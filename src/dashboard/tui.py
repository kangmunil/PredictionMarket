
import json
import time
import os
from datetime import datetime
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.console import Console
from rich import box
from rich.align import Align

# Configuration
STATE_FILE = "data/dashboard_state.json"
REFRESH_RATE = 1  # seconds

console = Console()

class SwarmDashboard:
    def __init__(self):
        self.layout = Layout()
        self.layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )
        self.layout["main"].split_row(
            Layout(name="positions", ratio=2),
            Layout(name="sidebar", ratio=1),
        )
        self.layout["sidebar"].split(
            Layout(name="signals", size=10),
            Layout(name="logs", ratio=1),
        )

    def load_state(self):
        try:
            if not os.path.exists(STATE_FILE):
                return {}
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def make_header(self, state):
        balance = state.get("balance_usdc", 0.0)
        pnl = state.get("total_pnl", 0.0)
        
        # Color based on PnL
        pnl_color = "green" if pnl >= 0 else "red"
        
        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right", ratio=1)
        
        grid.add_row(
            f"🚀 [bold blue]Hive Mind Swarm Intelligence[/bold blue]",
            f"💰 Balance: [bold green]${balance:,.2f}[/bold green]",
            f"📉 PnL: [bold {pnl_color}]${pnl:+.2f}[/bold {pnl_color}]"
        )
        return Panel(grid, style="white on black")

    def make_positions_table(self, state):
        table = Table(title="[bold]Active Positions[/bold]", expand=True, box=box.ROUNDED)
        table.add_column("Symbol", ratio=3, style="cyan")
        table.add_column("Size", justify="right", style="magenta")
        table.add_column("Entry", justify="right", style="green")
        table.add_column("Current", justify="right", style="yellow")
        table.add_column("PnL ($)", justify="right", style="bold")

        positions = state.get("active_positions", [])
        
        # Sort by PnL Descending
        positions.sort(key=lambda x: x.get("pnl", 0), reverse=True)

        for pos in positions[:15]: # Show top 15
            symbol = pos.get("symbol", "Unknown")[:30]
            size = pos.get("size", 0)
            entry = pos.get("entry", 0)
            current = pos.get("current", 0)
            pnl = pos.get("pnl", 0)
            
            pnl_style = "green" if pnl >= 0 else "red"
            
            table.add_row(
                symbol,
                f"{size:.2f}",
                f"${entry:.3f}",
                f"${current:.3f}",
                f"[{pnl_style}]${pnl:+.2f}[/{pnl_style}]"
            )
            
        return table

    def make_signals_panel(self, state):
        # Placeholder for signals, check if they exist in state 
        # (Assuming 'signals' key might be added later or we parse logs)
        signals_text = "📡 Strategy Signals:\n"
        
        # If we had dedicated signals key:
        # signals = state.get("signals", {})
        # for asset, score in signals.items():
        #     signals_text += f"- {asset}: {score:.2f}\n"
            
        # For now, just show active bots count or something
        positions = state.get("active_positions", [])
        signals_text += f"Active Bots: [bold]{len(positions)}[/bold]\n"
        signals_text += f"Mode: [bold green]{state.get('mode', 'LIVE')}[/bold green]"
        
        return Panel(signals_text, title="Market Intelligence", border_style="blue")

    def make_logs_panel(self, state):
        logs = state.get("recent_logs", [])
        log_text = Text()
        
        for log in logs[-15:]: # Last 15 logs
            time_str = log.get("time", "")
            msg = log.get("msg", "")
            level = log.get("level", "INFO")
            
            color = "white"
            if level == "WARNING": color = "yellow"
            elif level == "ERROR": color = "red"
            elif level == "CRITICAL": color = "bold red"
            
            log_text.append(f"[{time_str}] ", style="dim")
            log_text.append(f"{msg}\n", style=color)
            
        return Panel(log_text, title="Mission Log", border_style="white")

    def make_footer(self):
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return Align.center(f"[dim]Last Updated: {t} | Press Ctrl+C to Exit[/dim]")

    def run(self):
        with Live(self.layout, refresh_per_second=REFRESH_RATE, screen=True) as live:
            while True:
                state = self.load_state()
                
                self.layout["header"].update(self.make_header(state))
                self.layout["positions"].update(self.make_positions_table(state))
                self.layout["signals"].update(self.make_signals_panel(state))
                self.layout["logs"].update(self.make_logs_panel(state))
                self.layout["footer"].update(self.make_footer())
                
                time.sleep(REFRESH_RATE)

if __name__ == "__main__":
    try:
        dashboard = SwarmDashboard()
        dashboard.run()
    except KeyboardInterrupt:
        console.print("[bold yellow]Dashboard Closed.[/bold yellow]")
