import asyncio
import ipaddress
import sys
import logging
import time
from typing import Optional, Tuple

sys.path.append(".") 
from execution import db_manager

CHUNK_SIZE = 256 
MAX_RETRIES = 3

# V4 Maintenance State
last_maintenance_ts = 0

async def initialize_scan(target_cidr: str, priority: int = 1):
    """
    Splits the target CIDR into manageable chunks and enqueues them in the database.
    """
    try:
        network = ipaddress.ip_network(target_cidr, strict=False)
    except ValueError:
        logging.error(f"Invalid CIDR provided: {target_cidr}")
        return

    logging.info(f"[*] Initializing scan for {network} with priority {priority}...")
    
    # If network is small enough, make it a single chunk
    if network.num_addresses <= CHUNK_SIZE:
        await db_manager.create_scan_chunk(str(network), str(network[0]), str(network[-1]), priority)
    else:
        # Break down into /24s if possible, or just smaller chunks
        # Current logic assumes /24 chunks for simplicity
        if network.prefixlen < 24:
            subnets = network.subnets(new_prefix=24)
            for subnet in subnets:
                await db_manager.create_scan_chunk(str(target_cidr), str(subnet[0]), str(subnet[-1]), priority)
        else:
             # Just one chunk if it's smaller than a /24 but larger than CHUNK_SIZE?
             # (Not possible given num_addresses > 256 check above implies < /24)
             await db_manager.create_scan_chunk(str(network), str(network[0]), str(network[-1]), priority)

async def get_next_chunk() -> Optional[Tuple[int, str, str]]:
    """
    Retrieves the next highest priority chunk from the queue.
    Performs periodic maintenance before fetching.
    """
    await maintain_queue_health()
    
    chunk = await db_manager.get_next_chunk()
    if chunk:
        chunk_id, start_ip, end_ip, retries = chunk
        
        # Enforce Retry Limit
        if retries >= MAX_RETRIES:
             logging.warning(f"Chunk {chunk_id} exceeded max retries. Marking FAILED.")
             await db_manager.update_chunk_status(chunk_id, "FAILED", error="Max Retries Exceeded")
             return await get_next_chunk() # Recursively find next valid job
             
        await db_manager.update_chunk_status(chunk_id, "SCANNING")
        return chunk_id, start_ip, end_ip
        
    return None

async def complete_chunk(chunk_id: int):
    """Mark a chunk as successfully completed."""
    await db_manager.update_chunk_status(chunk_id, "COMPLETED")

async def fail_chunk(chunk_id: int, error: str):
    """
    Mark a chunk as failed (transiently).
    Increments retry count in DB.
    """
    await db_manager.update_chunk_status(chunk_id, "RETRYING", error=str(error))

async def maintain_queue_health():
    """
    V4: Periodic maintenance task (Auto-Rescan + Priority Promotion).
    Runs every hour to check for stale or starved tasks.
    """
    global last_maintenance_ts
    
    if time.time() - last_maintenance_ts < 3600: # Run hourly
        return
        
    logging.info("[Scheduler] Running V4 Queue Maintenance...")
    
    # 1. Promote ignored tasks (Anti-Starvation)
    await db_manager.promote_ignored_chunks(age_hours=48)
    
    # 2. Rescan High Priority (>24h stale)
    stale_high = await db_manager.get_stale_chunks(limit=50, high_priority=True, min_age_hours=24)
    for row in stale_high:
        await db_manager.reset_stale_chunk(row[0])
        
    # 3. Rescan Low Priority (>7d stale)
    stale_low = await db_manager.get_stale_chunks(limit=50, high_priority=False, min_age_hours=168)
    for row in stale_low:
        await db_manager.reset_stale_chunk(row[0])
        
    last_maintenance_ts = time.time()
