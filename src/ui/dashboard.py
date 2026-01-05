import asyncio
import sys
import tty
import termios
from collections import deque
from datetime import datetime
import logging
from typing import List, Dict
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.console import Console
from rich.text import Text
from rich.table import Table
from rich import box

class LogQueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
        
    def emit(self, record):
        try:
            timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            msg = record.getMessage()
            level = record.levelname
            color = "white"
            if level == "ERROR": color = "red"
            elif level == "WARNING": color = "yellow"
            elif level == "INFO": color = "cyan"
            
            self.log_queue.append(f"[{timestamp}] [{color}]{level:<7}[/] {msg}")
        except Exception:
            self.handleError(record)

class SwarmDashboard:
    def __init__(self, swarm_system):
        self.system = swarm_system
        self.log_queue = deque(maxlen=15)
        self.layout = Layout()
        self.update_count = 0
        self.running = True
        
        # 레이아웃 구성
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=12)
        )
        self.layout["body"].split_row(
            Layout(name="stats", ratio=1),
            Layout(name="signals", ratio=1)
        )
        self.layout["footer"].split_row(
            Layout(name="performance", ratio=2),
            Layout(name="logs", ratio=1)
        )

    def get_header(self) -> Panel:
        self.update_count += 1
        curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        is_trading = getattr(self.system, "trading_enabled", True)
        status_text = "[bold green]LIVE TRADING[/]" if is_trading else "[bold red]🛑 PAUSED (PANIC)[/]"
        
        content = f"[bold cyan]🐝 Hive Mind Swarm Dashboard[/] | Status: {status_text} | [white]{curr_time}[/]\n"
        content += "[dim]Hotkeys: [b]p[/]: Panic Stop | [b]r[/]: Resume | [b]q[/]: Safe Quit[/]"
        return Panel(Text.from_markup(content, justify="center"), style="white on blue", box=box.DOUBLE)

    def get_stats_panel(self) -> Panel:
        bm = getattr(self.system, "budget_manager", None)
        text = Text()
        if not bm:
            text.append("⏳ Initializing...", style="dim")
        else:
            total = float(bm.total_capital)
            text.append(f"Total Capital: [bold green]${total:,.2f}[/]\n")
            text.append(f"Reserve:       [dim]${float(bm.reserve_balance):,.2f}[/]\n")
            text.append("-" * 30 + "\n")
            for strat, bal in bm.balances.items():
                text.append(f"• {strat.upper():<10}: [cyan]${float(bal):>8.2f}[/]\n")
        return Panel(text, title="💰 Budget Status", border_style="green")

    def get_signals_panel(self) -> Panel:
        bus = getattr(self.system, "bus", None)
        text = Text()
        if not bus or not bus._signals:
            text.append("📡 Scanning markets...", style="dim")
        else:
            sorted_sigs = sorted(bus._signals.values(), key=lambda x: getattr(x, 'last_updated', 0), reverse=True)[:6]
            for sig in sorted_sigs:
                score = getattr(sig, 'sentiment_score', 0)
                color = "green" if score > 0.5 else "red" if score < -0.5 else "yellow"
                text.append(f"⚡ {sig.token_id[:12]:<12} | [bold {color}]{score:+.2f}[/]\n")
        return Panel(text, title="🧠 Hive Intelligence", border_style="magenta")

    def get_performance_table(self) -> Table:
        table = Table(title="📊 Live Trade Performance", expand=True, box=box.SIMPLE_HEAD)
        table.add_column("Time", style="dim")
        table.add_column("Asset", style="bold")
        table.add_column("Side", justify="center")
        table.add_column("Size", justify="right")
        table.add_column("Profit", justify="right")
        table.add_column("Status", justify="center")

        history = getattr(self.system, "completed_trades", [])
        for trade in list(history)[-8:]:
            pnl_color = "green" if trade.get('pnl', 0) > 0 else "red"
            table.add_row(
                trade.get('time', '--:--'),
                trade.get('asset', 'Unknown')[:10],
                f"[{'cyan' if trade.get('side')=='YES' else 'yellow'}]{trade.get('side')}[/]",
                f"${trade.get('size', 0):.1f}",
                f"[{pnl_color}]${trade.get('pnl', 0):+.2f}[/]",
                "[bold green]FILLED[/]"
            )
        return table

    def get_logs_panel(self) -> Panel:
        text = Text.from_markup("\n".join(list(self.log_queue)))
        return Panel(text, title="📜 System Activity", border_style="white")

    def refresh(self):
        try:
            self.layout["header"].update(self.get_header())
            self.layout["stats"].update(self.get_stats_panel())
            self.layout["signals"].update(self.get_signals_panel())
            self.layout["performance"].update(self.get_performance_table())
            self.layout["logs"].update(self.get_logs_panel())
        except Exception: pass

    async def _input_handler(self):
        """Listen for keyboard input without blocking UI (Unix only)"""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            while self.running:
                # Non-blocking check if input is available
                if sys.stdin in (await asyncio.get_event_loop().run_in_executor(None, lambda: [sys.stdin] if sys.stdin.readable() else [])):
                    ch = sys.stdin.read(1).lower()
                    if ch == 'q':
                        self.running = False
                        await self.system.shutdown()
                        break
                    elif ch == 'p':
                        await self.system.handle_stop("")
                    elif ch == 'r':
                        await self.system.handle_resume("")
                await asyncio.sleep(0.1)
        except Exception: pass
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    async def run(self):
        handler = LogQueueHandler(self.log_queue)
        logging.getLogger().addHandler(handler)
        
        system_task = asyncio.create_task(self.system.run())
        input_task = asyncio.create_task(self._input_handler())
        
        with Live(self.layout, refresh_per_second=4, screen=True) as live:
            while self.running and not system_task.done():
                self.refresh()
                await asyncio.sleep(0.25)
        
        self.running = False
        input_task.cancel()
        if not system_task.done():
            system_task.cancel()