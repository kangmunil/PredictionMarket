# 📊 성능 모니터링 대시보드 개선사항

**작성일**: 2026-01-05
**목적**: 기존 대시보드 분석 및 개선 제안

---

## 현재 구현 상태

### 1. **Swarm Dashboard** (src/ui/dashboard.py)
- **기술**: Rich 라이브러리 기반 TUI (Terminal UI)
- **업데이트**: 4Hz (0.25초마다)
- **기능**:
  - 💰 자본 할당 현황
  - 🤖 에이전트 상태
  - 🧠 Hive Mind 신호
  - 📜 시스템 로그 (최근 25개)

**강점**:
- ✅ 실시간 업데이트
- ✅ 로그 핸들러 통합
- ✅ 에러 처리 (UI 크래시 방지)
- ✅ 명확한 레이아웃

**약점**:
- ⚠️ 거래 성과 미표시
- ⚠️ API 레이트 리밋 미표시
- ⚠️ 봇별 PnL 미분리
- ⚠️ 차트/그래프 없음

### 2. **Health Monitor** (src/core/health_monitor.py)
- **기술**: Redis 기반 메트릭 수집 + Slack/Discord 알림
- **주기**: 30초마다 체크
- **기능**:
  - 봇 상태 (active/crashed)
  - 예산 사용률
  - API 요청/에러
  - 거래 성과 (승률, PnL)
  - 알림 (Slack, Discord)

**강점**:
- ✅ 포괄적 메트릭
- ✅ 다채널 알림
- ✅ 헬스 체크 로직
- ✅ JSON 직렬화

**약점**:
- ⚠️ 시각화 없음 (메트릭만 수집)
- ⚠️ 히스토리 추적 부족
- ⚠️ 봇별 세분화 부족

---

## 🎯 개선 제안

### Priority 1: Swarm Dashboard 기능 확장 (2-3시간)

#### 1.1 거래 성과 패널 추가
```python
def get_trading_text(self) -> Panel:
    """
    📈 Trading Performance
    ├─ Trades Today: 23
    ├─ Win Rate: 68.2% (15W / 7L / 1P)
    ├─ Today PnL: +$127.50 ▲
    └─ Avg Profit: $8.50 per trade
    """
    text = Text()
    bm = self.system.budget_manager

    trades = bm.trades_today if bm else 0
    wins = bm.wins_today if bm else 0
    losses = bm.losses_today if bm else 0
    win_rate = (wins / trades * 100) if trades > 0 else 0
    pnl = float(bm.pnl_today) if bm else 0.0

    text.append(f"Trades: {trades}\n", style="white")
    text.append(f"Win Rate: {win_rate:.1f}% ({wins}W / {losses}L)\n",
                style="green" if win_rate > 60 else "yellow")

    pnl_color = "green" if pnl > 0 else "red" if pnl < 0 else "white"
    pnl_arrow = "▲" if pnl > 0 else "▼" if pnl < 0 else "─"
    text.append(f"PnL: ${pnl:+.2f} {pnl_arrow}\n", style=pnl_color)

    return Panel(text, title="📈 Trading Performance", border_style="cyan")
```

**위치**: `self.layout["right"]`의 하단에 추가

#### 1.2 API 레이트 리밋 인디케이터
```python
def get_api_status(self) -> Panel:
    """
    🌐 API Health
    ├─ Requests: 47/100 ████████░░ (47%)
    ├─ Errors: 2 ⚠️
    └─ Rate Limits: 0 ✅
    """
    text = Text()
    rl = getattr(self.system, "rate_limiter", None)

    if rl:
        requests = rl.requests_last_minute
        limit = rl.max_requests_per_minute
        pct = (requests / limit * 100) if limit > 0 else 0

        # Progress bar
        filled = int(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)

        text.append(f"Requests: {requests}/{limit} {bar} ({pct:.0f}%)\n")

        errors = rl.errors_last_minute
        error_style = "red" if errors > 5 else "yellow" if errors > 0 else "green"
        text.append(f"Errors: {errors}", style=error_style)

        if errors > 0:
            text.append(" ⚠️\n")
        else:
            text.append(" ✅\n")

    return Panel(text, title="🌐 API Health", border_style="blue")
```

