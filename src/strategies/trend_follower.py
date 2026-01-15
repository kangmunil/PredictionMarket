import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from decimal import Decimal

from src.core.config import Config
from src.core.clob_client import PolyClient
from src.core.gamma_client import GammaClient
from src.core.price_history_api import PolymarketHistoryAPI
from src.news.news_aggregator import NewsAggregator
from src.core.rag_system_openrouter import OpenRouterRAGSystem, NewsEvent

logger = logging.getLogger(__name__)

class SmartTrendFollower:
    """
    Proactive Trend Following Strategy.
    
    Logic:
    1. Identify 'Hot' Markets via Gamma API (High Volume/Liquidity).
    2. Fetch recent news for these markets.
    3. Use RAG to validate if the trend is supported by fundamental news.
    4. Execute trade if Momentum + News Alignment exists.
    """

    def __init__(self, client: PolyClient, budget_manager=None):
        self.client = client
        self.budget_manager = budget_manager
        self.config = Config()
        
        # Components
        self.gamma = GammaClient()
        self.news_aggregator = NewsAggregator(
            news_api_key=self.config.NEWS_API_KEY,
            tree_api_key=self.config.TREE_NEWS_API_KEY
        )
        self.rag = OpenRouterRAGSystem(
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_key=os.getenv("SUPABASE_KEY")
        )
        self.history_api = PolymarketHistoryAPI()

        
        # Strategy Params
        self.min_volume = 3000.0 # Lowered from 5000 to catch emerging trends
        self.scan_interval = 300 # 5 minutes
        self.min_confidence = 0.75
        self.max_position = 20.0 # Small aggressive bets
        
        # Position Management
        self.active_positions: Dict[str, Dict] = {} # token_id -> {entry_price, size, market_question, timestamp}

        # Cache to avoid re-trading same trend immediately
        self.cooldowns: Dict[str, datetime] = {}
        self.cooldown_duration = timedelta(hours=4)

    async def run(self):
        """Main Strategy Loop"""
        logger.info("🚀 SmartTrendFollower: Activated. Scanning for trends...")
        
        while True:
            try:
                # 1. Normal Trend Scan (Hours/Days)
                await self._scan_and_trade()
                
                # 2. Scalp Scan (15m - Algo Style)
                await self._scan_scalp_candidates()
                
                # 3. Manage Positions
                await self._manage_positions()

            except Exception as e:
                logger.error(f"Error in TrendFollower loop: {e}", exc_info=True)
            
            await asyncio.sleep(self.scan_interval)

    async def _manage_positions(self):
        """Monitor active positions for TP/SL"""
        if not self.active_positions:
            return

        logger.info(f"🛡️ Managing {len(self.active_positions)} active positions...")
        
        # Create list of IDs to remove after closing
        closed_ids = []
        
        for token_id, pos in self.active_positions.items():
            try:
                current_price_str = await self.client.get_price(token_id)
                if not current_price_str: continue
                current_price = float(current_price_str)
                
                entry_price = pos['entry_price']
                side = pos['side']
                
                # Calculate PnL
                if side == "BUY":
                    pnl_pct = (current_price - entry_price) / entry_price
                    close_side = "SELL"
                else: # SELL (Short)
                    pnl_pct = (entry_price - current_price) / entry_price
                    close_side = "BUY"
                
                # Exit Logic
                should_close = False
                reason = ""
                
                # 1. Take Profit (+20%)
                if pnl_pct >= 0.20:
                    should_close = True
                    reason = f"Take Profit (+{pnl_pct*100:.1f}%)"
                    
                # 2. Stop Loss (-10%)
                elif pnl_pct <= -0.10:
                    should_close = True
                    reason = f"Stop Loss ({pnl_pct*100:.1f}%)"
                    
                # 3. Time Limit (24h)
                elif datetime.now() - pos['timestamp'] > timedelta(hours=24):
                    should_close = True
                    reason = "Time Limit (24h)"
                    
                if should_close:
                    logger.info(f"🔄 Closing Position: {pos['market_question'][:30]} | Reason: {reason}")
                    
                    if not self.config.DRY_RUN:
                        # Close with limit order at current price (slippage protected)
                        # Note: We need to sell the SIZE (shares) we have
                        # But place_limit... takes USD AMOUNT usually. 
                        # Wait, clob_client.place_limit... takes AMOUNT in USD.
                        # We need to calculate USD value = shares * current_price
                        close_amount_usd = pos['size'] * current_price
                        
                        resp = await self.client.place_limit_order_with_slippage_protection(
                            token_id=token_id,
                            side=close_side,
                            amount=close_amount_usd,
                            target_price=current_price
                        )
                        if resp:
                            logger.info(f"      ✅ Closed: {reason}")
                            closed_ids.append(token_id)
                    else:
                        logger.info(f"      📝 [DRY RUN] Would Close: {reason}")
                        closed_ids.append(token_id)
                        
            except Exception as e:
                logger.error(f"Error managing position {token_id}: {e}")
                
        # Remove closed positions
        for tid in closed_ids:
            self.active_positions.pop(tid, None)

    async def _scan_and_trade(self):
        """Core logic: Scan -> Analyze -> Execute"""
        
        # 1. Get Active Markets
        markets = await self.gamma.get_active_markets(
            limit=20, 
            volume_min=self.min_volume,
            max_hours_to_close=24*7 # Weekly or shorter
        )
        
        logger.info(f"🔎 TrendScanner: Found {len(markets)} active markets")
        
        for market in markets:
            condition_id = market.get('condition_id')
            if not condition_id or self._is_cooldown(condition_id):
                continue
                
            # 2. Extract Keywords & Check Momentum
            # (Simple momentum check: is price drifting? We need history for that, 
            # for now we assume High Volume + News = Trend)
            question = market.get('question', '')
            keywords = self._extract_keywords(question)
            
            if not keywords: 
                continue

            logger.info(f"   👉 Analyzing Trend Candidate: {question[:50]}...")
            
            # 3. Fetch News
            articles = await self.news_aggregator.get_breaking_news(
                keywords, 
                max_results=3
            )
            
            if not articles:
                logger.debug("      No news found. Skipping.")
                continue
                
            # 4. Analyze with RAG
            # Use the freshest article
            latest_article = articles[0]
            
            # Get current price
            # Need token ID. Gamma gives 'clobTokenIds' or 'tokens'
            token_id = self._get_yes_token(market)
            if not token_id: continue
            
            try:
                current_price_str = await self.client.get_price(token_id)
                current_price = Decimal(str(current_price_str)) if current_price_str else Decimal("0.5")
            except:
                current_price = Decimal("0.5")

            # Create NewsEvent wrapper
            event = NewsEvent(
                title=latest_article['title'],
                content=latest_article.get('description') or latest_article.get('content') or "",
                source=latest_article.get('source', {}).get('name', 'Unknown'),
                published_at=datetime.now(), # Approximation if parsing fails
                url=latest_article.get('url', '')
            )
            
            # RAG Analysis
            impact = await self.rag.analyze_market_impact(
                event,
                market_id=condition_id,
                current_price=current_price,
                market_question=question
            )
            
            logger.info(f"      🤖 AI Insight: {impact.trade_recommendation} ({impact.confidence*100:.0f}%) -> {impact.reasoning[:50]}...")

            # 5. Execution Decision
            if impact.confidence >= self.min_confidence and impact.trade_recommendation != 'hold':
                await self._execute_trend_trade(token_id, impact.trade_recommendation, market, impact)
                self._set_cooldown(condition_id)


    async def _scan_scalp_candidates(self):
        """
        Mimic 'distinct-baguette': Scan for 15m crypto markets and trade momentum.
        """
        logger.info("⚡ ScalpScanner: Hunting for 15m crypto opportunities...")
        
        # 1. Broaden Search (Crypto, Politics, Sports)
        # Fetch top active markets by volume (Category Agnostic)
        markets = await self.gamma.get_active_markets(limit=60, volume_min=self.min_volume)
        
        # Filter for Expanded Categories
        allowed_tags = ['Crypto', 'Politics', 'Sports', 'Business', 'Trump', 'Elon', 'Tech']
        
        active_markets = [
            m for m in markets 
            if m.get('active') and 
            (
                any(tag in str(m.get('tags', [])) for tag in allowed_tags) or 
                any(k in m.get('question', '') for k in ['ETH', 'BTC', 'Fed', 'Rate', 'Trump', 'Elon', 'Kamala'])
            )
        ]
        
        logger.info(f"   ⚡ Found {len(active_markets)} potential scalp markets")
        
        for market in active_markets:
            condition_id = market.get('condition_id')
            if not condition_id or self._is_cooldown(condition_id):
                continue
                
            # Get Yes Token ID
            token_id = self._get_yes_token(market)
            if not token_id: continue
            
            # 2. Check Price Momentum (Last 30 mins)
            try:
                # Use History API to get recent price points
                history, source = await self.history_api.get_history_with_source(
                    condition_id=condition_id, days=1, min_points=5
                )
                
                if len(history) < 5:
                    continue
                    
                # Analyze last few ticks
                # history is a list of {'price': float, 'timestamp': datetime}
                current = history[-1]
                prev = history[-min(len(history), 3)] # 2-3 ticks ago
                
                current_price = float(current['price'])
                prev_price = float(prev['price'])
                
                # Calculate simple return
                if prev_price == 0: continue
                momentum = (current_price - prev_price) / prev_price
                
                logger.debug(f"      📈 {market.get('question')[:30]} Mom: {momentum*100:.2f}% (${current_price})")
                
                # Scalp Signal: Strong Breakout (>3% move recently)
                # distinct-baguette buys volatility.
                if momentum > 0.03 and current_price < 0.85: 
                     logger.info(f"   🚀 SCALP SIGNAL: {market.get('question')} | Mom: {momentum*100:.1f}%")
                     
                     # Check Budget
                     if self.config.DRY_RUN:
                         logger.info(f"      📝 [DRY RUN] Would SCALP BUY $10 on {token_id}")
                         continue

                     # Execute Scalp
                     # Use aggressive limit (target = current * 1.01)
                     target_price = round(current_price * 1.01, 3)
                     
                     await self.client.place_limit_order_with_slippage_protection(
                         token_id=token_id,
                         side="BUY",
                         amount=10.0, # Fixed scalp size
                         priority="high",
                         max_slippage_pct=3.0, # Low liquidity tolerance
                         target_price=target_price
                     )
                     
                     # Record position with aggressive take profit
                     self.active_positions[token_id] = {
                        'entry_price': current_price,
                        'size': 10.0 / current_price, # shares estimated
                        'market_question': market.get('question'),
                        'timestamp': datetime.now(),
                        'side': 'BUY',
                        'strategy': 'scalp'
                    }
                    
                     # Cooldown
                     self.cooldowns[condition_id] = datetime.now()
                     
            except Exception as e:
                logger.error(f"Error scanning scalp candidate {token_id}: {e}")

    async def _execute_trend_trade(self, token_id: str, side: str, market: dict, impact):
        """Execute the trade via CLOB with positions tracking"""
        amount = self.max_position
        
        # Budget Check
        if self.budget_manager:
            alloc = await self.budget_manager.request_allocation("trend_follower", Decimal(str(amount)))
            if not alloc: 
                logger.warning("      💸 Budget denied for trend trade")
                return

        logger.info(f"🚀 TREND EXECUTION: {side} ${amount} on {market['question'][:30]} (Target: {impact.suggested_price})")
        
        if not self.config.DRY_RUN:
            try:
                # Use Limit Order with Slippage Protection + AI Target Price
                resp = await self.client.place_limit_order_with_slippage_protection(
                    token_id=token_id, 
                    side=side.upper(), 
                    amount=amount,
                    target_price=float(impact.suggested_price)
                )
                
                if resp:
                    logger.info(f"      ✅ Filled: {resp.get('filled')} shares @ ${resp.get('price')}")
                    
                    # Track Position
                    self.active_positions[token_id] = {
                        "entry_price": float(resp.get('price')),
                        "size": float(resp.get('filled')),
                        "side": side.upper(),
                        "market_question": market.get('question'),
                        "timestamp": datetime.now(),
                        "target_price": float(impact.suggested_price)
                    }
                else:
                    logger.warning("      ❌ Trade failed (no fill)")
                    # Release budget if failed
                    if self.budget_manager:
                        await self.budget_manager.release_allocation("trend_follower", alloc, Decimal(str(amount)))

            except Exception as e:
                logger.error(f"      ❌ Execution Failed: {e}")
                if self.budget_manager:
                    await self.budget_manager.release_allocation("trend_follower", alloc, Decimal(str(amount)))
        else:
            logger.info(f"      📝 [DRY RUN] Would {side} ${amount} at target ${impact.suggested_price}")
            # Mock position tracking for dry run
            self.active_positions[token_id] = {
                "entry_price": float(impact.current_price),
                "size": amount / float(impact.current_price or 0.5),
                "side": side.upper(),
                "market_question": market.get('question'),
                "timestamp": datetime.now(),
                "target_price": float(impact.suggested_price)
            }

    def _extract_keywords(self, question: str) -> List[str]:
        """Simple keyword extractor"""
        ignore = {'will', 'the', 'be', 'of', 'in', 'at', 'on', 'to', 'a', 'before', 'after'}
        words = [w.strip("?.,") for w in question.lower().split()]
        return [w for w in words if w not in ignore and len(w) > 3][:3]

    def _get_yes_token(self, market: dict) -> Optional[str]:
        """
        Robustly identify the 'Yes' token ID.
        """
        # 1. Check if we have both definitions
        clob_ids = market.get('clobTokenIds')
        tokens = market.get('tokens')
        
        if not clob_ids or not tokens:
            return None
            
        if len(clob_ids) != len(tokens):
            logger.warning(f"⚠️ Token mismatch for {market.get('question')}: {len(clob_ids)} IDs vs {len(tokens)} tokens")
            return None
            
        # 2. Iterate and find 'Yes'
        for i, token in enumerate(tokens):
            outcome = token.get('outcome', '').upper()
            if outcome == 'YES':
                return clob_ids[i]
                
        # 3. Fallback: If binary [Yes, No], usually 0 is Yes? 
        # But safest is to return None if explicit 'Yes' not found 
        # (could be A vs B market)
        
        # Check for "Long" or other positives?
        return None

    def _is_cooldown(self, condition_id: str) -> bool:
        if condition_id in self.cooldowns:
            if datetime.now() < self.cooldowns[condition_id]:
                return True
        return False
        
    def _set_cooldown(self, condition_id: str):
        self.cooldowns[condition_id] = datetime.now() + self.cooldown_duration
