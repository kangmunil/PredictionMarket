# Project Hive Mind - Quick Start Guide

## 5-Minute Setup

### Prerequisites

```bash
# 1. Start Redis (required for BudgetManager)
docker run -d -p 6379:6379 --name redis redis:alpine

# 2. Verify Redis is running
redis-cli ping
# Should output: PONG
```

### Install Dependencies

```bash
cd /Users/mac/BOT/PredictionMarket
pip install -r requirements.txt
```

### Environment Setup

Create `.env` file with your API keys:

```bash
# Polymarket
POLYMARKET_PRIVATE_KEY=0x...

# News Sources
NEWS_API_KEY=your_newsapi_key
TREE_NEWS_API_KEY=your_tree_news_key

# AI (for RAG system)
OPENROUTER_API_KEY=your_openrouter_key

# Database (optional)
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

## Running the Swarm

### Dry Run Mode (Recommended First)

```bash
# Run all 6 bots in dry-run mode
python3 run_swarm.py --dry-run --budget 1000.0
```

**Output:**
```
================================================================================
PROJECT HIVE MIND - Unified Trading Bot Swarm
================================================================================
Mode: DRY RUN
Total Budget: $1000.0
Enabled Bots: news_scalper, arbhunter, stat_arb, elitemimic, polyai, pure_arb
Redis: redis://localhost:6379
================================================================================

Initializing SignalBus...
SignalBus ready

Initializing BudgetManager...
Budget Allocation:
  arbhunter: $400.00 (40%)
  polyai: $350.00 (35%)
  elitemimic: $250.00 (25%)
  reserve: $100.00 (10%)
BudgetManager ready - Total Capital: $1000.0

Launching Bots:
📰 Launching News Scalper...
   News Scalper started
🎯 Launching ArbHunter...
   ArbHunter started
📊 Launching StatArb Live...
   StatArb Live started
🐋 Launching EliteMimic...
   EliteMimic started
🧠 Launching PolyAI...
   PolyAI started
⚡ Launching Pure Arbitrage V2...
   Pure Arbitrage V2 started

6 bots running concurrently
```

### Run Specific Bots Only

```bash
# Run only news scalper and arbitrage bots
python3 run_swarm.py --bots news_scalper arbhunter pure_arb --budget 500.0
```

### Live Trading Mode

```bash
# CAUTION: This uses real money!
python3 run_swarm.py --live --budget 1000.0
```

## Understanding the Dashboard

Every 60 seconds, you'll see a status update:

```
────────────────────────────────────────────────────────────────────────────────
SWARM STATUS
────────────────────────────────────────────────────────────────────────────────
Budget Allocation:
  arbhunter: $385.50
  polyai: $340.20
  elitemimic: $245.80
  reserve: $28.50

SignalBus Metrics:
  Signals Published: 1,247
  Signals Delivered: 4,523
  Avg Latency: 23.4ms        ← Should be <100ms
  Hot Tokens: 12
  Active Opportunities: 3

Active Bots: 6
  news_scalper: Running
  arbhunter: Running
  stat_arb: Running
  elitemimic: Running
  polyai: Running
  pure_arb: Running
────────────────────────────────────────────────────────────────────────────────
```

## Monitoring Signals

### View SignalBus Status (Python)

```python
import asyncio
from src.core.signal_bus import get_signal_bus

async def check_status():
    bus = await get_signal_bus()
    bus.print_status()

asyncio.run(check_status())
```

### View Budget Status (Redis CLI)

```bash
redis-cli

# Check available budgets
> GET budget:arbhunter:available
"385.50"

> GET budget:polyai:available
"340.20"

# Check pending allocations
> HGETALL budget:allocations
```

## Example: Signal Flow

Here's what happens when news breaks:

```
1. [News Scalper] Detects Bitcoin ETF news
   ↓
