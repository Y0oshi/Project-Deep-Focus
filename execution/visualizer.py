import sqlite3
import time
import sys
import datetime
import os
from rich.console import Console
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.align import Align
from rich import box
from rich.text import Text

# Path hack to find modules if running from root
sys.path.append(".") 
# We only import db_manager to get DB_PATH string if needed, 
# but actually we can just hardcode "results.db" for simplicity/robustness here.

# Global Console Instance
console = Console()

# --- ASCII Graphics ---
ASCII_WORLD_MAP = r"""
██████╗ ███████╗███████╗██████╗ 
██╔══██╗██╔════╝██╔════╝██╔══██╗
██║  ██║█████╗  █████╗  ██████╔╝
██║  ██║██╔══╝  ██╔══╝  ██╔═══╝ 
██████╔╝███████╗███████╗██║     
╚═════╝ ╚══════╝╚══════╝╚═╝     

███████╗ ██████╗  ██████╗██╗   ██╗███████╗
██╔════╝██╔═══██╗██╔════╝██║   ██║██╔════╝
█████╗  ██║   ██║██║     ██║   ██║███████╗
██╔══╝  ██║   ██║██║     ██║   ██║╚════██║
██║     ╚██████╔╝╚██████╗╚██████╔╝███████║
╚═╝      ╚═════╝  ╚═════╝ ╚══════╝ ╚══════╝

      Made By Y0oshi  |  ig:rde0
"""

def fetch_analytics(db):
    """
    Retrieves real-time metrics from the SQLite database.
    Robust against database locks by using try/except with fallbacks.
    """
    try:
        cursor = db.cursor()
        stats = {}
        
        # Core Metrics
        cursor.execute("SELECT COUNT(*) FROM hosts")
        stats['hosts'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM services")
        stats['services'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM scan_state WHERE status != 'COMPLETED'")
        stats['pending_chunks'] = cursor.fetchone()[0]
            
        # Activity Metric
        cursor.execute("SELECT COUNT(*) FROM history")
        churn_events = cursor.fetchone()[0]

        # Recent Discoveries Feed
        query = """
            SELECT ip, port, service_type, vendor, product, banner, confidence, first_seen, last_seen 
            FROM services 
            ORDER BY last_seen DESC 
            LIMIT 15
        """
        cursor.execute(query)
        recent_services = cursor.fetchall()
        
        return stats, churn_events, recent_services
    except Exception as e:
        # If DB is locked, return zeros to prevent UI crash
        # Can happen frequently with high-speed writing
        return {'hosts':0, 'services':0, 'pending_chunks':0}, 0, []

def generate_layout(stats, churn, recent_services):
    """Constructs the Rich TUI Layout."""
    layout = Layout()
    layout.split_column(
        Layout(name="upper", size=18),
        Layout(name="lower")
    )
    layout["upper"].split_row(
        Layout(name="map", ratio=2),
        Layout(name="analytics", ratio=1)
    )
    
    # 1. Map Panel (Banner)
    layout["map"].update(
        Panel(Align.center(Text(ASCII_WORLD_MAP, style="bold red")), border_style="red")
    )
    
    # 2. Analytics Panel
    analytics_text = Text()
    analytics_text.append(f"Hosts Index:    {stats.get('hosts', 0)}\n", style="bold cyan")
    analytics_text.append(f"Services Index: {stats.get('services', 0)}\n", style="bold magenta")
    analytics_text.append(f"Pending Chunks: {stats.get('pending_chunks', 0)}\n", style="bold yellow")
    analytics_text.append(f"\nVolatility (Events): {churn}\n", style="bold red")
    
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    analytics_text.append(f"Status: Indexing... ({current_time})", style="dim")

    layout["analytics"].update(
        Panel(analytics_text, title="Deep Focus Intelligence (V4)", border_style="blue")
    )
    
    # 3. Live Feed Table
    table = Table(title="Real-time Observations", expand=True, box=box.SIMPLE_HEAD)
    table.add_column("Target", style="cyan")
    table.add_column("Service", style="green")
    table.add_column("Identity", style="yellow")
    table.add_column("Conf", style="bold white")
    table.add_column("Last Seen", style="dim")
    
    for svc in recent_services:
        ip, port, stype, vendor, product, banner, conf, first, last = svc
        
        target = f"{ip}:{port}"
        identity = f"{vendor or ''} {product or ''}".strip() or "Unknown"
        
        # Dynamic Confidence Coloring
        conf_style = "red"
        if conf and conf > 80: conf_style = "green"
        elif conf and conf > 50: conf_style = "yellow"
        
        table.add_row(
            target, 
            stype or "tcp", 
            identity, 
            Text(f"{conf}%", style=conf_style), 
            str(last)
        )
        
    layout["lower"].update(Panel(table, title="Live Index Feed"))
    
    return layout

def run_dashboard():
    """Main UI Loop."""
    print("Starting Dashboard (Sync Mode)... Connecting to DB...")
    
    try:
        # 5s timeout handles WAL locking contention
        db = sqlite3.connect("results.db", timeout=5.0)
        
        # Optimize Read Performance
        db.execute("PRAGMA journal_mode=WAL;")
        db.commit()
        print("DB Connection OK. Initializing UI...")
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return

    # Rich Live Display
    with Live(refresh_per_second=4, screen=True) as live:
        while True:
            try:
                # 1. Fetch Data
                stats, churn, services = fetch_analytics(db)
                
                # 2. Render Layout
                layout = generate_layout(stats, churn, services)
                live.update(layout)
                
                # 3. Frequency Cap
                time.sleep(0.5)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                time.sleep(1) # Backoff on error
    finally:
        try:
            db.close()
            print("DB Connection Closed.")
        except:
            pass

if __name__ == "__main__":
    try:
        run_dashboard()
    except KeyboardInterrupt:
        print("Exiting...")
