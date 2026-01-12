import sys
import subprocess
import time
import os
from pathlib import Path

# Local Code modules
from execution import config
from execution import visualizer 

# --- Configuration & Setup ---
sys.path.append(".")  # Ensure module path is correct

# --- ASCII Art & Branding ---
BANNER = r"""
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡼⢀⠀⠀⠘
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣾⣷⡿⠀⣀⣼
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣼⢛⣵⣶⣟⣽⣿
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡰⢎⣾⣿⣿⣿⣿⣩⠞
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣨⣾⣿⣿⣿⣿⠟⠉⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣤⣾⣿⣿⣿⡿⠋⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠹⡢⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣰⣾⣿⣿⡿⠋⠉⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠳⡄⠙⠦⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣰⣾⣿⣿⢟⣩⣶⠤⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⢦⠀⠈⠳⣦⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⣿⣿⠿⠋⠐⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡀⠀⠈⢧⠀⠓⠿⠙⣦⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⣿⡿⠛⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢖⢤⡈⠳⡄⠀⠀⠈⢷⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⢀⡀⠀⠀⢀⣴⣿⣿⡯⠖⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠙⢯⡉⠙⠒⠒⢒⣢⣤⣦⣤⠤⣀⣀⣀⣑⣼⡳⣜⣦⡀⠈⠉⠉⢣⡀⠀⠀⠀ ⠀⣠⣦⠾⢉⣿⢇⠀⣴⠿⠋⠛⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠙⠲⣄⡘⠁⠀⠀⠀⠐⠋⠀⢠⠒⠦⢭⣙⡳⢍⣿⣶⣄⠈⠒⠵⣄⠀⠀⠀⠀⠀⠀⣾⣻⣾⣾⣧⣦⣿⣅⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠉⠓⠲⠤⠤⠔⠢⣄⠀⠀⠀⠤⢴⣿⣟⣊⣉⣛⣳⠦⢄⣈⠓⠦⢄⡀⠀⠀⢻⢱⣿⠛⢁⠉⠁⠘⠳⡦⡤⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠓⠤⠤⢈⣁⣀⡀⡀⠀⠀⣀⣉⠁⠒⣭⣓⠦⢌⣒⣶⠶⠿⢻⡆⠈⢿⣤⣀⣠⠇⡿⡞⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⡤⠤⠒⠊⠉⠉⠉⠉⠙⠉⠙⠋⠙⠛⣛⣓⣶⣶⣶⡶⠭⣛⣿⣦⠂⠻⣟⠀⢰⡿⣥⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⣠⣤⣖⣒⡊⣭⠄⠀⠀⢀⡠⠴⠒⠪⡿⠋⣹⣷⣤⡶⢷⣿⢿⡟⠋⣡⣴⢿⢿⣿⣿⣿⣦⣜⠷⢟⣁⣹⣝⣆⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⡠⣔⣯⡶⣂⠤⠚⠉⢀⣀⣤⠮⠗⠚⣋⠭⠚⢁⠤⠞⠋⣠⢾⣿⢱⢃⢟⣿⣿⠃⢸⣿⣷⣄⣀⣈⣍⠛⠮⠷⢲⠾⣴⡷⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⢀⣠⣔⠯⠓⢉⣽⠟⠋⠀⢀⣀⣠⢞⣵⡾⣠⠖⠈⠀⠀⠀⠀⠀⡠⣺⣵⢫⣻⠇⡼⢸⣇⢻⠀⡼⢤⠈⠑⠃⡜⠀⠀⠀⠉⠉⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⢀⣤⠾⠛⠉⠀⠀⢐⣫⠴⠚⠉⠉⢉⣟⡵⠋⠞⠀⠀⠀⠀⠀⠀⢀⣠⣴⡫⡻⣣⡸⠙⠀⢻⢸⡗⢏⡾⠁⢘⠀⡀⣴⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠈⠉⠀⠀⠀⠀⠴⠚⠉⠀⠀⠀⢀⡴⠋⠋⠀⠀⠀⠀⠀⣀⣠⢴⠖⠋⣴⣿⣯⢞⡽⣣⠇⡰⠏⣸⡷⠋⠀⠀⢨⡴⣩⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⠔⠋⠀⠀⠀⣀⣤⠶⢝⡲⣿⠟⢁⣠⣾⠟⠁⡀⠞⠁⡡⢊⣅⣼⣿⠃⠀⠀⠀⠈⡇⡏⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣜⣁⠤⠴⠒⠋⠉⠁⣠⢔⣫⡾⠽⣾⡿⢋⡀⠀⠀⢉⡴⠊⠠⣨⣾⣎⢾⣝⠀⠀⢀⢀⣷⡇⠀⠀⠀⠀⢠⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠠⠞⠉⠠⣦⠀⣀⣤⠶⡟⣛⢩⡁⢀⣾⣏⣞⣾⣮⢴⣖⣋⠀⠴⠾⠼⠞⠁⣸⣉⣷⣴⣰⣸⣻⡇⠀⠀⡠⣤⣻⠁⣴⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠟⢰⠀⢀⣄⠧⢿⣞⡧⣿⠿⠿⠓⢝⠥⠭⠭⠭⠭⠭⠍⢔⡲⣶⣺⠫⠥⠤⢚⣛⡩⠧⢛⣒⢝⣫⡷⢆⣁⣄⠀⠀⠀⡀⣠⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⡠⢜⣒⡽⢺⣛⡽⠵⠛⠛⠉⠉⠋⠉⠀⠀⠀⠀⠀⠀⠀⠈⠀⠸⠇⠁⠉⠉⠉⠉⠚⠛⠵⢴⠹⣇⢍⣒⡢⠾⣢⢤⣀⠽⡿⣶⡤⣀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⢀⡠⢖⠫⢕⡺⠝⠚⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠈⠀⠀⠉⠉⠒⠭⣚⠽⣲⣤⣙⢦⡍⠒⠤⡀⠀
⠀⠀⠀⠀⢀⡤⣺⢕⣠⡿⠏⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠑⠢⣉⠚⢕⡦⣀⠀⠀⠀
⠀⠀⠀⠐⠁⠈⠀⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠑⠆⠉⠪⠳⠄⠀
                          Deep Focus
                     Made By Y0oshi | ig:@rde0
"""

