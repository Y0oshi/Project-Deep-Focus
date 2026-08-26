import asyncio
import os
import socket
import tempfile
import unittest
from pathlib import Path

import aiosqlite

from execution import db_manager, scanner
from execution import probes as probes_mod
from tests import helpers


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ScannerTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db = db_manager.DB_PATH
        db_manager.DB_PATH = Path(self._tmp.name) / "results.db"
        scanner._shutdown_requested = False
        scanner.thermal_resume.set()

    def tearDown(self):
        scanner._shutdown_requested = False
        scanner.thermal_resume.set()
        db_manager.DB_PATH = self._orig_db
        self._tmp.cleanup()


class TestWorker(ScannerTestBase):
    async def test_worker_buffers_only_open(self):
        await db_manager.init_db()
        srv = helpers.FakeServer(lambda c: c.sendall(b"HTTP/1.1 200 OK\r\nServer: nginx\r\n\r\n"))
        q = asyncio.Queue()
        q.put_nowait(("127.0.0.1", srv.port))   # open
        q.put_nowait(("127.0.0.1", closed_port()))  # closed
        q.put_nowait(None)

        buf = []
        lock = asyncio.Lock()
        try:
            await scanner.worker(q, buf, lock, batch_size=50)
        finally:
            srv.stop()

        self.assertEqual(len(buf), 1)
        self.assertEqual(buf[0]["port"], srv.port)
        self.assertEqual(buf[0]["status"], "open")


class TestWorkerHttps(ScannerTestBase):
    async def test_worker_preserves_https_service_type(self):
        # The fingerprint rules only know "http"; the worker must keep the
        # probe's "https"/"ldaps" designation so TLS web services aren't
        # mislabeled as "http".
        await db_manager.init_db()

        class FakeProbe:
            def __init__(self, port):
                self.port = port

            async def run(self, ip):
                return probes_mod.Observation(
                    ip=ip, port=self.port, protocol="tcp", service="https",
                    latency_ms=1.0, status="open",
                    banner="HTTP/1.1 200 OK\r\nServer: nginx",
                )

        orig = scanner.probes.get_probe
        scanner.probes.get_probe = lambda port: FakeProbe(port)
        try:
            q = asyncio.Queue()
            q.put_nowait(("1.2.3.4", 443))
            q.put_nowait(None)
            buf = []
            await scanner.worker(q, buf, asyncio.Lock(), batch_size=50)
        finally:
            scanner.probes.get_probe = orig

        self.assertEqual(len(buf), 1)
        self.assertEqual(buf[0]["analysis"]["service_type"], "https")


class TestScanChunk(ScannerTestBase):
    async def test_persists_only_open(self):
        await db_manager.init_db()
        await db_manager.create_scan_chunk("127.0.0.1/32", "127.0.0.1", "127.0.0.1")
        srv = helpers.FakeServer(lambda c: c.sendall(b"HTTP/1.1 200 OK\r\nServer: nginx\r\n\r\n"))
        closed = closed_port()
        try:
            await scanner.scan_chunk(1, "127.0.0.1", "127.0.0.1", [srv.port, closed], 5)
        finally:
            srv.stop()

        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT port, state FROM services") as c:
                rows = await c.fetchall()

        ports = {r[0] for r in rows}
        self.assertIn(srv.port, ports)
        self.assertNotIn(closed, ports)

    async def test_graceful_shutdown_flushes_and_marks_retry(self):
        await db_manager.init_db()
        await db_manager.create_scan_chunk("127.0.0.1/32", "127.0.0.1", "127.0.0.1")
        scanner._shutdown_requested = True
        await scanner.scan_chunk(1, "127.0.0.1", "127.0.0.1", [80, 443], 5)

        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT status FROM scan_state WHERE id=1") as c:
                status = (await c.fetchone())[0]
        self.assertEqual(status, "RETRYING")


class TestThermalMonitor(ScannerTestBase):
    async def test_pauses_then_resumes(self):
        orig = os.getloadavg
        state = {"v": 99.0}
        os.getloadavg = lambda: (state["v"], 0.0, 0.0)
        scanner.thermal_resume.set()

        task = asyncio.create_task(
            scanner.thermal_monitor(max_load=6.0, cool_down_target=3.0, poll_interval=0.05)
        )
        try:
            await asyncio.sleep(0.25)
            self.assertFalse(scanner.thermal_resume.is_set(), "should be paused under high load")
            state["v"] = 0.0
            await asyncio.sleep(0.25)
            self.assertTrue(scanner.thermal_resume.is_set(), "should resume once load drops")
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            os.getloadavg = orig
            scanner.thermal_resume.set()


class TestShutdownFlag(ScannerTestBase):
    async def test_request_shutdown_sets_flag(self):
        scanner._shutdown_requested = False
        scanner._request_shutdown(15, None)
        self.assertTrue(scanner._shutdown_requested)


if __name__ == "__main__":
    unittest.main()
