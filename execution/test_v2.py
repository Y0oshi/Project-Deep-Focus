import asyncio
import sys
import logging
sys.path.append(".") 
from execution import db_manager, scheduler, scanner

# Configure Logging
logging.basicConfig(level=logging.INFO)

async def test_integration():
    print("--- 1. Initialize DB ---")
    await db_manager.init_db()
    
    print("--- 2. Schedule Scan ---")
    # Scan Localhost/24 (simulated by just adding localhost to chunk actually)
    # But for invalid/safe test, let's use 127.0.0.1/32
    target = "127.0.0.1/32"
    await scheduler.initialize_scan(target)
    
    # Check Scan State
    chunk = await db_manager.get_pending_chunk()
    assert chunk is not None, "Scheduler failed to create chunk"
    print(f"Pending Chunk Found: {chunk}")
    
    print("--- 3. Run Scanner (One Loop) ---")
    # We'll run the scanner main logic manually to avoid infinite loop
    chunk_id, start, end = await scheduler.get_next_chunk()
    print(f"Processing Chunk {chunk_id}: {start}-{end}")
    
    # We need to simulate scanning real ports. 
    # scanner.scan_chunk works on creating workers.
    # Let's scan common ports on localhost.
    await scanner.scan_chunk(chunk_id, start, end, ports=[80, 22, 631, 8080], rate=10)
    
    print("--- 4. Verify Results ---")
    async with aiosqlite.connect(db_manager.DB_PATH) as db:
        async with db.execute("SELECT * FROM services") as c:
            services = await c.fetchall()
            print(f"Found {len(services)} services.")
            for s in services:
                print(s)
                
    print("--- V2 Integration Test Complete ---")

if __name__ == "__main__":
    import aiosqlite
    asyncio.run(test_integration())
