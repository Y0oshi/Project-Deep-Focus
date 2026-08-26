import ipaddress
import sys
import logging
import time
from typing import Optional, Tuple

sys.path.append(".") 
from execution import db_manager

CHUNK_SIZE = 256
MAX_RETRIES = 3

# when maintenance last ran (Unix timestamp)
last_maintenance_ts = 0

async def initialize_scan(target_cidr: str, priority: int = 1):
    """Split a CIDR into /24-sized chunks and enqueue them."""
    try:
        network = ipaddress.ip_network(target_cidr, strict=False)
    except ValueError:
        logging.error(f"Invalid CIDR provided: {target_cidr}")
        return

    logging.info(f"[*] Initializing scan for {network} with priority {priority}...")

    if network.num_addresses <= CHUNK_SIZE:
        await db_manager.create_scan_chunk(str(network), str(network[0]), str(network[-1]), priority)
    else:
        for subnet in network.subnets(new_prefix=24):
            await db_manager.create_scan_chunk(str(target_cidr), str(subnet[0]), str(subnet[-1]), priority)

async def get_next_chunk() -> Optional[Tuple[int, str, str]]:
    """Return the next chunk to scan, marking it SCANNING. Skips chunks over the retry limit."""
    await maintain_queue_health()

    while True:
        chunk = await db_manager.get_next_chunk()
        if not chunk:
            return None

        chunk_id, start_ip, end_ip, retries = chunk

        if retries >= MAX_RETRIES:
            logging.warning(f"Chunk {chunk_id} exceeded max retries. Marking FAILED.")
            await db_manager.update_chunk_status(chunk_id, "FAILED", error="Max Retries Exceeded")
            continue

        await db_manager.update_chunk_status(chunk_id, "SCANNING")
        return chunk_id, start_ip, end_ip

async def complete_chunk(chunk_id: int):
    """Mark a chunk as successfully completed."""
    await db_manager.update_chunk_status(chunk_id, "COMPLETED")

async def fail_chunk(chunk_id: int, error: str):
    """Mark a chunk as RETRYING so it gets picked up again."""
    await db_manager.update_chunk_status(chunk_id, "RETRYING", error=str(error))

async def maintain_queue_health():
    """Run hourly maintenance: promote starved chunks and rescan stale ones."""
    global last_maintenance_ts

    if time.time() - last_maintenance_ts < 3600:
        return

    logging.info("[Scheduler] Running queue maintenance...")

    await db_manager.promote_ignored_chunks(age_hours=48)

    stale = await db_manager.get_stale_chunks(limit=50, min_age_hours=24)
    for row in stale:
        await db_manager.reset_stale_chunk(row[0])

    last_maintenance_ts = time.time()
