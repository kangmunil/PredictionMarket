import asyncio
import sys
import tty
import termios
import fcntl
import os
import logging
from collections import deque
from datetime import datetime
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich import box

# 1. 로깅 간섭 완전 차단 함수 (콘솔 출력만 제거)
def setup_logging(handler):
    try:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # FileHandler를 제외하고 순수 StreamHandler(콘솔)만 제거
        found_stream = False
        for h in root_logger.handlers[:]:
            # FileHandler는 StreamHandler의 자식이므로, 정확히 StreamHandler인 경우만 제거
            if type(h) == logging.StreamHandler:
                root_logger.removeHandler(h)
                found_stream = True

        root_logger.addHandler(handler)
        logging.info("📡 UI Logging System Attached")
        if not found_stream:
            logging.info("ℹ️  No raw StreamHandler found to remove")
        logging.info("🚀 Swarm Dashboard is initializing...")
    except Exception as e:
        # Fallback logging if something goes wrong during setup
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        with open(os.path.join(log_dir, "ui_error.log"), "a") as f:
            f.write(f"[{datetime.now()}] Error setting up logging: {str(e)}\n")

class LogQueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            # 특정 로그 필터링
            logger_name = record.name.lower()

            # httpx 로그는 완전히 제외 (너무 많음)
            if "httpx" in logger_name:
                return

            # 너무 상세한 로그 제외
            if record.levelno < logging.INFO:
                return

            timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            msg = record.getMessage()
            level = record.levelname

            # 로그 메시지 단축 (너무 긴 메시지는 잘라냄)
            if len(msg) > 100:
                msg = msg[:97] + "..."

            # 로그 레벨별 색상 설정
            color = "white"
            if level == "ERROR": color = "red"
            elif level == "WARNING": color = "yellow"
            elif level == "INFO": color = "cyan"
            elif level == "DEBUG": color = "dim"

            self.log_queue.append((timestamp, level, color, msg))
        except Exception as e:
            # 로깅 자체의 에러는 무시하되 필요시 파일에 기록
            pass

