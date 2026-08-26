import asyncio
import socket
import tempfile
import unittest

from execution import probes
from tests import helpers


def closed_port():
    """Return a port that currently has no listener (hence connection refused)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ProbeTestBase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.cert, cls.key = helpers.make_self_signed_cert(cls._tmp.name)
        cls.have_tls = cls.cert is not None

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    async def run_probe(self, probe, handler):
        srv = helpers.FakeServer(handler)
        try:
            return await probe(srv.port).run("127.0.0.1")
        finally:
            srv.stop()


class TestTCPProbe(ProbeTestBase):
    async def test_open_with_banner(self):
        obs = await self.run_probe(
            probes.TCPProbe,
            lambda c: c.sendall(b"HELLO\r\n"),
        )
        self.assertEqual(obs.status, "open")
        self.assertIn("HELLO", obs.banner)

    async def test_closed_port(self):
        port = closed_port()
        obs = await probes.TCPProbe(port).run("127.0.0.1")
        self.assertEqual(obs.status, "closed")


class TestHTTPProbe(ProbeTestBase):
    async def test_http_parse(self):
        def handler(c):
            c.recv(4096)
            c.sendall(b"HTTP/1.1 200 OK\r\nServer: nginx/1.18.0\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello")

        obs = await self.run_probe(probes.HTTPProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertEqual(obs.response_code, 200)
        self.assertEqual(obs.headers.get("server"), "nginx/1.18.0")
        self.assertEqual(obs.service, "http")

    async def test_closed_port(self):
        port = closed_port()
        obs = await probes.HTTPProbe(port).run("127.0.0.1")
        self.assertEqual(obs.status, "closed")


class TestHTTPSProbe(ProbeTestBase):
    async def test_tls_cert_and_self_signed(self):
        if not self.have_tls:
            self.skipTest("openssl not available")
        def handler(c):
            c.recv(4096)
            c.sendall(b"HTTP/1.1 200 OK\r\nServer: apache\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")

        srv = helpers.make_tls_server(handler, self.cert, self.key, port=8443)
        try:
            obs = await probes.HTTPProbe(8443).run("127.0.0.1")
        finally:
            srv.stop()
        self.assertEqual(obs.status, "open")
        self.assertEqual(obs.service, "https")
        self.assertTrue(obs.cert_info.get("self_signed"))


class TestFTPProbe(ProbeTestBase):
    async def test_anonymous_allowed(self):
        def handler(c):
            c.sendall(b"220 (vsFTPd 3.0.3)\r\n")
            c.recv(1024)
            c.sendall(b"331 Please specify the password.\r\n")
            c.recv(1024)
            c.sendall(b"230 Login successful.\r\n")

        obs = await self.run_probe(probes.FTPProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("Anonymous Access ALLOWED", obs.banner)

    async def test_anonymous_denied(self):
        def handler(c):
            c.sendall(b"220 (vsFTPd 3.0.3)\r\n")
            c.recv(1024)
            c.sendall(b"331 Please specify the password.\r\n")
            c.recv(1024)
            c.sendall(b"530 Login incorrect.\r\n")

        obs = await self.run_probe(probes.FTPProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("DENIED", obs.banner)

    async def test_anonymous_550_rejected(self):
        # 550 on USER anonymous means "anonymous not allowed" — NOT a handshake error.
        def handler(c):
            c.sendall(b"220 ProFTPD Server\r\n")
            c.recv(1024)
            c.sendall(b"550 Anonymous login not allowed\r\n")

        obs = await self.run_probe(probes.FTPProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("Rejected", obs.banner)
        self.assertNotIn("Handshake Error", obs.banner)


class TestSSHProbe(ProbeTestBase):
    async def test_openssh(self):
        def handler(c):
            c.sendall(b"SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.1\r\n")
            c.recv(4096)
            # packet_len=20, pad_len=0, then msg_type 20 (KEXINIT) + 18 bytes
            c.sendall(b"\x00\x00\x00\x14\x00" + b"\x14" + b"\x00" * 18)

        obs = await self.run_probe(probes.SSHProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("OpenSSH", obs.banner)

    async def test_dropbear(self):
        def handler(c):
            c.sendall(b"SSH-2.0-dropbear_2020.81\r\n")
            c.recv(4096)
            c.sendall(b"\x00\x00\x00\x14\x00" + b"\x14" + b"\x00" * 18)

        obs = await self.run_probe(probes.SSHProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("Dropbear", obs.banner)


class TestVNCProbe(ProbeTestBase):
    async def test_no_auth(self):
        def handler(c):
            c.sendall(b"RFB 003.008\n")
            c.recv(12)
            c.sendall(b"\x01\x01")  # 1 security type: None

        obs = await self.run_probe(probes.VNCProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("None (OPEN)", obs.banner)


class TestRTSPProbe(ProbeTestBase):
    async def test_no_auth_hikvision(self):
        def handler(c):
            c.recv(4096)
            c.sendall(b"RTSP/1.0 200 OK\r\nCSeq: 1\r\nServer: Hikvision\r\n\r\n")

        obs = await self.run_probe(probes.RTSPProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("No Auth Required", obs.banner)
        self.assertIn("Hikvision", obs.banner)

    async def test_auth_required(self):
        def handler(c):
            c.recv(4096)
            c.sendall(b"RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\n\r\n")

        obs = await self.run_probe(probes.RTSPProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("Auth Required", obs.banner)


class TestTelnetProbe(ProbeTestBase):
    async def test_banner_control_chars_stripped(self):
        def handler(c):
            c.sendall(b"Welcome!\xff\xfe\x01\x02login: ")

        obs = await self.run_probe(probes.TelnetProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("Welcome!", obs.banner)
        self.assertNotIn("\xff", obs.banner)


class TestMQTTProbe(ProbeTestBase):
    async def test_no_auth(self):
        def handler(c):
            c.recv(4096)
            c.sendall(bytes.fromhex("20020000"))  # CONNACK accepted

        obs = await self.run_probe(probes.MQTTProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("Access ALLOWED", obs.banner)


class TestRDPProbe(ProbeTestBase):
    async def test_legacy(self):
        def handler(c):
            c.recv(4096)
            c.sendall(bytes.fromhex("0300000b06d00000123400"))  # X.224 CC

        obs = await self.run_probe(probes.RDPProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("RDP", obs.banner)


class TestSMTPProbe(ProbeTestBase):
    async def test_no_starttls(self):
        def handler(c):
            c.sendall(b"220 smtp.example.com ESMTP\r\n")
            c.recv(4096)
            c.sendall(b"250-smtp.example.com\r\n250 8BITMIME\r\n")

        obs = await self.run_probe(probes.SMTPProbe, handler)
        self.assertEqual(obs.status, "open")
        self.assertIn("STARTTLS:[NO]", obs.banner)


class TestLDAPSProbe(ProbeTestBase):
    async def test_tls_open(self):
        if not self.have_tls:
            self.skipTest("openssl not available")
        def handler(c):
            c.recv(4096)

        srv = helpers.make_tls_server(handler, self.cert, self.key)
        try:
            obs = await probes.LDAPSProbe(srv.port).run("127.0.0.1")
        finally:
            srv.stop()
        self.assertEqual(obs.status, "open")
        self.assertEqual(obs.service, "ldaps")


class TestGetProbe(unittest.TestCase):
    def test_mapping(self):
        self.assertIsInstance(probes.get_probe(80), probes.HTTPProbe)
        self.assertIsInstance(probes.get_probe(443), probes.HTTPProbe)
        self.assertIsInstance(probes.get_probe(21), probes.FTPProbe)
        self.assertIsInstance(probes.get_probe(22), probes.SSHProbe)
        self.assertIsInstance(probes.get_probe(554), probes.RTSPProbe)
        self.assertIsInstance(probes.get_probe(23), probes.TelnetProbe)
        self.assertIsInstance(probes.get_probe(1883), probes.MQTTProbe)
        self.assertIsInstance(probes.get_probe(3389), probes.RDPProbe)
        self.assertIsInstance(probes.get_probe(25), probes.SMTPProbe)
        self.assertIsInstance(probes.get_probe(587), probes.SMTPProbe)
        self.assertIsInstance(probes.get_probe(636), probes.LDAPSProbe)
        self.assertIsInstance(probes.get_probe(5900), probes.VNCProbe)
        self.assertIsInstance(probes.get_probe(9999), probes.TCPProbe)


class TestErrorStatus(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(probes._error_status(asyncio.TimeoutError()), "timeout")
        self.assertEqual(probes._error_status(ConnectionRefusedError()), "closed")
        self.assertEqual(probes._error_status(ValueError("x")), "error")


if __name__ == "__main__":
    unittest.main()
