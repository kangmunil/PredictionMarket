import asyncio
import logging
import os
import json
from datetime import datetime, timedelta
from decimal import Decimal
from src.core.rag_system_openrouter import OpenRouterRAGSystem, NewsEvent
from src.core.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_backtest(lookback_days: int = 7):
    """
    Backtest historical news events from Supabase.
    """
    config = Config()
    rag = OpenRouterRAGSystem(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_key=os.getenv("SUPABASE_KEY")
    )
    
## 10. Bot Improvement Sprint (11 Tasks) - ✅ COMPLETE
We successfully completed the major "Bot Improvement Sprint" covering stability, strategy, and observability.

### 🔴 High Priority: Infrastructure & Safety
*   **Stale Position Cleanup**: The bot now auto-purges untracked/old positions (24h+) on startup to prevent repeated 404 API spam from resolved markets.
*   **RPC Fallback**: `WalletWatcher` now rotates between 3 RPC endpoints. If the primary fails, it switches to backups to ensure persistent wallet tracking.
*   **Trading Hours Filter**: `NewsScalper` now respects US Market Hours (9 AM - 5 PM EST) and skips weekends, focusing on the most liquid news events.

### 🟡 Medium Priority: Strategy & Risk
*   **Liquidity Filter**: Tightened `MAX_SPREAD` from 5% to **3%** to ensure better entry prices.
*   **News Deduplication**: Enhanced with **Fuzzy Title Matching** (difflib). Articles with similar titles within 1 hour are skipped even if the URL is different.
*   **Dynamic Stop-Loss**: Stop-loss now scales with market volatility (using spread as a proxy).
*   **Trailing Stop**: Implemented "Lock-in" logic. Once a trade hits 5% profit, a **2% trailing stop** is activated to protect gains.

### 🟢 Low Priority: Monitoring & Tools
*   **Backtesting System**: Added `src/tools/backtest_news.py` to replay historical news through the RAG brain for performance analysis.
*   **Dashboard Upgrade**: Added a **Whale Activity** panel to the terminal UI to track large-scale market movements.
*   **Telegram Integration**: Real-time trade execution alerts and daily performance reports are now sent to the [Swarm Signals Bot].
*   **Strategy Weighting**: `BudgetManager` now enforces allocation caps (40% News, 35% StatArb, 25% Mimic) to ensure balanced exposure.

## 11. Final Verification (Current Session)
*   **BudgetManager**: Successfully enforces weights as "soft caps" (overridden only by high-priority requests).
*   **NewsScalper**: Fuzzy dedup and trailing stops verified via code review and unit checks.
*   **Dashboard**: Whale panel integration complete.

**The bot is now highly robust, more selective in its trades, and easier to monitor remotely.**
    
    logger.info(f"🚀 Starting backtest for last {lookback_days} days...")
    
    # 1. Fetch historical news from Supabase
    try:
        from_date = (datetime.now() - timedelta(days=lookback_days)).isoformat()
        response = rag.supabase.table('news_events')\
            .select('*')\
            .gt('published_at', from_date)\
            .order('published_at', desc=True)\
            .execute()
        
        events_data = response.data
        logger.info(f"📅 Found {len(events_data)} historical events.")
        
        results = []
        for item in events_data:
            event = NewsEvent(
                event_id=item['event_id'],
                title=item['title'],
                content=item['content'],
                source=item['source'],
                published_at=datetime.fromisoformat(item['published_at']),
                entities=item['entities'],
                category=item['category'],
                url=item.get('url'),
                sentiment=item.get('sentiment')
            )
            
            # Simple mock market question for backtest
            market_question = f"Will the event related to '{event.title}' happen?"
            current_price = Decimal("0.5") # Mock mid price
            
            logger.info(f"🔍 Analyzing: {event.title[:50]}...")
            
            impact = await rag.analyze_market_impact(
                event=event,
                market_id="backtest_mock",
                current_price=current_price,
                market_question=market_question
            )
            
            results.append({
                "title": event.title,
                "published_at": event.published_at.isoformat(),
                "suggested_price": float(impact.suggested_price),
                "confidence": impact.confidence,
                "recommendation": impact.trade_recommendation,
                "reasoning": impact.reasoning
            })
            
        # 2. Save results
        output_file = f"data/backtest_results_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
            
        logger.info(f"✅ Backtest complete! Results saved to {output_file}")
        
    except Exception as e:
        logger.error(f"❌ Backtest failed: {e}")
    finally:
        await rag.close()

if __name__ == "__main__":
    asyncio.run(run_backtest())
