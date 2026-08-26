import tempfile
import time
import unittest
from pathlib import Path

import aiosqlite

from execution import db_manager, scheduler


class SchedulerTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = db_manager.DB_PATH
        db_manager.DB_PATH = Path(self._tmp.name) / "results.db"
        self._orig_maint = scheduler.last_maintenance_ts
        scheduler.last_maintenance_ts = time.time()  # keep maintenance off by default

    def tearDown(self):
        db_manager.DB_PATH = self._orig
        scheduler.last_maintenance_ts = self._orig_maint
        self._tmp.cleanup()

    async def _count_chunks(self):
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM scan_state") as c:
                return (await c.fetchone())[0]


class TestInitializeScan(SchedulerTestBase):
    async def test_small_network_single_chunk(self):
        await db_manager.init_db()
        await scheduler.initialize_scan("10.0.0.0/30")
        self.assertEqual(await self._count_chunks(), 1)

    async def test_24_single_chunk(self):
        await db_manager.init_db()
        await scheduler.initialize_scan("10.0.0.0/24")
        self.assertEqual(await self._count_chunks(), 1)

    async def test_23_splits_into_two(self):
        await db_manager.init_db()
        await scheduler.initialize_scan("10.0.0.0/23")
        self.assertEqual(await self._count_chunks(), 2)

    async def test_16_splits_into_256(self):
        await db_manager.init_db()
        await scheduler.initialize_scan("10.0.0.0/16")
        self.assertEqual(await self._count_chunks(), 256)

    async def test_invalid_cidr_handled(self):
        await db_manager.init_db()
        await scheduler.initialize_scan("not-a-cidr")
        self.assertEqual(await self._count_chunks(), 0)


class TestGetNextChunk(SchedulerTestBase):
    async def test_returns_chunk(self):
        await db_manager.init_db()
        await db_manager.create_scan_chunk("10.0.0.0/24", "10.0.0.0", "10.0.0.255")
        chunk = await scheduler.get_next_chunk()
        self.assertEqual(chunk, (1, "10.0.0.0", "10.0.0.255"))
        # Marked SCANNING.
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT status FROM scan_state WHERE id=1") as c:
                status = (await c.fetchone())[0]
        self.assertEqual(status, "SCANNING")

    async def test_retry_limit_marks_failed_no_recursion(self):
        await db_manager.init_db()
        await db_manager.create_scan_chunk("10.0.0.0/24", "10.0.0.0", "10.0.0.255")
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            await db.execute(f"UPDATE scan_state SET retry_count = {scheduler.MAX_RETRIES}")
            await db.commit()
        result = await scheduler.get_next_chunk()
        self.assertIsNone(result)
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT status FROM scan_state WHERE id=1") as c:
                status = (await c.fetchone())[0]
        self.assertEqual(status, "FAILED")

    async def test_empty_returns_none(self):
        await db_manager.init_db()
        self.assertIsNone(await scheduler.get_next_chunk())


class TestMaintenance(SchedulerTestBase):
    async def test_rescans_stale_completed_chunks(self):
        await db_manager.init_db()
        await db_manager.create_scan_chunk("10.0.0.0/24", "10.0.0.0", "10.0.0.255")
        await db_manager.update_chunk_status(1, "COMPLETED")
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            await db.execute("UPDATE scan_state SET updated_at = '2000-01-01T00:00:00'")
            await db.commit()
        scheduler.last_maintenance_ts = 0  # force maintenance
        await scheduler.maintain_queue_health()
        async with aiosqlite.connect(db_manager.DB_PATH) as db:
            async with db.execute("SELECT status FROM scan_state WHERE id=1") as c:
                status = (await c.fetchone())[0]
        self.assertEqual(status, "QUEUED")


if __name__ == "__main__":
    unittest.main()