2. Publishes to SignalBus:
   - Signal Type: NEWS_EVENT
   - Priority: HIGH
   - Data: {headline, sentiment=0.9, entities=['Bitcoin']}
   ↓
3. [ArbHunter] Receives signal
   - Increases Bitcoin market scan frequency 10x
   - Scans every 6s instead of 60s
   ↓
4. [StatArb] Receives signal
   - Lowers Z-score entry threshold: 2.0 → 1.5
   - Easier to enter Bitcoin pairs
   ↓
5. [EliteMimic] Monitors for whale activity
   - If whale also buys Bitcoin → SIGNAL CONVERGENCE
   - Doubles position size
```

## Testing

### Run Unit Tests

```bash
# Test SignalBus
python3 -m pytest tests/test_swarm.py::test_signal_publish_subscribe -v

# Test signal convergence
python3 -m pytest tests/test_swarm.py::test_news_whale_convergence_scenario -v

# Run all tests
python3 -m pytest tests/test_swarm.py -v
```

### Run Performance Benchmark

```bash
# Test signal latency
python3 -m pytest tests/test_swarm.py::test_signal_latency -v

# Expected: Average latency <100ms
```

## Common Operations

### Stop the Swarm Gracefully

Press `Ctrl+C` in the terminal. The swarm will:
1. Stop accepting new signals
2. Complete in-flight trades
3. Close all positions (optional)
4. Display final performance report
5. Disconnect from Redis

### Reset Budget

```python
from src.core.budget_manager import BudgetManager
import asyncio

async def reset_budget():
    mgr = BudgetManager()
    await mgr.connect()
    await mgr.set_total_capital(Decimal("1000"))
    await mgr.disconnect()

asyncio.run(reset_budget())
```

### View Recent Signals

```python
from src.core.signal_bus import get_signal_bus
import asyncio

async def view_signals():
    bus = await get_signal_bus()

    # Get hot tokens
    hot = bus.get_hot_tokens(top_n=5)
    for token in hot:
        print(f"{token.market_name}: ${token.volume_1h:.0f}")

    # Get recent whale moves
    moves = bus.get_whale_moves(minutes=30)
    for move in moves:
        print(f"{move.entity}: {move.side} ${move.amount_usd:.0f}")

    # Get news events
    news = bus.get_news_events(minutes=60)
    for event in news:
        print(f"{event.headline}: {event.sentiment_score:.2f}")

asyncio.run(view_signals())
```

## Troubleshooting

### "Redis connection failed"

**Problem**: BudgetManager can't connect to Redis

**Solution**:
```bash
# Start Redis
docker run -d -p 6379:6379 redis:alpine

# Or check if Redis is running
docker ps | grep redis
```

### "Signal latency >100ms"

**Problem**: Slow signal delivery

**Causes**:
- Too many subscribers (>50 per signal type)
- Slow callback functions
- Network latency to Redis

**Solution**:
```python
# Optimize callback functions
async def fast_callback(signal):
    # Do heavy processing in background
    asyncio.create_task(process_signal(signal))
```

### "Budget allocation denied"

**Problem**: Bot can't get budget allocation

**Check budget status**:
```bash
redis-cli
> GET budget:arbhunter:available
> HGETALL budget:allocations
```

**Possible causes**:
- Budget exhausted (too many open positions)
- Pending allocations not released
- Circuit breaker active (risk limit exceeded)

## Configuration

### Adjust Budget Allocations

Edit `src/core/budget_manager.py`:

```python
# Default: 40% Arb, 35% AI, 25% Mimic
self.allocations = {
    "arbhunter": 0.40,
    "polyai": 0.35,
    "elitemimic": 0.25
}

# Custom: 50% Arb, 30% AI, 20% Mimic
self.allocations = {
    "arbhunter": 0.50,
    "polyai": 0.30,
    "elitemimic": 0.20
}
```

### Adjust Risk Limits

Edit `run_swarm.py` to pass custom risk limits:

```python
from src.swarm.risk_manager import RiskLimits

