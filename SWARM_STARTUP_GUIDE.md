# Swarm System Startup Guide

## Quick Start

### Using the Startup Script (Recommended)
```bash
# Make script executable (first time only)
chmod +x start_swarm.sh

# Launch with UI in dry-run mode (safe for testing)
./start_swarm.sh --ui --dry-run

# Launch without UI in dry-run mode
./start_swarm.sh --dry-run

# Launch in LIVE trading mode (WARNING: real money!)
./start_swarm.sh --ui
```

### Manual Start (Advanced Users)
```bash
# Activate virtual environment
source venv/bin/activate

# Run with UI in dry-run mode
python run_swarm.py --ui --dry-run

# Run without UI in dry-run mode
python run_swarm.py --dry-run
```

## System Architecture

The Swarm Intelligence System consists of 6 coordinated bots:

1. **NewsScalper** - Real-time news monitoring with RAG AI analysis
2. **StatArb** - Statistical arbitrage based on market correlations
3. **EliteMimic** - Whale wallet monitoring and copy trading
4. **PureArb** - Pure arbitrage across Polymarket and Gamma
5. **HealthMonitor** - System health and signal monitoring
6. **DailyReport** - Automated performance reporting

## Recent Fixes (2026-01-06)

### Issue: Bots Not Starting
**Problem**: When running `python3 run_swarm.py --ui --dry-run`, the system would stop after SignalBus initialization and the 6 bots would not start.

**Root Causes Identified and Fixed**:

1. **Missing Notifier Initialization**
   - Location: `run_swarm.py`, line 73
   - Issue: The notifier initialization code was replaced with a comment placeholder
   - Fix: Restored complete `TelegramNotifier` initialization with polling

2. **Missing Attribute Reference**
   - Location: `run_swarm.py`, `__init__` method
   - Issue: Code referenced `self.trade_history` but only `self.completed_trades` existed
   - Fix: Added `self.trade_history = self.completed_trades` alias

3. **Wrong Python Interpreter**
   - Issue: User was running with system Python3 instead of venv
   - System Python: `/opt/homebrew/bin/python3` (v3.13.5) - missing dependencies
   - Venv Python: `venv/bin/python` (v3.12.3) - has all dependencies
   - Fix: Created `start_swarm.sh` script to ensure correct environment

4. **Improved Error Handling**
   - Added comprehensive exception handling in `run()` method
   - Added logging for bot task creation and initialization steps
   - Added safety checks for disabled notifier in `_daily_report_task()`

### Files Modified
```
✅ run_swarm.py           - Fixed notifier init, added error handling
✅ src/ui/dashboard.py    - Improved logging error handling
✅ start_swarm.sh         - NEW: Startup script with correct Python
✅ SWARM_STARTUP_GUIDE.md - NEW: This documentation
```

## Verification

After fixes, the system properly initializes all 6 bots as shown in logs:

```log
2026-01-06 16:47:21 [INFO] SwarmOrchestrator: ✅ All Agents Initialized & Connected to Hive Mind
2026-01-06 16:47:21 [INFO] SwarmOrchestrator: 🚀 Swarm 요원 가동 시작... (감시 키워드: 18개)
2026-01-06 16:47:21 [INFO] SwarmOrchestrator: 📋 Starting 6 bots: NewsScalper, StatArb, EliteMimic, PureArb, HealthMonitor, DailyReport
2026-01-06 16:47:21 [INFO] SwarmOrchestrator: ✅ All 6 bot tasks created successfully
2026-01-06 16:47:21 [INFO] src.news.news_scalper_optimized: 🚀 OPTIMIZED NEWS SCALPING BOT STARTED
2026-01-06 16:47:21 [INFO] src.strategies.stat_arb_enhanced: 🛡️ Enhanced Stat Arb Strategy Started
2026-01-06 16:47:21 [INFO] src.strategies.elite_mimic: 🌑 EliteMimic Agent: '나는 고수들의 그림자를 따라가는 그림자 트레이더입니다.'
2026-01-06 16:47:21 [INFO] src.strategies.arbitrage: >>> ArbHunter Online: High-Frequency WebSocket Mode <<<
```

## Environment Requirements

### Required Environment Variables (.env file)
```bash
# Polymarket API
POLY_PRIVATE_KEY=your_private_key
POLY_ADDRESS=your_wallet_address
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_secret
POLYMARKET_PASSPHRASE=your_passphrase

# News APIs
NEWS_API_KEY=your_newsapi_key
TREE_NEWS_API_KEY=your_treenews_key

# AI/RAG System
OPENROUTER_API_KEY=your_openrouter_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key

# Telegram Notifications (optional)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Python Dependencies
All dependencies are listed in `requirements.txt`. Install with:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'dotenv'"
**Solution**: You're using the wrong Python. Use `./start_swarm.sh` or activate venv first:
```bash
source venv/bin/activate
python run_swarm.py --ui --dry-run
```

### Issue: Dashboard not showing or blank screen
**Solution**: Ensure your terminal supports Rich library's TUI features. Try:
```bash
# Update Rich library
pip install --upgrade rich

# Test terminal compatibility
python -c "from rich.console import Console; Console().print('[bold green]Test[/]')"
```

### Issue: Bots start but crash immediately
**Solution**: Check the log file in `logs/swarm_YYYYMMDD_HHMMSS.log` for detailed error traces.

### Issue: "Telegram Notifier disabled"
**Solution**: This is normal if you haven't configured Telegram credentials. The system will work fine without notifications. To enable:
1. Create a Telegram bot via @BotFather
2. Get your chat ID via @userinfobot
3. Add credentials to `.env` file

## Dashboard Controls

When running with `--ui` flag:

- **Q** - Quit the system
- **P** - Pause trading (switch to dry-run mode)
- **R** - Resume trading

## Log Files

All activity is logged to `logs/swarm_YYYYMMDD_HHMMSS.log`

To monitor in real-time:
```bash
tail -f logs/swarm_*.log
```

## Safety Notes

1. **Always test with `--dry-run` first** before live trading
2. Monitor the dashboard for the first few hours
3. Start with small capital allocation in `BudgetManager`
4. Review logs regularly for unexpected behavior
5. Keep API keys secure and never commit them to git

## Support

For issues or questions:
1. Check logs in `logs/` directory
2. Review this guide for common solutions
3. Verify all environment variables are set correctly
4. Ensure using venv Python (`./start_swarm.sh`)
