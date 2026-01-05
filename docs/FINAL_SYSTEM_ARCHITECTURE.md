# 🏗️ ArbHunter V2: Final System Architecture

**"The Complete System"** - A hybrid trading engine combining low-latency news scalping with statistical arbitrage.

---

## 1. Core Philosophy
Combine the **Speed of Information** (News) with the **Safety of Math** (Stat Arb).
- **Event-Driven:** Do not search for random markets; wait for news to trigger analysis.
- **Statistically Validated:** Do not trade on sentiment alone; verify with price statistics (Z-score).

---

## 2. The 4-Stage Pipeline

### Phase 1: Information Ingestion (The Eyes)
*   **Sources:** Tree News (WebSocket/API) + NewsAPI (HTTP).
*   **Speed:** Parallel processing using `asyncio.gather`.
*   **Analysis:** `FinBERT` model for financial sentiment (Positive/Negative).
*   **Filter:** Minimum confidence score (80%+) & Source Credibility.

### Phase 2: Intelligent Targeting (The Brain)
*   **Entity Extraction:** Extract keywords (e.g., "Bitcoin", "SEC") from headlines.
*   **Noise Cancellation:** Use Polymarket **Tag ID `1` (Crypto)** to filter out sports/politics.
*   **Strict Matching:** Only select markets with volume > $100 and exact keyword matches.

### Phase 3: Strategic Bridge (The Synapse)
*   **Module:** `NewsToArbBridge`
*   **Logic:**
    1. Receive "High Impact News" signal.
    2. Dynamically find the relevant Polymarket market.
    3. Pair it with a benchmark (e.g., ETH) for correlation analysis.
    4. Trigger `StatArb` engine to calculate Cointegration & Z-score.

### Phase 4: Execution & Protection (The Hands)
*   **Execution:** 29ms latency target using pre-warmed connections.
*   **Slippage Protection:** Limit orders with max 2% slippage cap.
*   **Risk Management:**
    - **Stop-Loss:** Auto-close if P&L hits -5%.
    - **Time-Exit:** Close after 1-6 hours (news decay).

---

## 3. Directory Structure

```
src/
├── news/
│   ├── news_scalper_optimized.py  # Main Engine (Phase 4)
│   ├── news_aggregator.py         # Data Collection (Phase 1)
│   ├── sentiment_analyzer.py      # AI Analysis (Phase 1)
│   └── market_matcher.py          # Market Finding (Phase 2)
├── strategies/
│   ├── news_arb_bridge.py         # Connector (Phase 3)
│   ├── stat_arb_enhanced.py       # Math Engine (Phase 3)
│   └── market_discovery.py        # Discovery Logic (Phase 2)
└── core/
    └── clob_client.py             # Execution Interface
```

---

## 4. Execution Command

To run the complete optimized system:

```bash
python3 run_news_scalper_optimized.py
```

---

**Status:** Ready for Production Deployment 🚀
