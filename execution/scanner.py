import asyncio
import sys
import argparse
import logging
import time
import socket
import struct
import os
from typing import List

# Local imports
sys.path.append(".") 
from execution import db_manager, fingerprint, scheduler, probes

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def worker(queue: asyncio.Queue, result_buffer: List, buffer_lock: asyncio.Lock, batch_size=50):
    """
    Worker coroutine that processes scan tasks from the queue.
    Executes probes, fingerprints services, and buffers results for batch insertion.
    """
    while True:
        try:
            item = await queue.get()
            if item is None:
                queue.task_done()
                break
            
            target_ip, port = item
            
            # 1. Resolve appropriate probe implementation
            probe = probes.get_probe(port)
            
            # 2. execute Probe (Returns Observation object)
            observation = await probe.run(target_ip)
            
            # 3. Analyze / Fingerprint (Returns dict with confidence/evidence)
            obs_dict = observation.to_dict()
            analysis_result = fingerprint.analyze(obs_dict)
            obs_dict['analysis'] = analysis_result
            
            # 4. Log Open Ports & Buffer Result
            if observation.status == "open":
                logging.info(f"[+] {target_ip}:{port} OPEN | {analysis_result['vendor']} {analysis_result['product']}")
                
            async with buffer_lock:
                result_buffer.append(obs_dict)
                if len(result_buffer) >= batch_size:
                    # Flush Batch to DB
                    await db_manager.save_observation_batch(result_buffer)
                    result_buffer.clear()

            queue.task_done()
            
        except Exception as e:
            logging.error(f"Worker Exception: {e}")
            queue.task_done()

async def scan_chunk(chunk_id, start_ip, end_ip, ports, rate):
    """
    Orchestrates the scanning of a single IP chunk (range).
    """
    logging.info(f"[*] Starting Chunk {chunk_id} ({start_ip} - {end_ip})")
    
    # helper for IP math
    def ip2long(ip): return struct.unpack("!L", socket.inet_aton(ip))[0]
    def long2ip(l): return socket.inet_ntoa(struct.pack("!L", l))
    
    start_long = ip2long(start_ip)
    end_long = ip2long(end_ip)
    
    # Task Queue Setup
    queue = asyncio.Queue()
    result_buffer = []
    buffer_lock = asyncio.Lock()
    
    # Create Worker Pool
    workers = []
    for _ in range(rate): 
        w = asyncio.create_task(worker(queue, result_buffer, buffer_lock))
        workers.append(w)
        
    # Populate Queue with Targets
    for l in range(start_long, end_long + 1):
        target_ip = long2ip(l)
        for port in ports:
            queue.put_nowait((target_ip, port))
            
    # Wait for completion
    await queue.join()
    
    # Graceful Shutdown
    for _ in range(len(workers)):
        queue.put_nowait(None)
    await asyncio.gather(*workers)
    
    # Flush remaining buffer data
    async with buffer_lock:
        if result_buffer:
            await db_manager.save_observation_batch(result_buffer)
    
    logging.info(f"[*] Chunk {chunk_id} Complete")
    await scheduler.complete_chunk(chunk_id)

def check_thermal_governor(max_load=6.0, cool_down_target=3.0):
    """
    Monitors system load average to prevent thermal throttling on passive systems (e.g. M1/M2 Air).
    Returns True if execution was paused, False otherwise.
    """
    # Windows Compatibility check
    if not hasattr(os, "getloadavg"):
        return False

    try:
        current_load = os.getloadavg()[0] # 1 minute load average
        
        if current_load > max_load:
            logging.warning(f"[Thermal Governor] High Load Detected ({current_load:.2f}). Pausing execution...")
            
            # Wait until load drops below target
            while current_load > cool_down_target:
                time.sleep(30)
                current_load = os.getloadavg()[0]
                
            logging.info(f"[Thermal Governor] System stabilized ({current_load:.2f}). Resuming scan.")
            return True 
            
    except (AttributeError, OSError):
        pass 
        
    return False

async def main():
    parser = argparse.ArgumentParser(description="Deep Focus Scanner Engine")
    parser.add_argument("--target", help="CIDR range to scan")
    parser.add_argument("--priority", type=int, default=1, help="Job priority")
    parser.add_argument("--ports", help="Ports to scan (comma separated)", default="80,443,22,21,8080,5900,554,3389")
    parser.add_argument("--rate", type=int, default=300, help="Concurrent threads")
    parser.add_argument("--loop", action="store_true", help="Keep running continuously")
    parser.add_argument("--max-load", type=float, default=6.0, help="Thermal throttling threshold")
    parser.add_argument("--cool-down", type=float, default=3.0, help="Resume threshold")
    args = parser.parse_args()

    # Initialize Database
    await db_manager.init_db()
    
    target_ports = [int(p) for p in args.ports.split(",")]

    # Seed initial target if provided
    if args.target:
        await scheduler.initialize_scan(args.target, priority=args.priority)
    
    chunks_processed_count = 0
    
    logging.info(f"[*] Engine Started. Threads: {args.rate}, Ports: {len(target_ports)}")
    
    while True:
        # 1. Thermal Safety Check
        check_thermal_governor(max_load=args.max_load, cool_down_target=args.cool_down)
        
        # 2. Database Maintenance (Periodic)
        if chunks_processed_count > 0 and chunks_processed_count % 50 == 0:
             await db_manager.prune_old_data()

        # 3. Get Next Job
        chunk = await scheduler.get_next_chunk()
        
        if chunk:
            chunk_id, start_ip, end_ip = chunk
            
            if not start_ip or not end_ip:
                logging.error(f"Invalid chunk data: {chunk_id}")
                await scheduler.fail_chunk(chunk_id, "Invalid Range")
                continue

            try:
                await scan_chunk(chunk_id, start_ip, end_ip, target_ports, args.rate)
                chunks_processed_count += 1
                
                # Small breather to allow OS to process IO
                if chunks_processed_count % 5 == 0:
                    time.sleep(1) 
                    
            except Exception as e:
                logging.error(f"Chunk {chunk_id} execution failed: {e}")
                await scheduler.fail_chunk(chunk_id, str(e))
        else:
            if not args.loop:
                logging.info("[*] Queue empty. Exiting.")
                break
            # Wait for new jobs
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Interrupted by user.")
