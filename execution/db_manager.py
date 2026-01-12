import aiosqlite
import logging
import datetime
import asyncio
from pathlib import Path
from typing import List, Tuple, Dict, Optional

DB_PATH = Path("results.db")

INIT_SCRIPT = """
-- Hosts: Basic IP info
CREATE TABLE IF NOT EXISTS hosts (
    ip TEXT PRIMARY KEY,
    country TEXT,
    city TEXT,
    lat REAL,
    lon REAL,
    first_seen DATETIME,
    last_seen DATETIME
);

-- Services: Current state
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT,
    port INTEGER,
    protocol TEXT,
    state TEXT,       
    service_type TEXT,
    vendor TEXT,
    product TEXT,
    version TEXT,
    banner TEXT,      
    confidence INTEGER, 
    tags TEXT,
    first_seen DATETIME,
    last_seen DATETIME,
    FOREIGN KEY(ip) REFERENCES hosts(ip),
    UNIQUE(ip, port, protocol)
);

-- History: Temporal changes
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER,
    timestamp DATETIME,
    banner TEXT,
    state TEXT,
    FOREIGN KEY(service_id) REFERENCES services(id)
);

-- Scan State (V3): Priority and Lifecycle
CREATE TABLE IF NOT EXISTS scan_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cidr TEXT,
    chunk_start TEXT, 
    chunk_end TEXT,   
    status TEXT,      -- QUEUED, SCANNING, RETRYING, COMPLETED, FAILED
    priority INTEGER DEFAULT 1, -- 1=Normal, 2=High
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    created_at DATETIME,
    updated_at DATETIME
);
"""

async def init_db():
    """Initialize the SQLite database schema if it doesn't await exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.executescript(INIT_SCRIPT)
        await db.commit()
    logging.info(f"Database initialized at {DB_PATH} (WAL Mode)")

# --- Batched Storage ---

async def upsert_host_batch(db, hosts_data: List[Tuple[str, float]]):
    """
    Batch upsert for hosts based on IP.
    Updates `last_seen` on conflict.
    """
    try:
        await db.executemany(
            """
            INSERT INTO hosts (ip, first_seen, last_seen) VALUES (?, ?, ?)
            ON CONFLICT(ip) DO UPDATE SET last_seen=excluded.last_seen
            """,
            [(ip, ts, ts) for ip, ts in hosts_data]
        )
    except Exception as e:
        logging.error(f"Batch Host Error: {e}")

async def save_observation_batch(observations: List[dict]):
    """
    Saves a batch of dictionary-formatted Observations.
    Handles upserts and history logic efficiently.
    """
    if not observations:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Batch Upsert Hosts
        hosts_data = [(obs['ip'], obs['timestamp']) for obs in observations]
        await upsert_host_batch(db, hosts_data)
        
        # 2. Process Services
        # Fetch status of existing services to determine if this is a new state
        ips = [f"'{obs['ip']}'" for obs in observations]
        ip_list_str = ",".join(ips)
        
        existing_map = {} # (ip, port, proto) -> (id, banner, state)
        async with db.execute(
            f"SELECT ip, port, protocol, id, banner, state FROM services WHERE ip IN ({ip_list_str})"
        ) as cursor:
            async for row in cursor:
                existing_map[(row[0], row[1], row[2])] = (row[3], row[4], row[5])
        
        to_insert = []
        to_update = []
        history_inserts = []
        
        for obs in observations:
            key = (obs['ip'], obs['port'], obs['protocol'])
            ts = datetime.datetime.fromtimestamp(obs['timestamp']).isoformat()
            
            # Enrich with analysis if present
            analysis = obs.get('analysis', {})
            
            if key in existing_map:
                svc_id, old_banner, old_state = existing_map[key]
                new_banner = obs.get('banner') or ""
                new_state = obs['status']
                
                to_update.append((
                    ts, new_banner, 
                    analysis.get('service_type'), analysis.get('vendor'), analysis.get('product'),
                    analysis.get('version'), analysis.get('confidence'), str(analysis.get('tags', [])),
                    new_state,
                    svc_id
                ))
                
                # History Check: Log separate event if state/banner changed
                if (new_banner and new_banner != old_banner) or (new_state != old_state):
                    history_inserts.append((svc_id, ts, new_banner, new_state))
            else:
                # New Service Discovery
                to_insert.append((
                    obs['ip'], obs['port'], obs['protocol'], obs['status'], obs.get('banner', ''),
                    analysis.get('service_type'), analysis.get('vendor'), analysis.get('product'),
                    analysis.get('version'), analysis.get('confidence', 0), str(analysis.get('tags', [])),
                    ts, ts
                ))
                
        # Bulk Execute
        if to_insert:
            await db.executemany(
                """
                INSERT INTO services (
                    ip, port, protocol, state, banner, 
                    service_type, vendor, product, version, confidence, tags,
                    first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, to_insert
            )
            
        if to_update:
             await db.executemany(
                """
                UPDATE services 
                SET last_seen = ?, 
                    banner = ?, 
                    service_type = COALESCE(?, service_type),
                    vendor = COALESCE(?, vendor),
                    product = COALESCE(?, product),
                    version = COALESCE(?, version),
                    confidence = COALESCE(?, confidence),
                    tags = COALESCE(?, tags),
                    state = ?
                WHERE id = ?
                """, to_update
            )
            
        if history_inserts:
            await db.executemany(
                "INSERT INTO history (service_id, timestamp, banner, state) VALUES (?, ?, ?, ?)",
                history_inserts
            )
            
        await db.commit()

