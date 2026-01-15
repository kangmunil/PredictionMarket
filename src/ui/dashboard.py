import time
import json
import os
from datetime import datetime
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.console import Console
from rich import box

LOG_FILE = "logs/latest_swarm.log"
STATE_FILE = "dashboard_state.json"

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def get_log_tail(n=20):
    try:
        if not os.path.exists(LOG_FILE):
             return ["Waiting for logs..."]
        # Simple reliable tail (inefficient for huge files but fine for now)
        # For production, seeking to end is better.
        with open(LOG_FILE, "r") as f:
             # Fast read last N lines
             f.seek(0, os.SEEK_END)
             size = f.tell()
             block = 1024
             lines = []
             
             # Read backwards roughly
             params_to_read = min(size, block * 10) # 10KB
             f.seek(max(size - params_to_read, 0))
             
             data = f.read()
             lines = data.splitlines()
             return lines[-n:]
    except Exception as e:
        return [f"Error reading logs: {e}"]

def make_layout():
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3)
    )
    layout["main"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=2),
    )
    layout["left"].split(
        Layout(name="pnl", size=8),
        Layout(name="positions"),
    )
    return layout

def generate_header(state):
    mode = state.get("mode", "UNKNOWN")
    status = state.get("status", "UNKNOWN")
    ts = state.get("timestamp", "")[11:19] # Time only
    
    style = "bold green" if status == "RUNNING" else "bold red"
    title_text = Text(f"🤖 HIVE MIND SWARM | {status} | {mode} | Last Update: {ts}", justify="center", style=style)
    return Panel(title_text, box=box.DOUBLE)

def generate_pnl_panel(state):
    pnl = state.get("pnl", {})
    total = float(pnl.get("total_net", 0.0))
    real = float(pnl.get("realized", 0.0))
    unreal = float(pnl.get("unrealized", 0.0))
    win_rate = float(pnl.get("win_rate", 0.0))
    
    color = "green" if total >= 0 else "red"
    
    text = Text()
    text.append(f"💰 Total PnL: ", style="bold")
    text.append(f"${total:+.2f}\n", style=f"bold {color}")
    text.append(f"💵 Realized:  ${real:+.2f}\n")
    text.append(f"📉 Floating:  ${unreal:+.2f}\n")
    text.append(f"🏆 Win Rate:  {win_rate:.1f}%")
    
    return Panel(text, title="Performance", border_style=color)

def generate_positions_table(state):
    table = Table(box=box.SIMPLE_HEAD, expand=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Side")
    table.add_column("Size", justify="right")
    table.add_column("PnL", justify="right")
    
    positions = state.get("positions", [])
    
    if not positions:
        return Panel(Text("No active positions", style="dim italic"), title="Active Positions")

    for p in positions:
        pnl = float(p.get('pnl', 0))
        color = "green" if pnl >= 0 else "red"
        side_color = "green" if p['side'] == "BUY" else "red"
        
        table.add_row(
            p['symbol'],
            Text(p['side'], style=side_color),
            f"${p['size']:.1f}",
            Text(f"${pnl:+.2f}", style=color)
        )
        
    return Panel(table, title=f"Positions ({len(positions)})")

def generate_log_panel():
    logs = get_log_tail(25)
    text = Text()
    for line in logs:
        line_clean = line
        if "INFO]" in line:
            line_clean = line.split("INFO]")[-1].strip()
            style = "white"
            if "BUY" in line or "SELL" in line: style = "bold green"
        elif "WARNING]" in line:
             line_clean = line.split("WARNING]")[-1].strip()
             style = "yellow"
        elif "ERROR]" in line:
             line_clean = line.split("ERROR]")[-1].strip()
             style = "bold red"
        else:
             style = "dim white"
             
        text.append(f"{line_clean}\n", style=style)
            
    return Panel(text, title="Live Logs", box=box.ROUNDED)

def run_dashboard():
    console = Console()
    layout = make_layout()
    
    if not os.path.exists(STATE_FILE):
        print("Waiting for bot to generate state...")
        time.sleep(2)
    
    with Live(layout, refresh_per_second=2, screen=True):
        while True:
            state = load_state()
            
            layout["header"].update(generate_header(state))
            layout["pnl"].update(generate_pnl_panel(state))
            layout["positions"].update(generate_positions_table(state))
            layout["right"].update(generate_log_panel())
            
            # Signals
            sigs = state.get("active_signals", 0)
            layout["footer"].update(Panel(f"📡 Active Signals: {sigs} | [bold]Ctrl+C[/bold] to exit dashboard", style="blue"))
            
            time.sleep(0.5)

if __name__ == "__main__":
    try:
        run_dashboard()
    except KeyboardInterrupt:
        pass