# Global handle for scanner subprocess
scanner_process = None

# Rich console for colored output
from rich.console import Console
console = Console()

def print_help():
    """Display available CLI commands."""
    console.print("\n[bold cyan]Available Commands:[/bold cyan]")
    console.print("  [green]/scan[/green]      - Start Scanner (Background) and Open Visualizer")
    console.print("  [red]/stop[/red]      - Stop Scanner and Export Data")
    console.print("  [yellow]/settings[/yellow]  - Configure Target, Speed & Limits")
    console.print("  [bold white]/exit[/bold white]      - Quit Application")

def start_scan():
    """Start the background scanning process and launch the UI."""
    global scanner_process
    cfg = config.load_config()
    
    # Check if already running
    if scanner_process and scanner_process.poll() is None:
        console.print("[yellow][*] Scanner is already active.[/yellow]")
        return
        
    console.print("[green][*] Launching Scanner Engine...[/green]")
    
    # Construct scanner command
    cmd = [
        sys.executable, "execution/scanner.py",
        "--target", cfg['target_network'],
        "--rate", str(cfg['scan_speed']),
        "--max-load", str(cfg['max_load']),
        "--cool-down", str(cfg['cool_down_target']),
        "--loop"
    ]
    
    # Execute in background, discarding output to avoid UI conflicts
    # Output is piped to /dev/null
    try:
        devnull = open(os.devnull, 'w')
        scanner_process = subprocess.Popen(cmd, stdout=devnull, stderr=devnull)
        console.print(f"[green][+] Scanner started successfully (PID: {scanner_process.pid})[/green]")
        time.sleep(1) # Allow process to initialize
    except Exception as e:
        console.print(f"[bold red][!] Failed to start scanner: {e}[/bold red]")
        return

    # Attach Visualizer (This blocks the main thread until user exits UI)
    console.print("[*] Attaching Dashboard... (Active)")
    time.sleep(1)
    
    try:
        visualizer.run_dashboard()
    except KeyboardInterrupt:
        pass # Handle Ctrl+C gracefully
    except Exception as e:
        console.print(f"[bold red][!] Visualizer error: {e}[/bold red]")
        
    # When visualizer exits:
    console.print("\n[blue][i] Dashboard closed. Scanner is still running in background.[/blue]")
    console.print("    Type '[bold red]/stop[/bold red]' to halt, or '[green]/scan[/green]' to view again.")

def stop_scan():
    """Terminate the scanner process and offer export."""
    global scanner_process
    
    # 1. Terminate Process
    if scanner_process and scanner_process.poll() is None:
        console.print(f"[yellow][*] Stopping Scanner (PID: {scanner_process.pid})...[/yellow]")
        scanner_process.terminate()
        try:
            scanner_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            scanner_process.kill() # Force kill if stuck
        console.print("[green][+] Scanner Stopped.[/green]")
        scanner_process = None
    else:
        console.print("[dim][i] Scanner is not running.[/dim]")
        
    # 2. Offer Export
    perform_export()
    
    # 3. Cleanup Session Data
    console.print("\n[dim][*] Cleaning up session data...[/dim]")
    try:
        # Remove temporary SQLite database files
        for f in ["results.db", "results.db-wal", "results.db-shm"]:
            if os.path.exists(f): 
                os.remove(f)
        console.print("[green][+] Session cleared. Ready for next scan.[/green]")
    except Exception as e:
        console.print(f"[red][!] Cleanup warning: {e}[/red]")

