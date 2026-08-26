import asyncio
import sys
import argparse
import logging
import socket
import struct
import os
import random
import signal

sys.path.append(".")
from execution import db_manager, fingerprint, scheduler, probes

# Fallback names for ports we can't fingerprint.
COMMON_PORTS = {
    21: "ftp", 22: "ssh", 23: "telnet", 80: "http", 443: "https",
    554: "rtsp", 1883: "mqtt", 3389: "rdp", 5900: "vnc", 8080: "http-alt"
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

_shutdown_requested = False
# Workers pause while this event is cleared; it starts set so they run.
thermal_resume = asyncio.Event()
thermal_resume.set()


def _request_shutdown(signum, frame):
    """Signal handler that asks the engine to stop cleanly."""
    global _shutdown_requested
    _shutdown_requested = True
    logging.info(f"Received signal {signum}. Shutting down gracefully...")


async def thermal_monitor(max_load=6.0, cool_down_target=3.0, poll_interval=5.0):
    """Pause workers while system load is high, resume once it cools down."""
    if not hasattr(os, "getloadavg"):
        return

    while not _shutdown_requested:
        try:
            current = os.getloadavg()[0]
            if current > max_load:
                thermal_resume.clear()
                logging.warning(f"[Thermal Governor] High load ({current:.2f}) > {max_load}. Pausing workers.")
                while not _shutdown_requested and os.getloadavg()[0] > cool_down_target:
                    await asyncio.sleep(poll_interval)
                thermal_resume.set()
                logging.info("[Thermal Governor] Load stabilized. Resuming workers.")
        except (AttributeError, OSError):
            pass
        await asyncio.sleep(poll_interval)


async def worker(queue, result_buffer, buffer_lock, batch_size=50):
    """Pull targets from the queue, probe them, and buffer open results for batch insert."""
    while True:
        await thermal_resume.wait()

        item = await queue.get()
        if item is None:
            queue.task_done()
            break

        target_ip, port = item
        try:
            probe = probes.get_probe(port)
            observation = await probe.run(target_ip)

            # Skip anything that isn't open — no point storing noise.
            if observation.status != "open":
                continue

            obs_dict = observation.to_dict()
            analysis_result = fingerprint.analyze(obs_dict)
            # The fingerprint rules only know "http", so keep the probe's
            # "https"/"ldaps" designation instead of flattening it.
            if observation.service in ("https", "ldaps"):
                analysis_result["service_type"] = observation.service
            obs_dict['analysis'] = analysis_result

            vendor = analysis_result['vendor']
            product = analysis_result['product']

            # Unknown services get a generic name so the dashboard isn't blank.
            if str(vendor).lower() == "unknown" and str(product).lower() == "unknown":
                if port in COMMON_PORTS:
                    svc_name = COMMON_PORTS[port]
                    product = f"{svc_name} (Generic)"
                    vendor = "Generic"
                    obs_dict['analysis']['service_type'] = svc_name
                    obs_dict['analysis']['vendor'] = vendor
                else:
                    try:
                        svc_name = socket.getservbyport(port)
                        product = f"{svc_name} (Generic)"
                        obs_dict['analysis']['service_type'] = svc_name
                    except OSError:
                        pass
                obs_dict['analysis']['product'] = product

            logging.info(f"[+] {target_ip}:{port} OPEN | {vendor} {product}")

            # Swap the batch out under the lock so we don't await the DB write
            # while still holding it.
            batch = None
            async with buffer_lock:
                result_buffer.append(obs_dict)
                if len(result_buffer) >= batch_size:
                    batch = list(result_buffer)
                    result_buffer.clear()

            if batch is not None:
                await db_manager.save_observation_batch(batch)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(f"Worker Exception: {e}")
        finally:
            queue.task_done()


async def scan_chunk(chunk_id, start_ip, end_ip, ports, rate):
    """Scan one chunk (a /24 or smaller) across the given ports."""
    logging.info(f"[*] Starting Chunk {chunk_id} ({start_ip} - {end_ip})")

    def ip2long(ip): return struct.unpack("!L", socket.inet_aton(ip))[0]
    def long2ip(l): return socket.inet_ntoa(struct.pack("!L", l))

    start_long = ip2long(start_ip)
    end_long = ip2long(end_ip)

    # Shuffle hosts so they aren't hit in sequential order.
    targets = []
    for l in range(start_long, end_long + 1):
        target_ip = long2ip(l)
        for port in ports:
            targets.append((target_ip, port))
    random.shuffle(targets)

    queue = asyncio.Queue()
    result_buffer = []
    buffer_lock = asyncio.Lock()

    workers = [asyncio.create_task(worker(queue, result_buffer, buffer_lock)) for _ in range(rate)]

    for t in targets:
        queue.put_nowait(t)

    # Wait for the queue to drain, but bail early if shutdown is requested.
    while not _shutdown_requested:
        try:
            await asyncio.wait_for(queue.join(), timeout=1.0)
            break
        except asyncio.TimeoutError:
            continue

    if _shutdown_requested:
        # Cancel workers and flush whatever we have so results aren't lost.
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        async with buffer_lock:
            if result_buffer:
                await db_manager.save_observation_batch(result_buffer)
                result_buffer.clear()
        await scheduler.fail_chunk(chunk_id, "Shutdown")
        logging.info(f"[*] Chunk {chunk_id} aborted due to shutdown; partial results flushed.")
        return

    for _ in range(len(workers)):
        queue.put_nowait(None)
    await asyncio.gather(*workers)

    async with buffer_lock:
        if result_buffer:
            await db_manager.save_observation_batch(result_buffer)

    logging.info(f"[*] Chunk {chunk_id} Complete")
    await scheduler.complete_chunk(chunk_id)


async def main():
    parser = argparse.ArgumentParser(description="Deep Focus Scanner Engine")
    parser.add_argument("--target", help="CIDR range to scan")
    parser.add_argument("--priority", type=int, default=1, help="Job priority")
    parser.add_argument("--ports", help="Ports to scan (comma separated)",
                        default="80,443,22,21,8080,5900,554,3389,23,1883,25,587,636")
    parser.add_argument("--rate", type=int, default=300, help="Concurrent threads")
    parser.add_argument("--loop", action="store_true", help="Keep running continuously")
    parser.add_argument("--max-load", type=float, default=6.0, help="Thermal throttling threshold")
    parser.add_argument("--cool-down", type=float, default=3.0, help="Resume threshold")
    args = parser.parse_args()

    # Catch SIGTERM (from /stop) and SIGINT for a clean shutdown.
    signal.signal(signal.SIGTERM, _request_shutdown)
    try:
        signal.signal(signal.SIGINT, _request_shutdown)
    except ValueError:
        pass  # not the main thread

    await db_manager.init_db()

    target_ports = [int(p) for p in args.ports.split(",") if p.strip()]

    if args.target:
        await scheduler.initialize_scan(args.target, priority=args.priority)

    monitor_task = asyncio.create_task(thermal_monitor(args.max_load, args.cool_down))

    chunks_processed_count = 0

    logging.info(f"[*] Engine Started. Threads: {args.rate}, Ports: {len(target_ports)}")

    try:
        while not _shutdown_requested:
            if chunks_processed_count > 0 and chunks_processed_count % 50 == 0:
                await db_manager.prune_old_data()

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

                    # Let the OS settle between batches.
                    if chunks_processed_count % 5 == 0:
                        await asyncio.sleep(1)

                except Exception as e:
                    logging.error(f"Chunk {chunk_id} execution failed: {e}")
                    await scheduler.fail_chunk(chunk_id, str(e))
            else:
                if not args.loop:
                    logging.info("[*] Queue empty. Exiting.")
                    break
                await asyncio.sleep(5)
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

    logging.info("[*] Engine stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Interrupted by user.")
