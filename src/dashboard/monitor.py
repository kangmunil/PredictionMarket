from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich import box
import json
import time
import os

STATUS_FILE = "data/dashboard_state.json"

def loaded_state():
    if not os.path.exists(STATUS_FILE):
        return {}
    try:
        with open(STATUS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def make_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=4),
        Layout(name="main", ratio=2),
        Layout(name="footer", ratio=1)
    )
    layout["main"].split_row(
        Layout(name="positions", ratio=2),
        Layout(name="signals", ratio=1),
        Layout(name="brain", ratio=1)
    )
    return layout

def generate_header(state):
    bal = state.get("balance_usdc", 0.0)
    pnl = state.get("total_pnl", 0.0)
    updated = time.strftime('%H:%M:%S', time.localtime(state.get("last_updated", 0)))
    
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="center")
    table.add_column(justify="right")
    
    pnl_color = "green" if pnl >= 0 else "red"
    
    table.add_row(
        f"💰 Balance: [bold cyan]${bal:,.2f}[/]",
        f"PredictionMarket Swarm [dim](Updated: {updated})[/]",
        f"📈 Total PnL: [bold {pnl_color}]${pnl:+,.2f}[/]"
    )
    return Panel(table, style="white on blue", box=box.ROUNDED)

def generate_positions(state):
    table = Table(expand=True, box=box.SIMPLE_HEAD)
    table.add_column("Symbol")
    table.add_column("Size")
    table.add_column("Entry")
    table.add_column("Current")
    table.add_column("PnL")
    
    positions = state.get("active_positions", [])
    if not positions:
        table.add_row("[dim]No active positions[/]", "", "", "", "")
    else:
        for p in positions:
            pnl = p.get('pnl', 0)
            color = "green" if pnl >= 0 else "red"
            table.add_row(
                p.get('symbol', 'Unknown')[:15],
                f"${p.get('size', 0):.2f}",
                f"${p.get('entry', 0):.2f}",
                f"${p.get('current', 0):.2f}",
                f"[{color}]${pnl:+.2f}[/]"
            )
            
    return Panel(table, title="Active Positions", border_style="yellow")

def generate_signals(state):
    table = Table(expand=True, box=box.SIMPLE)
    table.add_column("Token")
    table.add_column("Score")
    
    signals = state.get("signals", {})
    sorted_sigs = sorted(signals.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
    
    if not sorted_sigs:
        table.add_row("[dim]No signals[/]", "")
    else:
        for k, v in sorted_sigs:
            color = "green" if v > 0 else "red"
            table.add_row(k[:10], f"[{color}]{v:+.2f}[/]")
            
    return Panel(table, title="Hive Mind Signals", border_style="magenta")

def generate_logs(state):
    logs = state.get("recent_logs", [])
    log_text = ""
    for log in logs[-8:]: # Show last 8 lines
        c = "white"
        if log['level'] == "ERROR": c = "red"
        elif log['level'] == "WARNING": c = "yellow"
        log_text += f"[{c}]{log['time']} {log['msg']}[/]\n"
        
    return Panel(log_text.strip(), title="System Logs", border_style="white")

def generate_brain_panel(state):
    table = Table(expand=True, box=box.SIMPLE)
    table.add_column("Category")
    table.add_column("Win Rate")
    table.add_column("Boost")
    
    metrics = state.get("brain", [])
    if not metrics:
        table.add_row("[dim]Brain Empty[/]", "", "")
    else:
        for m in metrics[:5]: # Top 5 categories
            mult = m['multiplier']
            color = "green" if mult > 1.0 else "red" if mult < 1.0 else "white"
            table.add_row(
                m['tag'],
                f"{m['win_rate']:.1f}%",
                f"[{color}]x{mult:.2f}[/]"
            )
            
    return Panel(table, title="🧠 Brain (Specialist)", border_style="cyan")

def run_monitor():
    console = Console()
    layout = make_layout()
    
    with Live(layout, refresh_per_second=4, screen=True) as live:
        while True:
            state = loaded_state()
            layout["header"].update(generate_header(state))
            layout["positions"].update(generate_positions(state))
            layout["signals"].update(generate_signals(state))
            layout["brain"].update(generate_brain_panel(state))
            layout["footer"].update(generate_logs(state))
            time.sleep(0.25)

if __name__ == "__main__":
    run_monitor()