def perform_export():
    """Export valid findings to a text file."""
    # Lazy import sqlite3 only when needed
    import sqlite3
    
    cfg = config.load_config()
    choice = input(f"Export results to '{cfg['export_path']}'? (Y/n): ").lower()
    if choice in ['n', 'no']:
        return
        
    export_dir = Path(cfg['export_path'])
    export_dir.mkdir(exist_ok=True)
    
    timestamp = int(time.time())
    filename = export_dir / f"deep_focus_export_{timestamp}.txt"
    
    console.print(f"[cyan][*] Exporting data to {filename}...[/cyan]")
    
    try:
        conn = sqlite3.connect("results.db")
        cursor = conn.cursor()
        
        # Select high-value targets (Open ports + Valid services)
        query = """
            SELECT ip, port, service_type, banner 
            FROM services 
            WHERE state='open' 
            AND (
                service_type IN ('ssh', 'vnc', 'rtsp', 'ftp') 
                OR 
                (service_type LIKE '%http%' AND banner NOT LIKE '%403 Forbidden%' AND banner NOT LIKE '%404 Not Found%')
            )
        """
        cursor.execute(query)
        
        count = 0
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"Deep Focus Scan Report - {time.ctime()}\n")
            f.write("="*60 + "\n\n")
            
            for row in cursor:
                ip, port, svc, banner = row
                f.write(f"Target:  {ip}:{port}\n")
                f.write(f"Service: {svc}\n")
                if banner:
                    # Clean up banner for readable log output
                    clean_banner = banner.replace('\n', ' ').replace('\r', '')[:120]
                    f.write(f"Details: {clean_banner}\n")
                f.write("-" * 30 + "\n")
                count += 1
                
        console.print(f"[bold green][+] Export Complete. Saved {count} records.[/bold green]")
        conn.close()
        
    except Exception as e:
        console.print(f"[bold red][!] Export Failed: {e}[/bold red]")

def configure_settings():
    """Interactive settings menu."""
    cfg = config.load_config()
    power = cfg.get('power_level', 50)
    speed = cfg.get('scan_speed', 500)
    
    print("\n--- Configuration ---")
    print(f"1. Target Network   [Current: {cfg['target_network']}]")
    print(f"2. Power Level      [Current: {power}%] (Controls Thermal Limit)")
    print(f"3. Scan Speed       [Current: {speed} threads]")
    print(f"4. Export Path      [Current: {cfg['export_path']}]")
    print("5. Back")
    
    choice = input("Select setting to change: ")
    
    if choice == '1':
        val = input("Enter new Target CIDR (e.g. 104.21.0.0/20): ").strip()
        if val: cfg['target_network'] = val
        
    elif choice == '2':
        val = input("Enter Power Level (10-100): ").strip()
        if val:
            try:
                p_int = int(val)
                p_int = max(10, min(100, p_int))
                
                # Dynamic Governor Formula
                # Base Load 1.5 + variable part based on user %
                ratio = p_int / 100.0
                max_load = 1.5 + (ratio * 8.5)
                
                cfg['power_level'] = p_int
                cfg['max_load'] = round(max_load, 2)
                cfg['cool_down_target'] = round(max_load * 0.6, 2)
                print(f"[+] Power set to {p_int}%. (Max Load: {cfg['max_load']})")
            except ValueError:
                print("Invalid input.")
                
    elif choice == '3':
        print("\n[!] CAUTION: Recommended range is 300-600 threads.")
        print("    Above 600 may cause router overload and heat issues.")
        val = input("Enter Scan Speed (100-1000): ").strip()
        if val:
            try:
                s_int = int(val)
                s_int = max(100, min(1000, s_int))
                cfg['scan_speed'] = s_int
                if s_int > 600:
                    print(f"[!] Speed set to {s_int}. Watch for overheating!")
                else:
                    print(f"[+] Speed set to {s_int} threads.")
            except ValueError:
                print("Invalid input.")
                
    elif choice == '4':
        val = input("Enter Export Path: ").strip()
        if val: cfg['export_path'] = val
    
    config.save_config(cfg)
    print("[+] Settings Saved.")

def main():
    """Main Application Loop."""
    # Resize terminal for optimal viewing (100 cols x 40 rows)
    sys.stdout.write("\033[8;40;100t")
    os.system('clear')  # Clean start
    
    # Print branded banner
    for line in BANNER.strip().split('\n'):
        console.print(line, style="bold red", justify="center")
    print_help()
    
    # Command Loop
    while True:
        try:
            cmd = input("\nDeep Focus> ").strip().lower()
            
            if not cmd:
                continue
                
            if cmd == "/scan":
                start_scan()
            elif cmd == "/stop":
                stop_scan()
            elif cmd == "/settings":
                configure_settings()
            elif cmd == "/help":
                print_help()
            elif cmd == "/exit":
                stop_scan()
                console.print("[bold white]Goodbye.[/bold white]")
                sys.exit(0)
            else:
                console.print("[dim]Unknown command. Type /help for list.[/dim]")
                
        except KeyboardInterrupt:
            print("\n") # Just new line, don't crash
            
if __name__ == "__main__":
    main()