#### 1.3 봇별 PnL 분리 표시
```python
def get_bot_pnl(self) -> Panel:
    """
    💵 Bot Performance
    ├─ News Scalper: +$45.20 ▲
    ├─ Pure Arb:     +$82.30 ▲▲
    ├─ StatArb:      -$12.50 ▼
    └─ EliteMimic:   +$15.00 ▲
    """
    text = Text()
    bots = [
        ("News Scalper", "news_scalper"),
        ("Pure Arb", "pure_arb"),
        ("StatArb", "stat_arb"),
        ("EliteMimic", "elite_mimic")
    ]

    for name, key in bots:
        pnl = self.system.get_bot_pnl(key) if hasattr(self.system, "get_bot_pnl") else 0

        if pnl > 20:
            arrow = "▲▲"
            style = "bold green"
        elif pnl > 0:
            arrow = "▲"
            style = "green"
        elif pnl < -20:
            arrow = "▼▼"
            style = "bold red"
        elif pnl < 0:
            arrow = "▼"
            style = "red"
        else:
            arrow = "─"
            style = "white"

        text.append(f"{name:<15}: ${pnl:+7.2f} {arrow}\n", style=style)

    return Panel(text, title="💵 Bot Performance", border_style="green")
```

### Priority 2: Health Monitor 히스토리 트래킹 (1-2시간)

#### 2.1 Redis에 메트릭 히스토리 저장
```python
async def save_metrics_history(self, metrics: HealthMetrics):
    """Save metrics to Redis with 24h TTL"""
    key = f"metrics:history:{int(time.time())}"
    await self.redis.set(key, json.dumps(metrics.to_dict()), ex=86400)  # 24h

    # Maintain index
    await self.redis.zadd("metrics:index", {key: time.time()})

    # Cleanup old entries (keep last 1000)
    total = await self.redis.zcard("metrics:index")
    if total > 1000:
        await self.redis.zremrangebyrank("metrics:index", 0, -1001)

async def get_metrics_history(self, hours: int = 1) -> List[HealthMetrics]:
    """Get metrics from last N hours"""
    cutoff = time.time() - (hours * 3600)
    keys = await self.redis.zrangebyscore("metrics:index", cutoff, "+inf")

    metrics = []
    for key in keys:
        data = await self.redis.get(key)
        if data:
            metrics.append(HealthMetrics(**json.loads(data)))

    return metrics
```

#### 2.2 트렌드 분석
```python
def analyze_trends(self, history: List[HealthMetrics]) -> Dict:
    """Analyze metric trends"""
    if len(history) < 2:
        return {}

    # Win rate trend
    win_rates = [m.win_rate_pct for m in history]
    win_rate_trend = "improving" if win_rates[-1] > win_rates[0] else "declining"

    # PnL trend
    pnls = [float(m.pnl_today) for m in history]
    pnl_trend = sum(pnls[-10:]) / 10  # 10-period average

    # Error rate trend
    errors = [m.error_count_last_hour for m in history]
    error_trend = "increasing" if errors[-1] > errors[0] else "stable"

    return {
        "win_rate_trend": win_rate_trend,
        "pnl_trend": pnl_trend,
        "error_trend": error_trend
    }
```

### Priority 3: 웹 대시보드 (선택사항, 4-6시간)

FastAPI + Chart.js로 웹 기반 대시보드 구축:

```python
# src/ui/web_dashboard.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

@app.get("/")
async def get_dashboard():
    """Serve web dashboard"""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Hive Mind Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
        <h1>🐝 Hive Mind Trading System</h1>
        <div style="display: grid; grid-template-columns: 1fr 1fr;">
            <canvas id="pnlChart"></canvas>
            <canvas id="winRateChart"></canvas>
        </div>
        <script>
            // Fetch data from /api/metrics endpoint
            // Render charts with Chart.js
        </script>
    </body>
    </html>
    """)

@app.get("/api/metrics")
async def get_metrics():
    """Return current metrics as JSON"""
    # Return HealthMetrics.to_dict()
    pass
```

**실행**:
```bash
python3 -m uvicorn src.ui.web_dashboard:app --reload
# Visit http://localhost:8000
```

---

## 📋 구현 우선순위

| 항목 | 우선순위 | 예상 시간 | 영향도 |
|------|----------|-----------|--------|
| 거래 성과 패널 | **High** | 1시간 | 높음 |
| API 상태 인디케이터 | **High** | 30분 | 중간 |
| 봇별 PnL | **High** | 1시간 | 높음 |
| 메트릭 히스토리 | Medium | 1-2시간 | 중간 |
| 트렌드 분석 | Medium | 1시간 | 중간 |
| 웹 대시보드 | Low | 4-6시간 | 낮음 (nice-to-have) |

**총 예상 시간**: 4-6시간 (웹 대시보드 제외)

---

## 🎨 개선된 레이아웃 설계

```
┌─────────────────────────────────────────────────────────────────┐
│  🐝 Hive Mind Swarm System | Status: RUNNING | 2026-01-05 12:34 │
├──────────────────────────┬──────────────────────────────────────┤
│ 💰 Capital Allocation    │ 🌐 API Health                        │
│ Total: $1,000.00         │ Requests: 47/100 ████████░░ (47%)   │
│ Safe:  $  200.00         │ Errors: 2 ⚠️                         │
│ ────────────────────     │ Rate Limits: 0 ✅                    │
│ NEWS      : $  200.00    ├──────────────────────────────────────┤
│ STAT      : $  200.00    │ 📈 Trading Performance               │
│ ARB       : $  200.00    │ Trades: 23                           │
│ MIMIC     : $  200.00    │ Win Rate: 68.2% (15W / 7L / 1P)     │
├──────────────────────────┤ PnL: +$127.50 ▲                      │
│ 🤖 Agent Status          ├──────────────────────────────────────┤
│ 🤖 NEWS : ●  ONLINE      │ 💵 Bot Performance                   │
│ 🤖 STAT : ●  ONLINE      │ News Scalper: +$45.20 ▲             │
│ 🤖 ARB  : ●  ONLINE      │ Pure Arb:     +$82.30 ▲▲            │
│ 🤖 MIMIC: ⏳ WAITING     │ StatArb:      -$12.50 ▼             │
│                          │ EliteMimic:   +$15.00 ▲             │
├──────────────────────────┴──────────────────────────────────────┤
│ 📜 System Logs                                                  │
│ [12:34:01] INFO    News detected: Bitcoin ETF approved          │
│ [12:34:02] INFO    Signal strength: 0.92 (STRONG)              │
│ [12:34:03] INFO    ArbHunter: Increased scan frequency 10x     │
│ [12:34:04] INFO    Trade executed: BUY BTC-YES @ $0.67         │
│ [12:34:05] INFO    Position opened: $100 @ 68.2% confidence    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 구현 파일

개선사항을 적용할 파일:
- `src/ui/dashboard.py` - Swarm Dashboard 개선
- `src/core/health_monitor.py` - Health Monitor 히스토리 추가
- `src/ui/web_dashboard.py` - 웹 대시보드 (새 파일, 선택사항)

---

## 📝 다음 단계

1. ✅ Phase 1 (긴급 수정) 완료 후
2. ✅ Phase 2 (마켓 타겟팅) 완료 후
3. 대시보드 개선 시작 (Priority 1 항목부터)

---

**마지막 업데이트**: 2026-01-05
**상태**: 개선 제안 완료, 구현 대기