async def get_stats():
    """Retrieve high-level index statistics."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM hosts") as c:
            hosts = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM services") as c:
            services = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM scan_state WHERE status != 'COMPLETED'") as c:
            pending = (await c.fetchone())[0]
    return {"hosts": hosts, "services": services, "pending_chunks": pending}


# --- Scheduler DB Ops ---

async def create_scan_chunk(cidr, start_ip, end_ip, priority=1):
    """Enqueues a new scan chunk."""
    now = datetime.datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO scan_state 
               (cidr, chunk_start, chunk_end, status, priority, created_at, updated_at) 
               VALUES (?, ?, ?, 'QUEUED', ?, ?, ?)""",
            (cidr, start_ip, end_ip, priority, now, now)
        )
        await db.commit()

async def get_next_chunk():
    """
    Fetch priority queue-style next chunk.
    Prioritizes Priority > Oldest Created.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id, chunk_start, chunk_end, retry_count 
               FROM scan_state 
               WHERE status IN ('QUEUED', 'RETRYING') 
               ORDER BY priority DESC, created_at ASC 
               LIMIT 1"""
        ) as cursor:
            row = await cursor.fetchone()
            
    if row:
        return row # id, start, end, retries
    return None

async def update_chunk_status(chunk_id, status, error=None):
    """Update lifecycle status of a chunk."""
    now = datetime.datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        if error:
            # Increment retry count if failing/retrying
            await db.execute(
                """UPDATE scan_state 
                   SET status = ?, last_error = ?, updated_at = ?, retry_count = retry_count + 1 
                   WHERE id = ?""",
                (status, error, now, chunk_id)
            )
        else:
            await db.execute(
                """UPDATE scan_state SET status = ?, updated_at = ? WHERE id = ?""",
                (status, now, chunk_id)
            )
        await db.commit()

# --- Maintenance DB Ops ---

async def get_stale_chunks(limit=10, high_priority=False, min_age_hours=24):
    """Find COMPLETED chunks that need rescanning."""
    now = datetime.datetime.now()
    cutoff = (now - datetime.timedelta(hours=min_age_hours)).isoformat()
    
    priority_filter = "priority >= 5" if high_priority else "priority < 5"
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"""SELECT id, cidr, priority, created_at 
               FROM scan_state 
               WHERE status = 'COMPLETED' 
               AND updated_at < ? 
               AND {priority_filter} 
               ORDER BY updated_at ASC 
               LIMIT ?""",
            (cutoff, limit)
        ) as cursor:
            return await cursor.fetchall()

async def reset_stale_chunk(chunk_id):
    """Reset a stale chunk to QUEUED for rescan."""
    now = datetime.datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE scan_state 
               SET status = 'QUEUED', updated_at = ?, retry_count = 0 
               WHERE id = ?""",
            (now, chunk_id)
        )
        await db.commit()
    logging.info(f"Chunk {chunk_id} reset for rescan.")

async def promote_ignored_chunks(age_hours=48):
    """Dynamic Priority Promotion. Bump priority if ignored for too long."""
    now = datetime.datetime.now()
    cutoff = (now - datetime.timedelta(hours=age_hours)).isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE scan_state 
               SET priority = priority + 1, updated_at = ?
               WHERE status = 'QUEUED' 
               AND created_at < ? 
               AND priority < 10""",
            (now.isoformat(), cutoff)
        )
        changes = db.total_changes
        await db.commit()
    if changes > 0:
        logging.info(f"Promoted {changes} ignored chunks.")

async def prune_old_data(history_days=30, service_days=90):
    """Rolling Retention Policy (GDPR / Disk Space)."""
    cutoff_history = (datetime.datetime.now() - datetime.timedelta(days=history_days)).isoformat()
    cutoff_service = (datetime.datetime.now() - datetime.timedelta(days=service_days)).isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM history WHERE timestamp < ?", (cutoff_history,))
        pruned_history = db.total_changes
        await db.execute("DELETE FROM services WHERE last_seen < ?", (cutoff_service,))
        pruned_services = db.total_changes
        await db.commit()
    
    if pruned_history > 0 or pruned_services > 0:
        logging.info(f"[Storage] Pruned {pruned_history} history, {pruned_services} services.")
