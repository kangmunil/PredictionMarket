# 🚀 Quick Start - Statistical Arbitrage V2

## One-Line Test Commands

### 1. Dry Run (No Real Trades)
```bash
python3 run_stat_arb_live_v2.py --dry-run --category crypto --max-pairs 2
```

### 2. Live Trading (Conservative)
```bash
python3 run_stat_arb_live_v2.py --category crypto --max-pairs 1 --interval 600
```

### 3. Live Trading (Normal)
```bash
python3 run_stat_arb_live_v2.py --category crypto --max-pairs 3 --interval 300
```

---

## Expected Output (Success)

```
🤖 STATISTICAL ARBITRAGE V2 - INITIALIZATION
================================================================================
Category: crypto
Max Pairs: 2
================================================================================
📋 Loaded 6 pair configurations
   High Priority: 3
   Medium Priority: 2

🔍 Starting market discovery...

🔎 Searching for pair: BTC_ETH_Weekly_Correlation
📊 Market Discovery: Found 8 markets matching criteria
   ✅ SUCCESS!

🔎 Searching for pair: BTC_Sentiment_Daily
📊 Market Discovery: Found 5 markets matching criteria
   ✅ SUCCESS!

⚙️ Initializing 2 strategies...
   ✅ BTC_ETH_Weekly_Correlation
   ✅ BTC_Sentiment_Daily

✅ Initialization complete: 2 strategies active
```

---

## Expected Output (No Markets)

```
🔍 Starting market discovery...

🔎 Searching for pair: BTC_ETH_Weekly_Correlation
📊 Market Discovery: Found 0 markets matching criteria
   ❌ No markets found

❌ No markets found! Cannot proceed.
   Possible reasons:
   1. No active short-term markets at this time
   2. Check timeframe filters (try different times)
   3. Volume requirements too high
```

**Solution**: 다른 시간대에 재시도 (미국 저녁 시간 best)

---

## Monitor Logs

```bash
# Real-time monitoring
tail -f logs/stat_arb_v2.log

# Find signals
grep "SIGNAL" logs/stat_arb_v2.log

# Find errors
grep "ERROR" logs/stat_arb_v2.log
```

---

## Files to Check

✅ Configuration: src/strategies/stat_arb_config_v2.py
✅ Discovery: src/strategies/market_discovery.py
✅ Launcher: run_stat_arb_live_v2.py
📖 Full Guide: STAT_ARB_V2_GUIDE.md
📊 Complete Report: STAT_ARB_V2_COMPLETE.md

---

## Next: GAP Analysis Options

After testing Stat Arb V2, return to GAP_ANALYSIS_REPORT.md:

- **Option 1**: Pure Arbitrage (WebSocket) - ✅ DONE
- **Option 2**: Agentic RAG with LangGraph - 70% complete
- **Option 3**: Stat Arb V2 - ✅ DONE
- **Option 4**: News Scalping Bot - 0% (HIGH priority)
- **Option 5**: Momentum Trading Bot - 0% (MEDIUM priority)