limits = RiskLimits(
    max_position_size_usd=Decimal("200"),    # Max per position
    max_total_exposure_usd=Decimal("800"),   # Total exposure
    max_daily_loss_usd=Decimal("100")        # Daily loss limit
)

risk_mgr = SwarmRiskManager(signal_bus, limits)
```

### Adjust Signal Weights

Edit `src/core/signal_bus.py`:

```python
def get_signal_strength(entity: str) -> float:
    # Current weights:
    # News: 40%, Whale: 30%, Global: 20%, Hot Token: 10%

    # Custom weights (example):
    strength += news_sentiment * 0.5    # Increase news weight to 50%
    strength += whale_signal * 0.3      # Keep whale at 30%
    strength += global_sentiment * 0.15 # Reduce global to 15%
    strength += hot_token_boost * 0.05  # Reduce hot token to 5%
```

## Advanced Usage

### Add Custom Bot

Create a new adapter in `src/swarm/bot_adapters.py`:

```python
class CustomBotAdapter(BaseBotAdapter):
    def __init__(self, signal_bus, budget_manager, dry_run=True):
        super().__init__("custom_bot", signal_bus, budget_manager, dry_run)

    async def start(self):
        await super().start()

        # Subscribe to signals
        self.signal_bus.subscribe(
            SignalType.NEWS_EVENT,
            self.bot_name,
            self._on_news
        )

    async def _on_news(self, signal: Signal):
        # React to news
        pass

    async def run(self):
        await self.start()

        while self.running:
            # Your bot logic here
            await asyncio.sleep(60)

        await self.stop()
```

Then add to `run_swarm.py`:

```python
bot_configs = {
    'custom_bot': {
        'adapter': CustomBotAdapter,
        'name': 'Custom Bot',
        'icon': '🤖'
    },
    # ... other bots
}
```

### Replay Historical Signals (Backtesting)

```python
# Save signals to file
bus = await get_signal_bus()
history = bus._signal_history

with open('signals.json', 'w') as f:
    json.dump([s.to_dict() for signals in history.values() for s in signals], f)

# Replay later
with open('signals.json', 'r') as f:
    signals = json.load(f)

for signal_data in signals:
    await bus.publish(Signal(**signal_data))
```

## Performance Tips

### Optimize for Low Latency

1. **Use local Redis**: Don't use cloud Redis for BudgetManager
2. **Minimize callback work**: Do heavy processing in background tasks
3. **Batch signals**: Publish multiple related signals together
4. **Reduce TTL**: Shorter TTL = faster cleanup = less memory

### Scale to More Bots

1. **Monitor signal bus metrics**: Watch `avg_latency_ms`
2. **Use message queue**: For >20 bots, consider Redis Pub/Sub
3. **Separate state storage**: Move hot tokens to dedicated cache
4. **Profile bottlenecks**: Use `cProfile` to find slow spots

## Next Steps

1. **Read Full Documentation**: [SWARM_ARCHITECTURE.md](SWARM_ARCHITECTURE.md)
2. **Understand Signal Types**: Study signal routing rules
3. **Test in Dry Run**: Run for 24 hours to see signal flow
4. **Monitor Performance**: Check metrics, latency, budget usage
5. **Start Small Live**: Run with $100 budget to test real trading
6. **Scale Gradually**: Increase budget as confidence grows

## Support

**Files**:
- Architecture: `/Users/mac/BOT/PredictionMarket/SWARM_ARCHITECTURE.md`
- SignalBus: `/Users/mac/BOT/PredictionMarket/src/core/signal_bus.py`
- Runner: `/Users/mac/BOT/PredictionMarket/run_swarm.py`
- Tests: `/Users/mac/BOT/PredictionMarket/tests/test_swarm.py`

**Logs**:
- Main log: `logs/swarm_*.log`
- Individual bots: `logs/news_scalper_*.log`, etc.

---

**Happy Swarming!** 🐝
