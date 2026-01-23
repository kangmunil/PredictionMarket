import asyncio
import logging
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from decimal import Decimal

from src.core.config import Config
from src.core.config import Config
from src.core.clob_client import PolyClient, MarketDelistedError
from src.core.gamma_client import GammaClient
from src.core.gamma_client import GammaClient
from src.core.price_history_api import PolymarketHistoryAPI
from src.news.news_aggregator import NewsAggregator
from src.core.rag_system_openrouter import OpenRouterRAGSystem, NewsEvent
from src.strategies.crypto_15min_filter import Crypto15MinFilter

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

    def __init__(self, client: PolyClient, budget_manager=None, status_reporter=None, pnl_tracker=None, signal_bus=None):
        self.client = client
        self.budget_manager = budget_manager
        self.status_reporter = status_reporter
        self.pnl_tracker = pnl_tracker
        self.signal_bus = signal_bus
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
        self.crypto_filter = Crypto15MinFilter()

        
        # Strategy Params
        self.min_volume = 3000.0 # Lowered from 5000 to catch emerging trends
        self.scan_interval = 300 # 5 minutes
        self.min_confidence = 0.75
        self.max_position = 20.0 # Small aggressive bets
        
        # Position Management
        self.state_file = "data/trend_follower_state.json"
        self.active_positions: Dict[str, Dict] = self._load_state() 

        # Cache to avoid re-trading same trend immediately
        self.cooldowns: Dict[str, datetime] = {}
        self.cooldown_duration = timedelta(hours=4)
        
        self.is_running = True

    async def run(self):
        """Main Strategy Loop"""
        logger.info("🚀 SmartTrendFollower: Activated. Scanning for trends...")
        
        # Sync existing positions on startup
        await self._sync_with_account()
        
        while self.is_running:
            try:
                # 0. Low Capital Check
                if self.budget_manager and self.budget_manager.is_low_capital:
                    logger.debug("⚠️ Low Capital Mode: Skipping new trade scans (Waiting for funds/exits)")
                    # Still manage existing positions (sell-only mode)
                    await self._manage_positions()
                    await asyncio.sleep(self.scan_interval)
                    continue

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
        """Monitor active positions for TP/SL, Trailing Stop, and Partial Exit"""
        if not self.active_positions:
            return

        logger.info(f"🛡️ Managing {len(self.active_positions)} active positions...")
        
        # Create list of IDs to remove after closing
        closed_ids = []
        state_changed = False
        
        for token_id, pos in self.active_positions.items():
            if pos.get('zombie'):
                continue
            try:
                # Use get_real_market_price with condition_id fallback
                condition_id = pos.get('condition_id')
                current_price = await self.client.get_real_market_price(token_id, condition_id)
                
                if current_price is None:
                    # Fallback to orderbook bid/ask if MCP/REST fails
                    bid_price, _ = self.client.get_best_bid(token_id)
                    current_price = bid_price
                    
                if not current_price or current_price <= 0:
                    continue
            except MarketDelistedError as e:
                logger.warning(f"❌ Market Delisted/Invalid: {token_id}. Auto-removing position. ({e})")
                closed_ids.append(token_id)
                state_changed = True
                continue
            except Exception as e:
                logger.error(f"Error fetching price for {token_id}: {e}")
                continue
                
                entry_price = pos['entry_price']
                side = pos['side']
                
                # Update High Water Mark for Trailing Stop
                # pos['high_water_mark'] might not exist for old legacy positions
                hwm = pos.get('high_water_mark', entry_price)
                if side == "BUY":
                    if current_price > hwm:
                        pos['high_water_mark'] = current_price
                        state_changed = True
                        logger.info(f"📈 HWM Updated: {pos['market_question'][:30]} -> ${current_price:.4f}")
                    pnl_pct = (current_price - entry_price) / entry_price
                else: # SELL (Short)
                    if current_price < hwm:
                        pos['high_water_mark'] = current_price
                        state_changed = True
                    pnl_pct = (entry_price - current_price) / entry_price
                
                # --- Phase 8: Intelligent Signal Fetching ---
                signal = None
                if self.signal_bus:
                    signal = await self.signal_bus.get_signal(token_id)
                should_close = False
                close_pct = 1.0 # Default: close 100%
                reason = ""
                
                # 1. Partial Take Profit (10% Gain -> Sell 50%)
                if pnl_pct >= 0.10 and not pos.get('partial_exit_hit'):
                    logger.info(f"💰 Partial TP Triggered: {pos['market_question'][:30]} (+{pnl_pct*100:.1f}%)")
                    should_close = True
                    close_pct = 0.5
                    reason = "Partial Take Profit (10%)"
                    pos['partial_exit_hit'] = True
                    state_changed = True

                # 2. Main Take Profit (25% Gain -> Exit Full)
                elif pnl_pct >= 0.25:
                    should_close = True
                    reason = f"Full Take Profit (+{pnl_pct*100:.1f}%)"
                
                # 2a. Phase 8: Sentiment-Driven Emergency Exit
                elif signal and signal.sentiment_score < -0.6:
                    should_close = True
                    reason = f"Emergency Sentiment Exit (Score: {signal.sentiment_score:.2f})"
                
                # 2b. Phase 8: Endgame Awareness Exit (< 15m to expiry)
                elif signal and signal.metadata.get('expiry', {}).get('phase') == 'ENDGAME':
                    should_close = True
                    reason = "Endgame Phase Exit (Liquidity Protection)"
                    
                # 3. Trailing Stop (Volatility-Adjusted in Phase 8)
                elif side == "BUY" and hwm > entry_price:
                    # Default 5.0%, but adapt to market regime
                    trail_pct_threshold = 0.05
                    if signal:
                        if signal.spread_regime == "EFFICIENT":
                            trail_pct_threshold = 0.025 # Tighten to lock gains
                        elif signal.spread_regime == "INEFFICIENT":
                            trail_pct_threshold = 0.075 # Give more room
                            
                    trail_pct = (hwm - current_price) / hwm
                    if trail_pct >= trail_pct_threshold:
                        should_close = True
                        reason = f"Volatility-Adjusted Trailing Stop ({trail_pct*100:.1f}% vs {trail_pct_threshold*100:.1f}%)"

                # 4. Traditional Stop Loss (-10%)
                elif pnl_pct <= -0.10:
                    should_close = True
                    reason = f"Hard Stop Loss ({pnl_pct*100:.1f}%)"
                    
                # 5. Time Limit (48h)
                elif datetime.now() - datetime.fromisoformat(pos['timestamp']) > timedelta(hours=48):
                    should_close = True
                    reason = "Time Limit (48h)"
                    
                if should_close:
                    logger.info(f"🔄 Executing Exit: {pos['market_question'][:30]} | Reason: {reason} | Amount: {close_pct*100:.0f}%")
                    
                    close_side = "SELL" if side == "BUY" else "BUY"
                    shares_to_close = pos['size'] * close_pct
                    
                    if not self.config.DRY_RUN:
                        close_amount_usd = shares_to_close * current_price
                        
                        # 🛡️ Dust Protection: Skip if value < Minimum
                        if close_amount_usd < self.client.min_order_value:
                            logger.warning(f"      ⚠️ Cannot Close: Value ${close_amount_usd:.2f} < ${self.client.min_order_value:.2f} min. Marking as 'Zombie' to ignore.")
                            pos['zombie'] = True
                            state_changed = True
                            continue

                        # --- Phase 8: Liquidity-Aware Execution Pre-check ---
                        try:
                            ob = await self.client.get_order_book(token_id)
                            # Check top 5 levels of depth
                            side_key = 'bids' if close_side == 'SELL' else 'asks'
                            top_depth = sum(float(level['size']) for level in ob.get(side_key, [])[:5])
                            
                            if shares_to_close > top_depth * 0.5 and top_depth > 0:
                                logger.warning(f"      ⚠️ High Slippage Risk: Position {shares_to_close:.1f} > 50% Top Depth {top_depth:.1f}")
                                # In a real bot, we might choose to split the order here. 
                                # For now, we proceed but log the warning.
                        except Exception as nle:
                            logger.debug(f"      Note: Could not fetch depth for liquidity analysis: {nle}")

                        resp = await self.client.place_limit_order_with_slippage_protection(
                            token_id=token_id,
                            side=close_side,
                            amount=close_amount_usd,
                            size=shares_to_close, # Explicitly pass shares
                            target_price=current_price
                        )
                        if resp:
                            logger.info(f"      ✅ Part/Full Closed: {reason}")
                            if close_pct >= 1.0:
                                closed_ids.append(token_id)
                            else:
                                pos['size'] -= shares_to_close
                                state_changed = True
                    else:
                        logger.info(f"      📝 [DRY RUN] Would Close {close_pct*100:.0f}%: {reason}")
                        if close_pct >= 1.0:
                            closed_ids.append(token_id)
                            if self.pnl_tracker and pos.get('pnl_tid'):
                                self.pnl_tracker.record_exit(pos['pnl_tid'], current_price, reason=reason)
                        else:
                            pos['size'] -= shares_to_close
                            state_changed = True
                            
            except Exception as e:
                logger.error(f"Error managing position {token_id}: {e}")
                
        # Remove closed positions
        for tid in closed_ids:
            self.active_positions.pop(tid, None)
            state_changed = True
            
        if state_changed:
            self._save_state()

    async def _sync_with_account(self):
        """Sync local state with actual Polymarket account positions"""
        logger.info("🔄 Syncing positions with Polymarket account...")
        try:
            live_positions = await self.client.get_all_positions()
            if not live_positions:
                logger.info("   No active positions found in account.")
                return

            # live_positions is usually a list of dicts with 'asset', 'conditionId'
            for lp in live_positions:
                token_id = lp.get('asset') or lp.get('conditionId') or lp.get('asset_id')
                size = float(lp.get('size', 0))
                
                if size <= 0.01 or not token_id: continue # Dust or invalid
                
                if token_id not in self.active_positions:
                    logger.info(f"   ✨ Found untracked position: {str(token_id)[:15]}... (Size: {size})")
                    # Try to fetch market info for better tracking
                    market = await self.client.get_market_cached(token_id)
                    
                    self.active_positions[token_id] = {
                        'entry_price': float(lp.get('avgPrice', 0.5)),
                        'size': size,
                        'market_question': market.get('question', 'Existing Position') if market else lp.get('title', 'Untracked Position'),
                        'condition_id': market.get('condition_id') or lp.get('conditionId') if market else lp.get('conditionId'),
                        'timestamp': datetime.now().isoformat(),
                        'side': 'BUY',
                        'strategy': 'sync',
                        'high_water_mark': float(lp.get('avgPrice', 0.5))
                    }
                    if self.pnl_tracker:
                        meta = {"group": getattr(self, 'category', 'DEFAULT').upper()}
                        tid = self.pnl_tracker.record_existing_trade(
                            "trend_follower", 
                            token_id, 
                            "BUY", 
                            float(lp.get('avgPrice', 0.5)), 
                            size,
                            metadata=meta
                        )
                        self.active_positions[token_id]['pnl_tid'] = tid
            
            self._save_state()
            logger.info(f"   Sync complete. Tracking {len(self.active_positions)} positions.")
            
        except Exception as e:
            logger.error(f"Failed to sync positions: {e}")

    def _save_state(self):
        """Save active positions to disk and sync to dashboard"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.active_positions, f, indent=2)
            logger.debug("💾 Strategy state saved.")
            
            # Sync to dashboard for Telegram visibility
            if self.status_reporter:
                dashboard_positions = [
                    {
                        'symbol': pos.get('market_question', 'Unknown')[:30],
                        'size': pos.get('size', 0),
                        'entry': pos.get('entry_price', 0),
                        'current': pos.get('high_water_mark', pos.get('entry_price', 0)),
                        'pnl': (pos.get('high_water_mark', pos.get('entry_price', 0)) - pos.get('entry_price', 0)) / pos.get('entry_price', 1) * 100 if pos.get('entry_price') else 0,
                        'strategy': pos.get('strategy', 'trend')
                    }
                    for pos in self.active_positions.values()
                ]
                self.status_reporter.update_active_positions(dashboard_positions)
                
                # Also update PnL (approximate from positions)
                total_value = sum(p.get('size', 0) * p.get('entry_price', 0) for p in self.active_positions.values())
                self.status_reporter.update_metrics(balance=total_value, pnl=0.0)
                
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def _load_state(self) -> Dict:
        """Load active positions from disk"""
        if not os.path.exists(self.state_file):
            return {}
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                return state
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return {}

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
                # current_price_str = await self.client.get_price(token_id)
                # Fix: Use get_best_bid (returns (price, size))
                bid_price, _ = self.client.get_best_bid(token_id)
                current_price_str = bid_price
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
        
        # 1. Broaden Search (Dedicated 15m Filter + General Trends)
        scalp_markets = await self.crypto_filter.get_active_crypto_15min_markets(self.gamma, limit=20)
        
        # Also fetch top active markets by volume for general trends that might be scalped
        general_markets = await self.gamma.get_active_markets(limit=40, volume_min=self.min_volume)
        
        # Combine and deduplicate
        seen_ids = {m.get('id') for m in scalp_markets}
        active_markets = list(scalp_markets)
        
        for m in general_markets:
            if m.get('id') not in seen_ids:
                active_markets.append(m)
        
        logger.info(f"   ⚡ Found {len(active_markets)} potential scalp markets (including 15m specialists)")
        
        for market in active_markets:
            logger.debug(f"   👉 Checking candidate: {market.get('question')[:40]}...")
            condition_id = market.get('condition_id') or market.get('conditionId')
            logger.debug(f"      🆔 Condition ID: {condition_id}")
            if not condition_id:
                logger.warning(f"      ❌ Missing condition_id for {market.get('question')[:20]}")
                continue
                
            if self._is_cooldown(condition_id):
                logger.info(f"      ❄️ Cooldown active for {market.get('question')[:20]}...")
                continue
                
            # Get Yes Token ID
            token_id = self._get_yes_token(market)
            logger.debug(f"      🔑 Token ID: {token_id}")
            if not token_id: 
                logger.warning(f"      ⚠️ No 'Yes' token found for {market.get('question')[:30]}")
                continue
            
            # 2. Check Price Momentum (Last 30 mins)
            try:
                # Use History API to get recent price points
                logger.debug(f"      ⏳ Fetching history for {token_id}...")
                history, source = await self.history_api.get_history_with_source(
                    condition_id=condition_id, 
                    days=1, 
                    min_points=5,
                    market_data=market
                )
                logger.debug(f"      📊 History fetched: {len(history)} points")
                
                if len(history) < 5:
                    logger.info(f"      📉 Insufficient history for {market.get('question')[:20]} ({len(history)} points)")
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
                
                # Scalp Signal: Strong Breakout (>1% move recently)
                if momentum > 0.01 and 0.02 < current_price < 0.85: 
                     logger.info(f"   🚀 SCALP SIGNAL: {market.get('question')} | Mom: {momentum*100:.1f}%")
                     
                     # Check Budget
                     if self.config.DRY_RUN:
                         logger.info(f"      📝 [DRY RUN] Would SCALP BUY $5 on {token_id}")
                         # Record mock position for PnL tracking
                         self.active_positions[token_id] = {
                            'entry_price': current_price,
                            'size': 5.0 / (current_price or 0.5), 
                            'market_question': market.get('question'),
                            'condition_id': condition_id,
                            'timestamp': datetime.now().isoformat(),
                            'side': 'BUY',
                            'strategy': 'scalp',
                            'high_water_mark': current_price
                         }
                         self._save_state()
                         continue

                     # Execute Scalp
                     # Use aggressive limit (target = current * 1.01)
                     target_price = round(current_price * 1.01, 3)
                     
                     await self.client.place_limit_order_with_slippage_protection(
                         token_id=token_id,
                         side="BUY",
                         amount=self.client.min_order_value, # Automatically matches config
                         priority="high",
                         max_slippage_pct=3.0, # Low liquidity tolerance
                         target_price=target_price
                     )
                     
                     # Record position with aggressive take profit
                     self.active_positions[token_id] = {
                        'entry_price': current_price,
                        'size': 5.0 / current_price, # shares estimated
                        'market_question': market.get('question'),
                        'condition_id': condition_id,
                        'timestamp': datetime.now().isoformat(),
                        'side': 'BUY',
                        'strategy': 'scalp',
                        'high_water_mark': current_price
                    }
                     self._save_state()
                     
                     # Cooldown
                     self.cooldowns[condition_id] = datetime.now()
                else:
                    logger.info(f"      🚫 Rejected scalp: {market.get('question')[:30]} | Mom: {momentum*100:.2f}% (req >1.0%), Price: {current_price} (req <0.85)")
                     
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
                        "timestamp": datetime.now().isoformat(),
                        "target_price": float(impact.suggested_price),
                        "high_water_mark": float(resp.get('price'))
                    }
                    self._save_state()
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
                "timestamp": datetime.now().isoformat(),
                "target_price": float(impact.suggested_price),
                "high_water_mark": float(impact.current_price)
            }
            self._save_state()

    def _extract_keywords(self, question: str) -> List[str]:
        """Simple keyword extractor"""
        ignore = {'will', 'the', 'be', 'of', 'in', 'at', 'on', 'to', 'a', 'before', 'after'}
        words = [w.strip("?.,") for w in question.lower().split()]
        return [w for w in words if w not in ignore and len(w) > 3][:3]

    def _get_yes_token(self, market: dict) -> Optional[str]:
        """
        Robustly identify the 'Yes' token ID.
        """
        clob_ids = market.get('clobTokenIds')
        tokens = market.get('tokens')
        
        if clob_ids and tokens and len(clob_ids) == len(tokens):
             for i, token in enumerate(tokens):
                outcome = token.get('outcome', '').strip().upper()
                if outcome == 'YES':
                    return clob_ids[i]
        
        # 2. Fallback: Binary Market Assumption (Index 0 = YES)
        # Gamma markets sometimes lack 'tokens' but have 'clobTokenIds'
        if clob_ids:
             # Handle if it came as string
             if isinstance(clob_ids, str):
                 try:
                     import json
                     c_ids = json.loads(clob_ids)
                 except: c_ids = []
             else:
                 c_ids = clob_ids
                 
             if isinstance(c_ids, list) and len(c_ids) == 2:
                 # Heuristic: For binary markets, Yes/Long is usually index 0
                 return c_ids[0]
                 
        return None


    def _is_cooldown(self, condition_id: str) -> bool:
        if condition_id in self.cooldowns:
            if datetime.now() < self.cooldowns[condition_id]:
                return True
        return False
        
    def _set_cooldown(self, condition_id: str):
        self.cooldowns[condition_id] = datetime.now() + self.cooldown_duration

    async def shutdown(self):
        """Gracefully close all internal client sessions"""
        logger.info("🎬 Shutting down SmartTrendFollower...")
        self.is_running = False
        try:
            if hasattr(self, 'gamma') and self.gamma:
                await self.gamma.close()
            if hasattr(self, 'news_aggregator') and self.news_aggregator:
                await self.news_aggregator.close()
            if hasattr(self, 'rag') and self.rag:
                await self.rag.close()
            if hasattr(self, 'history_api') and self.history_api:
                await self.history_api.close()
            logger.info("✅ SmartTrendFollower resources closed")
        except Exception as e:
            logger.error(f"Error during SmartTrendFollower shutdown: {e}")
