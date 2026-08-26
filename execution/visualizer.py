import sqlite3
import time
import sys
import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.align import Align
from rich import box
from rich.text import Text

sys.path.append(".")

console = Console()

DB_PATH = Path(__file__).resolve().parent.parent / "results.db"

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
    """Read live metrics from the database, tolerating lock contention."""
    try:
        cursor = db.cursor()
        stats = {}

        cursor.execute("SELECT COUNT(*) FROM hosts")
        stats['hosts'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM services")
        stats['services'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM scan_state WHERE status != 'COMPLETED'")
        stats['pending_chunks'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM history")
        churn_events = cursor.fetchone()[0]

        query = """
            SELECT ip, port, service_type, vendor, product, banner, confidence, first_seen, last_seen 
            FROM services 
            WHERE confidence > 0
            ORDER BY last_seen DESC 
            LIMIT 15
        """
        cursor.execute(query)
        recent_services = cursor.fetchall()
        
        return stats, churn_events, recent_services
    except Exception:
        # If DB is locked, return zeros to prevent UI crash
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
    
    layout["map"].update(
        Panel(Align.center(Text(ASCII_WORLD_MAP, style="bold red")), border_style="red")
    )

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
    
    if not recent_services:
        table.add_row(
            "[dim]Scanning...[/dim]", 
            "[dim]--[/dim]", 
            "[dim]Waiting for discoveries[/dim]", 
            "[dim]--[/dim]", 
            "[dim]--[/dim]"
        )
        
    layout["lower"].update(Panel(table, title="Live Index Feed"))
    
    return layout

def run_dashboard():
    """Main UI Loop."""
    print("Starting Dashboard (Sync Mode)... Connecting to DB...")
    
    try:
        # 5s timeout handles WAL locking contention.
        db = sqlite3.connect(str(DB_PATH), timeout=5.0)
        db.execute("PRAGMA journal_mode=WAL;")
        db.commit()
        print("DB Connection OK. Initializing UI...")
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return

    try:
        with Live(refresh_per_second=4, screen=True) as live:
            while True:
                try:
                    stats, churn, services = fetch_analytics(db)
                    layout = generate_layout(stats, churn, services)
                    live.update(layout)
                    time.sleep(0.5)
                except KeyboardInterrupt:
                    break
                except Exception:
                    time.sleep(1)
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