class SwarmDashboard:
    def __init__(self, swarm_system):
        self.system = swarm_system
        self.log_queue = deque(maxlen=30)  # 큐 크기 확장 (10 → 30)
        self.console = Console()
        self.running = True

    def get_header(self) -> Panel:
        curr_time = datetime.now().strftime("%H:%M:%S")
        is_running = getattr(self.system, "running", False)
        is_trading = getattr(self.system, "trading_enabled", False)
        
        if not is_running: status_txt, status_col = "○ STARTING", "bold yellow"
        elif is_trading: status_txt, status_col = "● RUNNING", "bold green"
        else: status_txt, status_col = "○ PAUSED", "bold red"
        
        history = getattr(self.system, "completed_trades", [])
        total_pnl = sum(float(t.get('pnl', 0) or 0) for t in history)
        pnl_col = "green" if total_pnl >= 0 else "red"
        
        header_text = Text.assemble(
            (f" {status_txt} ", status_col),
            (" | ", "dim"),
            ("HIVE SWARM ", "bold cyan"),
            (" | ", "dim"),
            ("PNL: ", "bold"), (f"${total_pnl:+.2f} ", f"bold {pnl_col}"),
            (" | ", "dim"),
            (curr_time, "white")
        )
        return Panel(header_text, style="white on blue", box=box.SQUARE, padding=(0, 1))

    def get_main_content(self) -> Table:
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)

        # WALLET 섹션 - BudgetManager 접근 개선
        bm = self.system.budget_manager if hasattr(self.system, 'budget_manager') else None
        if bm and hasattr(bm, 'total_capital'):
            try:
                cap = float(bm.total_capital)
                res = float(bm.reserve_balance)
                act = cap - res

                # 사용 중인 자금 계산
                allocated = sum(float(v) for v in bm.allocated.values()) if hasattr(bm, 'allocated') else 0

                wallet_text = Text.assemble(
                    ("CAP: ", "dim"), (f"${cap:,.0f} ", "bold cyan"),
                    ("ACT: ", "dim"), (f"${act:,.0f} ", "bold green"),
                    ("RES: ", "dim"), (f"${res:,.0f}\n", "bold yellow"),
                    ("USED: ", "dim"), (f"${allocated:,.0f}", "bold magenta")
                )
            except Exception as e:
                wallet_text = Text(f"Error: {str(e)[:30]}...", style="red")
        else:
            wallet_text = Text("⏳ Initializing BudgetManager...", style="dim italic")

        # SIGNALS 섹션 - SignalBus 접근 개선
        bus = self.system.bus if hasattr(self.system, 'bus') else None
        sig_list = []

        if bus and hasattr(bus, "_signals"):
            signals_dict = bus._signals

            if signals_dict and len(signals_dict) > 0:
                # 최근 업데이트 순으로 최대 2개 시그널 추출
                try:
                    sorted_sigs = sorted(
                        signals_dict.values(),
                        key=lambda x: x.last_updated if hasattr(x, 'last_updated') and isinstance(x.last_updated, datetime) else datetime.min,
                        reverse=True
                    )

                    for s in sorted_sigs[:2]:
                        score = getattr(s, 'sentiment_score', 0)
                        whale = getattr(s, 'whale_activity_score', 0)
                        color = "green" if score > 0.2 else "red" if score < -0.2 else "yellow"

                        sig_text = Text.assemble(
                            (f"{s.token_id[:12]}", "white"),
                            (f" Sent:{score:+.2f}", color),
                            (f" Whl:{whale:.1f}", "magenta")
                        )
                        sig_list.append(sig_text)
                except Exception as e:
                    sig_list = [Text(f"Error: {str(e)[:20]}", style="red")]

        if not sig_list:
            # SignalBus가 초기화되었지만 비어있는 경우
            if bus:
                sig_content = Text("🔍 Scanning markets...", style="dim italic")
            else:
                sig_content = Text("⏳ Initializing SignalBus...", style="dim italic")
        else:
            sig_content = Text("\n").join(sig_list)

        grid.add_row(
            Panel(wallet_text, title="[b]WALLET[/]", border_style="green", box=box.SQUARE),
            Panel(sig_content, title="[b]SIGNALS[/]", border_style="magenta", box=box.SQUARE)
        )
        return grid

    def get_performance_table(self) -> Table:
        table = Table(title="[b]LIVE PERFORMANCE[/]", expand=True, box=box.SIMPLE, header_style="dim")
        table.add_column("Asset", no_wrap=True)
        table.add_column("Side", justify="center")
        table.add_column("PnL", justify="right")

        history = getattr(self.system, "completed_trades", [])
        if not history:
            table.add_row("No trades", "-", "$0.00")
        else:
            for trade in list(history)[-3:]:
                pnl = float(trade.get('pnl', 0) or 0)
                pnl_color = "green" if pnl > 0 else "red"
                side = str(trade.get('side', 'YES'))
                side_col = "cyan" if "YES" in side.upper() else "yellow"
                table.add_row(str(trade.get('asset', 'Unknown'))[:12], Text(side[:3], style=side_col), Text(f"${pnl:+.2f}", style=pnl_color))
        return table

    def get_logs_panel(self) -> Panel:
        log_render = Text()
        # 최근 로그들 표시 (최신 10개만)
        if not self.log_queue:
            log_render.append("⏳ Waiting for logs...", style="dim italic")
        else:
            # 최신 로그 10개만 표시 (큐 크기는 30이지만 UI에는 10개만)
            recent_logs = list(self.log_queue)[-10:]
            for ts, lvl, col, msg in recent_logs:
                log_render.append(f"[{ts}] ", style="dim")
                log_render.append(f"{lvl:<5} ", style=col)
                # 메시지는 이미 emit()에서 100자로 제한됨
                log_render.append(f"{msg}\n", style="white")
        return Panel(log_render, title=f"[b]LOGS[/] ({len(self.log_queue)}/30)", box=box.SQUARE)

    def generate_dashboard(self):
        return Group(
            self.get_header(),
            self.get_main_content(),
            self.get_performance_table(),
            self.get_logs_panel()
        )

    async def _input_handler(self):
        fd = sys.stdin.fileno()
        try:
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            orig_fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, orig_fl | os.O_NONBLOCK)

            while self.running:
                try:
                    ch = sys.stdin.read(1).lower()
                    if ch == 'q' or ord(ch) == 3:
                        self.running = False
                        break
                    elif ch == 'p': await self.system.handle_stop("")
                    elif ch == 'r': await self.system.handle_resume("")
                except (EOFError, IOError):
                    pass
                await asyncio.sleep(0.1)
            
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            fcntl.fcntl(fd, fcntl.F_SETFL, orig_fl)
        except Exception:
            pass

    async def run(self, dry_run: bool = False):
        # 1. 로깅 설정 초기화 (stderr 출력 완전 차단)
        handler = LogQueueHandler(self.log_queue)
        setup_logging(handler)

        # 2. 시스템 초기화를 먼저 완료
        logging.info("⏳ Initializing system before UI launch...")
        await self.system.setup(dry_run=dry_run)
        logging.info("✅ System initialized, launching dashboard...")

        # 3. 봇 실행을 별도 태스크로 시작 (setup 없이)
        system_task = asyncio.create_task(self._run_system_agents())
        input_task = asyncio.create_task(self._input_handler())

        try:
            with Live(
                self.generate_dashboard(),
                refresh_per_second=4,
                screen=True,
                console=self.console,
                transient=True
            ) as live:
                while self.running and not system_task.done():
                    live.update(self.generate_dashboard())
                    await asyncio.sleep(0.25)

                # 만약 시스템 태스크가 예외로 종료되었다면 로그에 남김
                if system_task.done() and system_task.exception():
                    exc = system_task.exception()
                    logging.error(f"❌ System crashed: {exc}")
                    await asyncio.sleep(2) # 로그 볼 시간 확보
        finally:
            self.running = False
            input_task.cancel()
            if not system_task.done(): system_task.cancel()
            await self.system.shutdown()
            os.system('reset')

    async def _run_system_agents(self):
        """시스템 에이전트들을 실행 (setup 제외)"""
        keywords = self.system.config.MONITOR_KEYWORDS

        logging.info(f"🚀 Starting {len(self.system.tasks)} agent tasks...")

        # 에이전트 태스크 생성
        self.system.tasks = [
            asyncio.create_task(self.system.news_agent.run(keywords=keywords, check_interval=20), name="NewsScalper"),
            asyncio.create_task(self.system.stat_arb_agent.run(), name="StatArb"),
            asyncio.create_task(self.system.mimic_agent.run(), name="EliteMimic"),
            asyncio.create_task(self.system.arb_agent.run(), name="PureArb"),
            asyncio.create_task(self.system._monitor_swarm_health(), name="HealthMonitor"),
            asyncio.create_task(self.system._daily_report_task(), name="DailyReport")
        ]

        try:
            await asyncio.gather(*self.system.tasks)
        except asyncio.CancelledError:
            logging.info("🐝 Agent tasks cancelled")