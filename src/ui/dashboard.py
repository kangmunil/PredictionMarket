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

STATE_FILE = "dashboard_state.json"

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


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
    status = "RUNNING" if state.get("last_updated", 0) > time.time() - 10 else "STALLED"
    ts = datetime.fromtimestamp(state.get("last_updated", 0)).strftime("%H:%M:%S")
    
    style = "bold green" if status == "RUNNING" else "bold red"
    title_text = Text(f"🤖 HIVE MIND SWARM | {status} | {mode} | Last Update: {ts}", justify="center", style=style)
    return Panel(title_text, box=box.DOUBLE)

def generate_sparkline(data, width=30):
    if not data: return ""
    chars = " ▂▃▄▅▆▇█"
    min_val, max_val = min(data), max(data)
    rng = max_val - min_val
    if rng == 0: return "█" * min(len(data), width)
    
    points = data[-width:]
    line = ""
    for v in points:
        idx = int(((v - min_val) / rng) * (len(chars) - 1))
        line += chars[idx]
    return line

def generate_pnl_panel(state):
    # Match StatusReporter flat structure
    total = float(state.get("total_pnl", 0.0))
    balance = float(state.get("balance_usdc", 0.0))
    history = state.get("pnl_history", [])
    
    # Calculate stats from history/logs if not explicitly in state
    # (Simplified for now)
    
    color = "green" if total >= 0 else "red"
    
    text = Text()
    text.append(f"💰 Balance:   ${balance:.2f}\n", style="bold white")
    text.append(f"📊 Total PnL: ", style="bold")
    text.append(f"${total:+.2f}\n", style=f"bold {color}")
    
    if history:
        chart = generate_sparkline(history, width=35)
        text.append(f"\n📈 Trend (1m):\n{chart}", style=color)
    else:
        text.append("\n(No PnL history yet)", style="dim")
    
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
        
    return Panel(table, title=f"Active Positions ({len(positions)})")

def generate_log_panel(state):
    logs = state.get("recent_logs", [])
    text = Text()
    for entry in logs:
        time_str = entry.get("time", "")
        msg = entry.get("msg", "")
        level = entry.get("level", "INFO")
        
        style = "white"
        if level == "INFO":
            if "BUY" in msg or "SELL" in msg: style = "bold green"
        elif level == "WARNING":
            style = "yellow"
        elif level == "ERROR":
            style = "bold red"
        else:
            style = "dim white"
             
        text.append(f"[{time_str}] {msg}\n", style=style)
            
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
            layout["right"].update(generate_log_panel(state))
            
            # Signals
            sigs = state.get("active_signals", 0)
            layout["footer"].update(Panel(f"📡 Active Signals: {sigs} | [bold]Ctrl+C[/bold] to exit dashboard", style="blue"))
            
            time.sleep(0.5)

if __name__ == "__main__":
    try:
        run_dashboard()
    except KeyboardInterrupt:
        pass