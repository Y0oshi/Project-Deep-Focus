import tempfile
import time
import unittest
from pathlib import Path

import aiosqlite

from execution import db_manager


def make_obs(ip="1.2.3.4", port=80, status="open", banner="", analysis=None):
    return {
        "ip": ip,
        "port": port,
        "protocol": "tcp",
        "status": status,
        "timestamp": time.time(),
        "banner": banner,
        "analysis": analysis or {
            "service_type": "http", "vendor": "Nginx", "product": "Nginx",
            "version": "1.18", "confidence": 100, "tags": ["web"],
        },
    }


class DbTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = db_manager.DB_PATH
        db_manager.DB_PATH = Path(self._tmp.name) / "results.db"

    def tearDown(self):
        db_manager.DB_PATH = self._orig
        self._tmp.cleanup()


class TestDbManager(DbTestBase):
    async def test_init_db_creates_tables(self):
        await db_manager.init_db()
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as c:
                tables = {r[0] async for r in c}
        for t in ("hosts", "services", "history", "scan_state"):
            self.assertIn(t, tables)

    async def test_save_and_update_preserves_good_data(self):
        await db_manager.init_db()
        good = {"service_type": "http", "vendor": "Nginx", "product": "Nginx",
                "version": "1.18", "confidence": 100, "tags": ["web"]}
        await db_manager.save_observation_batch([make_obs(banner="nginx", analysis=good)])

        # Re-scan with an 'unknown' fingerprint — should NOT downgrade.
        unknown = {"service_type": "unknown", "vendor": "unknown", "product": "unknown",
                   "version": None, "confidence": 0, "tags": []}
        await db_manager.save_observation_batch([make_obs(banner="changed", analysis=unknown)])

        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute(
                "SELECT vendor, confidence, banner FROM services WHERE ip='1.2.3.4' AND port=80"
            ) as c:
                vendor, confidence, banner = await c.fetchone()

        self.assertEqual(vendor, "Nginx")
        self.assertEqual(confidence, 100)
        self.assertEqual(banner, "changed")  # banner is always refreshed

    async def test_history_recorded_on_change(self):
        await db_manager.init_db()
        await db_manager.save_observation_batch([make_obs(banner="v1")])
        await db_manager.save_observation_batch([make_obs(banner="v2")])
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM history") as c:
                n = (await c.fetchone())[0]
        self.assertGreaterEqual(n, 1)

    async def test_chunk_lifecycle(self):
        await db_manager.init_db()
        await db_manager.create_scan_chunk("10.0.0.0/24", "10.0.0.0", "10.0.0.255")
        row = await db_manager.get_next_chunk()
        self.assertIsNotNone(row)
        chunk_id, start, end, retries = row
        self.assertEqual((start, end), ("10.0.0.0", "10.0.0.255"))
        await db_manager.update_chunk_status(chunk_id, "COMPLETED")
        # No more queued chunks.
        self.assertIsNone(await db_manager.get_next_chunk())

    async def test_get_stale_chunks(self):
        await db_manager.init_db()
        await db_manager.create_scan_chunk("10.0.0.0/24", "10.0.0.0", "10.0.0.255")
        await db_manager.update_chunk_status(1, "COMPLETED")
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            await db.execute("UPDATE scan_state SET updated_at = '2000-01-01T00:00:00'")
            await db.commit()
        stale = await db_manager.get_stale_chunks(limit=10, min_age_hours=24)
        self.assertEqual(len(stale), 1)

    async def test_reset_stale_chunk(self):
        await db_manager.init_db()
        await db_manager.create_scan_chunk("10.0.0.0/24", "10.0.0.0", "10.0.0.255")
        await db_manager.reset_stale_chunk(1)
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT status FROM scan_state WHERE id=1") as c:
                status = (await c.fetchone())[0]
        self.assertEqual(status, "QUEUED")

    async def test_promote_ignored_chunks(self):
        await db_manager.init_db()
        await db_manager.create_scan_chunk("10.0.0.0/24", "10.0.0.0", "10.0.0.255")
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            await db.execute("UPDATE scan_state SET created_at = '2000-01-01T00:00:00'")
            await db.commit()
        await db_manager.promote_ignored_chunks(age_hours=48)
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT priority FROM scan_state WHERE id=1") as c:
                priority = (await c.fetchone())[0]
        self.assertEqual(priority, 2)

    async def test_prune_old_data(self):
        await db_manager.init_db()
        await db_manager.save_observation_batch([make_obs()])
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            await db.execute("UPDATE services SET last_seen = '2000-01-01T00:00:00'")
            await db.commit()
        await db_manager.prune_old_data()
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM services") as c:
                n = (await c.fetchone())[0]
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
