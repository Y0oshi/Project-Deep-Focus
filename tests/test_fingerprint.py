import unittest

from execution import fingerprint as fp


def _obs(banner=None, headers=None, body=None, cert_info=None):
    return {
        "banner": banner,
        "headers": headers or {},
        "body": body,
        "cert_info": cert_info or {},
    }


class TestFingerprintRules(unittest.TestCase):
    def test_apache_banner(self):
        r = fp.analyze(_obs(banner="HTTP/1.1 200 OK\r\nServer: Apache/2.4.54"))
        self.assertEqual(r["vendor"], "Apache")
        self.assertEqual(r["service_type"], "http")
        self.assertEqual(r["version"], "2.4.54")

    def test_nginx_header(self):
        r = fp.analyze(_obs(headers={"server": "nginx/1.18.0"}))
        self.assertEqual(r["vendor"], "Nginx")

    def test_openssh(self):
        r = fp.analyze(_obs(banner="SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.1"))
        self.assertEqual(r["vendor"], "OpenBSD")
        self.assertEqual(r["service_type"], "ssh")

    def test_dropbear(self):
        r = fp.analyze(_obs(banner="SSH-2.0-dropbear_2020.81"))
        self.assertEqual(r["vendor"], "Dropbear")
        self.assertEqual(r["service_type"], "ssh")

    def test_mikrotik(self):
        r = fp.analyze(_obs(banner="SSH-2.0-ROSSSH"))
        self.assertEqual(r["service_type"], "ssh")  # generic fallback
        r = fp.analyze(_obs(banner="SSH-2.0-MikroTik_7.1"))
        self.assertEqual(r["vendor"], "MikroTik")

    def test_cisco(self):
        r = fp.analyze(_obs(banner="SSH-1.99-Cisco-1.25"))
        self.assertEqual(r["vendor"], "Cisco")

    def test_generic_ssh_fallback(self):
        r = fp.analyze(_obs(banner="SSH-2.0-Whatever"))
        self.assertEqual(r["service_type"], "ssh")
        self.assertEqual(r["vendor"], "unknown")

    def test_vsftpd(self):
        r = fp.analyze(_obs(banner="220 (vsFTPd 3.0.3)"))
        self.assertEqual(r["service_type"], "ftp")

    def test_hikvision(self):
        r = fp.analyze(_obs(body="<title>Hikvision</title>", headers={"server": "App-webs/"}))
        self.assertEqual(r["vendor"], "Hikvision")

    def test_vnc(self):
        r = fp.analyze(_obs(banner="RFB 003.008"))
        self.assertEqual(r["service_type"], "vnc")
        self.assertEqual(r["vendor"], "RealVNC")

    def test_unknown_returns_unknown(self):
        r = fp.analyze(_obs(banner=""))
        self.assertEqual(r["vendor"], "unknown")
        self.assertEqual(r["confidence"], 0)

    def test_version_not_stale_between_calls(self):
        # A rule that matched with a version, followed by one that matches without
        # a capture group, must not leak the previous version.
        fp.analyze(_obs(banner="Apache/2.4.54"))
        r = fp.analyze(_obs(banner="nginx"))
        self.assertIsNone(r["version"])


if __name__ == "__main__":
    unittest.main()
