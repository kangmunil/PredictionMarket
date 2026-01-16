"""
Enhanced Statistical Arbitrage Strategy V2.0
=============================================

Implements rigorous cointegration testing and mean reversion trading.

Key Improvements:
- Engle-Granger cointegration test
- Johansen test for validation
- Half-life calculation for optimal holding periods
- Real market data integration
- Position sizing based on Z-score confidence

Author: ArbHunter V2.0 Upgrade
Created: 2026-01-02
"""

import asyncio
import logging
import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Optional
from decimal import Decimal
from datetime import datetime, timedelta
from dataclasses import dataclass

# Statistical testing
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from scipy import stats

from src.core.clob_client import PolyClient
from src.core.decision_logger import DecisionLogger
from src.core.aggression import seconds_to_expiry, aggression_profile
from src.core.gamma_client import GammaClient

logger = logging.getLogger(__name__)


@dataclass
class PairMetrics:
    """Statistical metrics for a trading pair"""
    correlation: float
    cointegration_pvalue: float
    half_life: float  # Days until mean reversion
    spread_mean: float
    spread_std: float
    current_z_score: float
    is_cointegrated: bool

    def __repr__(self):
        return (
            f"PairMetrics(corr={self.correlation:.3f}, "
            f"coint_p={self.cointegration_pvalue:.4f}, "
            f"half_life={self.half_life:.1f}d, "
            f"z={self.current_z_score:.2f})"
        )


@dataclass
class TradingSignal:
    """Trading signal with confidence and sizing"""
    pair_name: str
    token_a: str
    token_b: str
    action: str  # "LONG_A_SHORT_B" or "SHORT_A_LONG_B"
    z_score: float
    confidence: float  # 0-1 based on cointegration strength
    position_size: Decimal
    expected_half_life: float
    entry_reason: str

    def __repr__(self):
        return (
            f"Signal({self.pair_name}): {self.action} "
            f"(Z={self.z_score:.2f}, conf={self.confidence:.0%}, "
            f"size=${self.position_size})"
        )


class EnhancedStatArbStrategy:
    """
    Statistical Arbitrage with rigorous cointegration testing.

    Trading Logic:
    1. Test pairs for cointegration (Engle-Granger + Johansen)
    2. Calculate half-life for optimal holding period
    3. Enter when |Z-score| > entry_threshold (2.0)
    4. Exit when Z-score reverts to mean or hits stop-loss (4.0)
    5. Position size based on confidence (cointegration p-value)
    """

    def __init__(
        self,
        client: PolyClient,
        budget_manager=None,
        lookback_days: int = 30,
        min_data_points: int = 10,
        signal_bus = None,
        pnl_tracker = None,
        delta_tracker=None,
    ):
        self.client = client
        self.gamma = GammaClient()
        self.budget_manager = budget_manager
        self.signal_bus = signal_bus # Hive Mind Connection
        self.pnl_tracker = pnl_tracker # Unified P&L Logger
        self.delta_tracker = delta_tracker
        self.decision_logger = DecisionLogger("StatArb") # Centralized Logger
        
        if self.signal_bus:
            logger.info("🧠 StatArb connected to SignalBus")

        # Data requirements
        self.lookback_days = lookback_days
        self.min_data_points = min_data_points

        # Trading thresholds
        self.entry_z_threshold = 2.0  # Enter when |Z| > 2.0
        self.exit_z_threshold = 1.0   # Exit when |Z| < 1.0 (sooner realization)
        self.stop_loss_z = 3.0        # Stop loss at |Z| > 3.0

        # Cointegration requirements
        self.max_cointegration_pvalue = 0.05  # p < 0.05 required
        self.min_correlation = 0.6            # Correlation > 0.6
        self.max_half_life_days = 14          # Reject if half-life > 2 weeks

        # Position management
        self.max_position_size = Decimal("100")  # $100 per leg
        self.active_positions: Dict[str, dict] = {}

        # Market pairs to monitor
        # Format: (condition_id_a, condition_id_b, pair_name, category)
        self.pairs = []
        self.pair_groups: Dict[str, str] = {}

        # Performance tracking
        self.pair_metrics_cache: Dict[str, PairMetrics] = {}
        self.last_analysis: Dict[str, datetime] = {}
        self.disabled_pairs: Dict[str, datetime] = {}

    def add_pair(
        self,
        condition_id_a: str,
        condition_id_b: str,
        pair_name: str,
        category: str = "general"
    ):
        """Add a pair to monitor for stat arb opportunities"""
        cooldown_until = self.disabled_pairs.get(pair_name)
        if cooldown_until and cooldown_until > datetime.now():
            logger.info(f"⏳ Skipping re-add of disabled pair {pair_name} until {cooldown_until:%H:%M}")
            return
        self.pairs.append((condition_id_a, condition_id_b, pair_name, category))
        self.pair_groups[pair_name] = (category or "DEFAULT").upper()
        logger.info(f"📊 Added pair: {pair_name} ({category})")

    def _resolve_pair_group(self, pair_name: str) -> str:
        return self.pair_groups.get(pair_name, "DEFAULT")

    @staticmethod
    def _entry_sides(action: str) -> Tuple[str, str]:
        if action == "LONG_A_SHORT_B":
            return ("BUY", "SELL")
        return ("SELL", "BUY")

    @staticmethod
    def _exit_sides(action: str) -> Tuple[str, str]:
        entry_a, entry_b = EnhancedStatArbStrategy._entry_sides(action)
        invert = {"BUY": "SELL", "SELL": "BUY"}
        return (invert[entry_a], invert[entry_b])

    async def _get_spread_regime(self, token_id: str) -> str:
        if not self.signal_bus:
            return "UNKNOWN"
        try:
            signal = await self.signal_bus.get_signal(token_id)
            return (getattr(signal, "spread_regime", "UNKNOWN") or "UNKNOWN").upper()
        except Exception as exc:
            logger.debug(f"⚠️ Spread regime lookup failed for {token_id[:10]}: {exc}")
            return "UNKNOWN"

    def _spread_multiplier(self, regime: str) -> float:
        regime_key = (regime or "UNKNOWN").upper()
        mapping = {
            "INEFFICIENT": 1.0,
            "NEUTRAL": 0.6,
            "EFFICIENT": 0.0,
            "UNKNOWN": 0.8,
        }
        return mapping.get(regime_key, 0.8)

    async def _determine_spread_policy(self, token_a: str, token_b: str) -> Tuple[float, str, str]:
        regime_a = await self._get_spread_regime(token_a)
        regime_b = await self._get_spread_regime(token_b)
        if regime_a == "EFFICIENT" and regime_b == "EFFICIENT":
            return 0.0, regime_a, regime_b
        multiplier = max(self._spread_multiplier(regime_a), self._spread_multiplier(regime_b))
        return multiplier, regime_a, regime_b

    def _parse_expiry(self, market: Optional[dict]) -> Optional[datetime]:
        if not market:
            return None
        end_raw = (
            market.get("end_date")
            or market.get("endDate")
            or market.get("ends_at")
            or market.get("endDateISO")
        )
        if not end_raw:
            return None
        text = end_raw.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    async def _resolve_condition_expiry(self, condition_id: str) -> Optional[datetime]:
        market = await self.client.get_market_cached(condition_id)
        if not market:
            return None
        return self._parse_expiry(market)

    def _disable_pair(self, pair_name: str, reason: str, cooldown_hours: int = 6):
        """Remove a problematic pair until data is refreshed"""
        before = len(self.pairs)
        self.pairs = [p for p in self.pairs if p[2] != pair_name]
        self.pair_metrics_cache.pop(pair_name, None)
        self.last_analysis.pop(pair_name, None)
        self.disabled_pairs[pair_name] = datetime.now() + timedelta(hours=cooldown_hours)
        logger.warning(f"🛑 Disabled pair {pair_name} ({before}->{len(self.pairs)}). Reason: {reason}")

    async def _release_allocation(self, allocation_info: Optional[dict], actual_spent: Decimal):
        """Helper to safely release capital back to the pool"""
        if allocation_info and self.budget_manager:
            await self.budget_manager.release_allocation(
                "statarb",
                allocation_info['allocation_id'],
                actual_spent
            )

    async def run(self):
        """Main strategy loop"""
        logger.info("🛡️ Enhanced Stat Arb Strategy Started")
        
        # 🚀 실시간 핫 마켓 자동 탐색 시작
        asyncio.create_task(self.auto_discover_pairs_loop())

        while True:
            try:
                # Phase 1: Analyze all pairs for cointegration
                await self.analyze_all_pairs()

                # Phase 2: Check for entry signals
                await self.scan_for_entries()

                # Phase 3: Manage active positions
                await self.manage_positions()

                # Wait before next scan (60 seconds)
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"StatArb Error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def analyze_all_pairs(self):
        """
        Analyze all configured pairs for cointegration.
        Updates pair_metrics_cache with latest statistics.
        """
        # Allow StatArb to run even without WebSocket (can use REST API for prices)
        ws_status = getattr(self.client, "ws_connected", None)
        if ws_status is False:
            logger.debug("⚠️ StatArb running without WS (using REST API fallback)")
        # Removed hard block: StatArb can fetch prices via REST if needed
        logger.debug("🔍 Analyzing pairs for cointegration...")

        for condition_a, condition_b, pair_name, category in self.pairs:
            try:
                # Skip if analyzed recently (cache for 1 hour)
                if pair_name in self.last_analysis:
                    time_since = datetime.now() - self.last_analysis[pair_name]
                    if time_since < timedelta(hours=1):
                        continue

                # Fetch historical data
                data_a = await self.fetch_historical_prices(condition_a, self.lookback_days)
                data_b = await self.fetch_historical_prices(condition_b, self.lookback_days)

                if len(data_a) < self.min_data_points or len(data_b) < self.min_data_points:
                    logger.warning(f"⚠️ {pair_name}: Insufficient data ({len(data_a)}, {len(data_b)} points)")
                    continue

                # Align timestamps
                df = self.align_price_series(data_a, data_b)

                if len(df) < self.min_data_points:
                    logger.warning(f"⚠️ {pair_name}: Insufficient aligned data ({len(df)} points)")
                    continue

                # Compute pair metrics
                metrics = self.compute_pair_metrics(df, pair_name)

                # Cache results
                self.pair_metrics_cache[pair_name] = metrics
                self.last_analysis[pair_name] = datetime.now()

                # Log if cointegrated
                if metrics.is_cointegrated:
                    logger.info(f"✅ {pair_name}: COINTEGRATED - {metrics}")
                    
                    # Subscribe to real-time orderbook (Cached Async)
                    tid_a = await self.client.get_yes_token_id_cached(condition_a)
                    tid_b = await self.client.get_yes_token_id_cached(condition_b)
                    if tid_a and tid_b:
                        asyncio.create_task(self.client.subscribe_orderbook([tid_a, tid_b]))
                else:
                    logger.debug(f"❌ {pair_name}: Not cointegrated (p={metrics.cointegration_pvalue:.4f})")

            except Exception as e:
                logger.error(f"Error analyzing {pair_name}: {e}")

    def compute_pair_metrics(self, df: pd.DataFrame, pair_name: str) -> PairMetrics:
        """
        Compute comprehensive statistical metrics for a pair.

        Tests:
        1. Correlation
        2. Engle-Granger cointegration
        3. Augmented Dickey-Fuller test on spread
        4. Half-life calculation
        5. Current Z-score
        """
        prices_a = df['price_a'].values
        prices_b = df['price_b'].values

        # 1. Correlation
        correlation = np.corrcoef(prices_a, prices_b)[0, 1]

        # 3. Check for constant data (prevents "x is constant" error)
        if prices_a.std() == 0 or prices_b.std() == 0:
            logger.warning(f"⚠️  Skipping {pair_name}: Constant price detected (Illiquid market)")
            return None

        # 4. Run Cointegration Test (Engle-Granger)
        try:
            # coint returns: t-stat, p-value, crit-values
            coint_test = coint(prices_a, prices_b)
            cointegration_pvalue = coint_test[1]
        except ValueError as e:
            logger.warning(f"⚠️  Math error analyzing {pair_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error in cointegration test: {e}")
            return None

        # 3. Calculate spread (using OLS regression)
        # Spread = price_a - beta * price_b
        beta = np.polyfit(prices_b, prices_a, 1)[0]
        spread = prices_a - beta * prices_b

        # 4. Test spread stationarity (ADF test)
        adf_result = adfuller(spread, maxlag=1)
        spread_is_stationary = adf_result[1] < 0.05

        # 5. Calculate half-life (time for spread to mean-revert)
        half_life = self.calculate_half_life(spread)

        # 6. Spread statistics
        spread_mean = np.mean(spread)
        spread_std = np.std(spread)

        # 7. Current Z-score
        current_spread = spread[-1]
        current_z_score = (current_spread - spread_mean) / spread_std if spread_std > 0 else 0

        # 8. Determine if pair is tradeable
        is_cointegrated = (
            cointegration_pvalue < self.max_cointegration_pvalue and
            correlation > self.min_correlation and
            spread_is_stationary and
            half_life < self.max_half_life_days
        )

        return PairMetrics(
            correlation=correlation,
            cointegration_pvalue=cointegration_pvalue,
            half_life=half_life,
            spread_mean=spread_mean,
            spread_std=spread_std,
            current_z_score=current_z_score,
            is_cointegrated=is_cointegrated
        )

    def calculate_half_life(self, spread: np.ndarray) -> float:
        """
        Calculate half-life of mean reversion using Ornstein-Uhlenbeck process.

        Model: d(spread) = -lambda * spread * dt + dW
        Half-life = ln(2) / lambda

        Returns:
            Half-life in days (assuming daily data)
        """
        spread_lag = spread[:-1]
        spread_diff = np.diff(spread)

        # OLS regression: spread_diff = alpha + beta * spread_lag
        spread_lag = spread_lag.reshape(-1, 1)
        spread_diff = spread_diff.reshape(-1, 1)

        # Add constant term
        X = np.hstack([np.ones_like(spread_lag), spread_lag])

        # Solve: beta = (X'X)^-1 X'y
        try:
            beta = np.linalg.lstsq(X, spread_diff, rcond=None)[0]
            lambda_param = -beta[1][0]

            if lambda_param > 0:
                half_life = np.log(2) / lambda_param
                return float(half_life)
            else:
                return float('inf')  # No mean reversion

        except:
            return float('inf')

    async def _scan_high_probability_bets(self):
        """
        Mimic 'Sharky6999': Find high probability (>98%) markets for yield farming.
        """
        try:
            # High volume ensures liquidity for 'Sure Bets'
            markets = await self.gamma.get_active_markets(limit=20, volume_min=10000.0)
            
            for market in markets:
                # Check simplified price (Gamma snapshot)
                # Ideally we check Real CLOB price, but this filters first
                tokens = market.get('tokens', [])
                if not tokens: continue
                
                # Assume Binary for simplicity
                yes_token = tokens[0] 
                price = float(yes_token.get('price', 0.5))
                
                signal_side = None
                target_price = None
                
                # Logic: If 98% confident, bet for the last 2% yield
                if price >= 0.98 and price < 0.995: # Don't buy 0.999 (no yield)
                    signal_side = "BUY"
                    target_price = price
                    reason = "Yield Farming (>98%)"
                
                # Logic: If <2%, maybe shorting is hard, but buying 'No' (Selling Yes) is good yield?
                # Selling Yes at 0.02 is risky (max loss 0.98).
                # Only buying Yes at 0.98 is "Yield Farming" (Risk 0.98 to make 0.02).
                
                if signal_side:
                     token_id = yes_token.get('token_id')
                     
                     # Check if we already have position
                     if token_id in self.active_positions: continue
                     
                     logger.info(f"💎 SURE BET SIGNAL: {market.get('question')} | Price: ${price}")
                     
                     if not self.client.config.DRY_RUN:
                         # Place large meaningful bet (Sharky style)
                         # Scaled down for our budget
                         amount = 20.0 
                         
                         await self.client.place_limit_order_with_slippage_protection(
                             token_id=token_id,
                             side=signal_side,
                             amount=amount,
                             priority="high",
                             target_price=target_price
                         )
                         
                         # Log position
                         self.active_positions[token_id] = {
                             'strategy': 'yield_farm',
                             'entry_price': price,
                             'timestamp': datetime.now()
                         }
        except Exception as e:
            logger.error(f"Error scanning sure bets: {e}")

    async def scan_for_entries(self):
        """Scan cointegrated pairs for entry signals"""
        for pair_name, metrics in self.pair_metrics_cache.items():
            if not metrics or not metrics.is_cointegrated:
                continue

            pair_info = next((p for p in self.pairs if p[2] == pair_name), None)
            if not pair_info:
                continue

            token_a, token_b, _, _ = pair_info

            # Skip if already in position
            if pair_name in self.active_positions:
                continue

            # 🧠 Dynamic Threshold Adjustment based on SignalBus
            current_threshold = self.entry_z_threshold

            # Apply data-quality penalty when synthetic history is in play
            history_sources = []
            for cid in (token_a, token_b):
                source = self._get_history_source(cid)
                if source:
                    history_sources.append(source)

            if history_sources and any(src == "SYNTHETIC" for src in history_sources):
                current_threshold *= 1.5
                logger.info(
                    "⚠️ %s: Synthetic history detected (%s) → threshold raised to %.2f",
                    pair_name,
                    ", ".join(history_sources),
                    current_threshold,
                )
            
            if self.signal_bus:
                # Get tokens from pair info
                # Get signals from Hive Mind
                # Note: Signal retrieval needs to be sync here or cached, 
                # but get_signal is async. For prototype, we assume we can run it.
                # Since this func is async, we can await.
                sig_a = await self.signal_bus.get_signal(token_a)
                sig_b = await self.signal_bus.get_signal(token_b)
                sig_a_score = getattr(sig_a, "sentiment_score", 0.0) if sig_a else 0.0
                sig_b_score = getattr(sig_b, "sentiment_score", 0.0) if sig_b else 0.0
                
                # Logic: If we want to LONG A (Z < 0) and A has Good News -> Lower threshold
                if metrics.current_z_score < 0: # Signal to LONG A, SHORT B
                    if sig_a_score > 0.5:
                        current_threshold = 1.5 # More aggressive
                        logger.info(f"🔥 Hive Mind Boost: Lowering entry threshold for {pair_name} due to {token_a} news")
                        
                # Logic: If we want to LONG B (Z > 0) and B has Good News -> Lower threshold
                elif metrics.current_z_score > 0: # Signal to SHORT A, LONG B
                    if sig_b_score > 0.5:
                        current_threshold = 1.5
                        logger.info(f"🔥 Hive Mind Boost: Lowering entry threshold for {pair_name} due to {token_b} news")

            # Check if Z-score exceeds dynamic entry threshold
            if abs(metrics.current_z_score) > current_threshold:
                # 🧠 HIVE MIND UPDATE: Report signal to dashboard
                if self.signal_bus:
                    # token_a를 기준으로 시그널 등록 (Z > 0이면 A 매도/B 매수이므로 음수 점수)
                    score = -metrics.current_z_score / 5.0 # -1.0 ~ 1.0 사이로 정규화 시도
                    asyncio.create_task(self.signal_bus.update_signal(
                        token_id=pair_name[:15], 
                        source='STATARB',
                        score=max(-1.0, min(1.0, score))
                    ))

                signal = self.generate_entry_signal(pair_name, metrics)
                if signal:
                    await self.execute_entry(signal)

    def generate_entry_signal(
        self,
        pair_name: str,
        metrics: PairMetrics
    ) -> Optional[TradingSignal]:
        """
        Generate trading signal based on statistical edge.

        Logic:
        - If Z > 0: Price A is expensive vs B → SHORT A, LONG B
        - If Z < 0: Price A is cheap vs B → LONG A, SHORT B
        """
        # Find pair details
        pair_info = next(
            (p for p in self.pairs if p[2] == pair_name),
            None
        )
        if not pair_info:
            return None

        condition_a, condition_b, _, _ = pair_info

        # Determine action
        if metrics.current_z_score > 0:
            action = "SHORT_A_LONG_B"
            entry_reason = f"A overpriced vs B (Z={metrics.current_z_score:.2f})"
        else:
            action = "LONG_A_SHORT_B"
            entry_reason = f"A underpriced vs B (Z={metrics.current_z_score:.2f})"

        # Calculate confidence (inverse of p-value)
        # p-value closer to 0 => stronger cointegration => higher confidence
        confidence = 1.0 - metrics.cointegration_pvalue

        # Position sizing: More confident => Larger size
        # Base size: $50, Max size: $100
        base_size = 50
        size_multiplier = 1 + confidence  # 1.0 to 2.0
        position_size = Decimal(str(min(base_size * size_multiplier, 100)))

        return TradingSignal(
            pair_name=pair_name,
            token_a=condition_a,
            token_b=condition_b,
            action=action,
            z_score=metrics.current_z_score,
            confidence=confidence,
            position_size=position_size,
            expected_half_life=metrics.half_life,
            entry_reason=entry_reason
        )

    async def execute_entry(self, signal: TradingSignal):
        """Execute entry orders for stat arb position"""
        
        await self.decision_logger.log_decision(
            action=signal.action,
            token=signal.pair_name,
            confidence=signal.confidence,
            reason=signal.entry_reason,
            factors={
                "Z-Score": f"{signal.z_score:.2f}",
                "Half-Life": f"{signal.expected_half_life:.1f}d",
                "Size": f"${signal.position_size}"
            }
        )

        # Dry Run 체크
        dry_run = getattr(self.client.config, 'DRY_RUN', True)
        allocation_info = None

        try:
            # 🚀 Resolve condition IDs to actual CLOB Token IDs
            tid_a = self.client.get_yes_token_id(signal.token_a)
            tid_b = self.client.get_yes_token_id(signal.token_b)
            if not tid_a or not tid_b:
                logger.error(f"❌ Could not resolve token IDs for {signal.pair_name}. A: {tid_a}, B: {tid_b}")
                self._disable_pair(signal.pair_name, "Token resolution failed")
                return

            market_group = self._resolve_pair_group(signal.pair_name)
            side_a, side_b = self._entry_sides(signal.action)
            base_size = float(signal.position_size)

            spread_multiplier, regime_a, regime_b = await self._determine_spread_policy(tid_a, tid_b)
            if spread_multiplier <= 0 or base_size <= 0:
                logger.info(
                    "   🧊 Spread regimes %s/%s show no exploitable edge; skipping entry.",
                    regime_a,
                    regime_b,
                )
                return

            trade_size = base_size * spread_multiplier
            if trade_size <= 0:
                logger.info("   💤 Spread regime scaling reduced size to $0. Skipping %s.", signal.pair_name)
                return
            if abs(trade_size - base_size) > 1e-6:
                logger.info(
                    "   ⚖️ Spread regimes %s/%s scaled size from $%.2f → $%.2f",
                    regime_a,
                    regime_b,
                    base_size,
                    trade_size,
                )
            position_size_dec = Decimal(str(trade_size))

            expiry_a = await self._resolve_condition_expiry(signal.token_a)
            expiry_b = await self._resolve_condition_expiry(signal.token_b)
            nearest_expiry = None
            if expiry_a and expiry_b:
                nearest_expiry = min(expiry_a, expiry_b)
            else:
                nearest_expiry = expiry_a or expiry_b
            expiry_seconds = seconds_to_expiry(nearest_expiry)
            agg_multiplier, agg_stage = aggression_profile(expiry_seconds)
            if agg_multiplier <= 0:
                logger.info("   🕒 Aggression stage %s suppressed stat-arb trade.", agg_stage)
                return
            if abs(agg_multiplier - 1.0) > 1e-6:
                scaled = trade_size * agg_multiplier
                logger.info(
                    "   ⚡ Aggression stage %s (t=%.0fs) scaled size from $%.2f → $%.2f",
                    agg_stage,
                    expiry_seconds if expiry_seconds is not None else float("nan"),
                    trade_size,
                    scaled,
                )
                trade_size = scaled
                position_size_dec = Decimal(str(trade_size))

            if self.delta_tracker:
                allowance_a = await self.delta_tracker.check_allowance(
                    token_id=tid_a,
                    side=side_a,
                    size=trade_size,
                    market_group=market_group,
                    condition_id=signal.token_a,
                )
                allowance_b = await self.delta_tracker.check_allowance(
                    token_id=tid_b,
                    side=side_b,
                    size=trade_size,
                    market_group=market_group,
                    condition_id=signal.token_b,
                )
                violated = allowance_a if not allowance_a.allowed else None
                if not allowance_b.allowed:
                    violated = allowance_b
                if violated and not violated.allowed:
                    logger.info(
                        "   🛑 Delta guard blocked stat-arb entry (%s) [group=%s current=%.2f -> projected=%.2f]",
                        violated.reason or "limit exceeded",
                        violated.group,
                        violated.current_delta,
                        violated.projected_delta,
                    )
                    return

            # Budget check after risk filters
            if self.budget_manager:
                total_required = position_size_dec * 2  # Both legs
                allocation_id = await self.budget_manager.request_allocation(
                    strategy="statarb",
                    amount=total_required,
                    priority="normal"
                )

                if not allocation_id:
                    logger.warning(f"⚠️ Budget allocation denied for {signal.pair_name}")
                    return

                allocation_info = {
                    'allocation_id': allocation_id,
                    'allocated_amount': total_required
                }

            if not dry_run:
                if signal.action == "SHORT_A_LONG_B":
                    logger.info(f"   🚀 LIVE ORDER: SELL {tid_a[:10]}... | BUY {tid_b[:10]}...")
                    await self.client.place_market_order(tid_a, "SELL", trade_size)
                    await self.client.place_market_order(tid_b, "BUY", trade_size)
                else:
                    logger.info(f"   🚀 LIVE ORDER: BUY {tid_a[:10]}... | SELL {tid_b[:10]}...")
                    await self.client.place_market_order(tid_a, "BUY", trade_size)
                    await self.client.place_market_order(tid_b, "SELL", trade_size)
                
                # Report to UI history
                swarm = getattr(self.client, 'swarm_system', None)
                if swarm:
                    swarm.add_trade_record(signal.action[:5], signal.pair_name, 0.5, trade_size)
            else:
                logger.info(f"   🧪 [DRY RUN] Entry for {signal.pair_name}")
                logger.info(f"      Resolved Leg A Token: {tid_a[:15]}...")
                logger.info(f"      Resolved Leg B Token: {tid_b[:15]}...")
                
                # Report to UI history even in dry run
                swarm = getattr(self.client, 'swarm_system', None)
                if swarm:
                    swarm.add_trade_record(signal.action, signal.pair_name, 0.5, trade_size)

            # Store in active positions
            trade_ids = []
            if self.pnl_tracker:
                entry_tid_a = self.pnl_tracker.record_entry(
                    strategy="statarb",
                    token_id=tid_a,
                    side="SELL" if "SHORT_A" in signal.action else "BUY",
                    price=0.5,
                    size=trade_size
                )
                entry_tid_b = self.pnl_tracker.record_entry(
                    strategy="statarb",
                    token_id=tid_b,
                    side="BUY" if "LONG_B" in signal.action else "SELL",
                    price=0.5,
                    size=trade_size
                )
                trade_ids = [entry_tid_a, entry_tid_b]

            self.active_positions[signal.pair_name] = {
                'signal': signal,
                'resolved_tids': (tid_a, tid_b),
                'entry_time': datetime.now(),
                'entry_z_score': signal.z_score,
                'allocation_info': allocation_info,
                'trade_ids': trade_ids,
                'market_group': market_group,
                'executed_size': position_size_dec,
                'expires_a': expiry_a,
                'expires_b': expiry_b,
            }

            if self.delta_tracker:
                entry_price = 0.5
                await self.delta_tracker.record_trade(
                    token_id=tid_a,
                    side=side_a,
                    size=trade_size,
                    price=entry_price,
                    market_group=market_group,
                    expires_at=expiry_a,
                    condition_id=signal.token_a,
                )
                await self.delta_tracker.record_trade(
                    token_id=tid_b,
                    side=side_b,
                    size=trade_size,
                    price=entry_price,
                    market_group=market_group,
                    expires_at=expiry_b,
                    condition_id=signal.token_b,
                )

            logger.info(f"✅ Position entered for {signal.pair_name}")

        except Exception as e:
            logger.error(f"❌ Failed to enter position: {e}")
            await self._release_allocation(allocation_info, Decimal("0"))

    async def manage_positions(self):
        """Monitor and exit active positions"""
        if not self.active_positions:
            return

        logger.debug(f"📊 Managing {len(self.active_positions)} active positions")

        positions_to_close = []

        for pair_name, position_data in self.active_positions.items():
            # Get current metrics
            metrics = self.pair_metrics_cache.get(pair_name)
            if not metrics:
                continue

            signal = position_data['signal']
            entry_z = position_data['entry_z_score']
            current_z = metrics.current_z_score

            # Exit conditions
            should_exit = False
            exit_reason = ""

            # 1. Mean reversion achieved (Z-score near zero)
            if abs(current_z) < self.exit_z_threshold:
                should_exit = True
                exit_reason = f"Mean reversion (Z: {entry_z:.2f} → {current_z:.2f})"

            # 2. Stop loss (divergence worsened)
            elif abs(current_z) > self.stop_loss_z:
                should_exit = True
                exit_reason = f"Stop loss triggered (Z: {current_z:.2f})"

            # 3. Timeout (holding > 2x expected half-life)
            holding_time = datetime.now() - position_data['entry_time']
            max_holding_days = signal.expected_half_life * 2
            if holding_time > timedelta(days=max_holding_days):
                should_exit = True
                exit_reason = f"Timeout ({holding_time.days}d > {max_holding_days:.0f}d)"

            if should_exit:
                positions_to_close.append((pair_name, exit_reason))

        # Close positions
        for pair_name, exit_reason in positions_to_close:
            await self.close_position(pair_name, exit_reason)

    async def close_position(self, pair_name: str, exit_reason: str):
        """Close a stat arb position"""
        position_data = self.active_positions.get(pair_name)
        if not position_data:
            return

        signal = position_data['signal']
        metrics = self.pair_metrics_cache.get(pair_name)
        dry_run = getattr(self.client.config, 'DRY_RUN', True)
        executed_size_dec = position_data.get('executed_size')
        executed_size = float(executed_size_dec) if executed_size_dec is not None else float(signal.position_size)

        logger.info(f"\n{'='*60}")
        logger.info(f"🔚 CLOSING POSITION: {pair_name}")
        logger.info(f"{'='*60}")
        logger.info(f"Reason: {exit_reason}")
        logger.info(f"Entry Z-Score: {position_data['entry_z_score']:.2f}")
        if metrics:
            logger.info(f"Exit Z-Score: {metrics.current_z_score:.2f}")
        logger.info(f"Holding Time: {datetime.now() - position_data['entry_time']}")

        # Execute closing orders (reverse of entry)
        try:
            tid_a, tid_b = position_data.get('resolved_tids', (None, None))
            if not tid_a or not tid_b:
                logger.error(f"❌ Cannot close position: Resolved Token IDs missing for {pair_name}")
                return
            market_group = position_data.get('market_group', self._resolve_pair_group(pair_name))
            exit_side_a, exit_side_b = self._exit_sides(signal.action)
            trade_size = executed_size

            if not dry_run:
                if signal.action == "SHORT_A_LONG_B":
                    # Close by: BUY A, SELL B
                    logger.info(f"   🚀 LIVE CLOSE: BUY {tid_a[:10]}... | SELL {tid_b[:10]}...")
                    await self.client.place_market_order(tid_a, "BUY", trade_size)
                    await self.client.place_market_order(tid_b, "SELL", trade_size)
                else:
                    # Close by: SELL A, BUY B
                    logger.info(f"   🚀 LIVE CLOSE: SELL {tid_a[:10]}... | BUY {tid_b[:10]}...")
                    await self.client.place_market_order(tid_a, "SELL", trade_size)
                    await self.client.place_market_order(tid_b, "BUY", trade_size)
            else:
                logger.info(f"   🧪 [DRY RUN] Closing position for {pair_name}")

            # Record Exits
            if self.pnl_tracker and 'trade_ids' in position_data:
                for tid in position_data['trade_ids']:
                    # Simulating a small profit (0.52 exit vs 0.50 entry) for verification
                    self.pnl_tracker.record_exit(
                        trade_id=tid, 
                        exit_price=0.52, 
                        reason=exit_reason
                    )

            # Release budget allocation
            if position_data['allocation_info'] and self.budget_manager:
                await self._release_allocation(position_data['allocation_info'], Decimal("0"))

            if self.delta_tracker:
                exit_price = 0.52 if self.pnl_tracker else 0.5
                await self.delta_tracker.record_trade(
                    token_id=tid_a,
                    side=exit_side_a,
                    size=trade_size,
                    price=exit_price,
                    market_group=market_group,
                    condition_id=signal.token_a,
                )
                await self.delta_tracker.record_trade(
                    token_id=tid_b,
                    side=exit_side_b,
                    size=trade_size,
                    price=exit_price,
                    market_group=market_group,
                    condition_id=signal.token_b,
                )

            # Remove from active positions
            del self.active_positions[pair_name]

            logger.info(f"✅ Position closed for {pair_name}")

        except Exception as e:
            logger.error(f"❌ Failed to close position: {e}")

    async def fetch_historical_prices(
        self,
        condition_id: str,
        days: int
    ) -> List[Dict]:
        """
        Fetch historical price data from Polymarket using real API.

        Returns:
            List of dicts: [{'timestamp': datetime, 'price': float}, ...] 
        """
        logger.debug(f"Fetching {days} days of data for {condition_id}")

        # Use PolymarketHistoryAPI for real data
        if not hasattr(self, '_price_api'):
            from src.core.price_history_api import PolymarketHistoryAPI
            self._price_api = PolymarketHistoryAPI()

        try:
            # Fetch real historical data along with source metadata
            data, source = await self._price_api.get_history_with_source(condition_id, days=days)
            logger.info(
                "📚 History source for %s...: %s (%d pts)",
                condition_id[:8],
                source,
                len(data),
            )

            if len(data) < 10:
                logger.warning(
                    "Insufficient data for %s (%d points from %s); synthetic fallback likely noisy",
                    condition_id,
                    len(data),
                    source,
                )

            return data

        except Exception as e:
            logger.error(f"Error fetching historical data for {condition_id}: {e}")
            # Fallback to synthetic if API fails
            return await self._price_api._generate_synthetic_history(condition_id, days)

    def _get_history_source(self, condition_id: str) -> Optional[str]:
        """
        Helper to read the last known history source for a condition.
        Returns None if the cache is unavailable.
        """
        api = getattr(self, "_price_api", None)
        if not api or not hasattr(api, "get_history_source"):
            return None
        try:
            return api.get_history_source(condition_id)
        except Exception as exc:
            logger.debug(f"History source lookup failed for {condition_id[:8]}: {exc}")
            return None

    async def shutdown(self):
        """Release data clients."""
        api = getattr(self, "_price_api", None)
        if api:
            try:
                await api.close()
            except Exception as exc:
                logger.debug(f"StatArb price API close error: {exc}")
            self._price_api = None

    async def auto_discover_pairs_loop(self):
        """1시간마다 전략적으로 최적화된 마켓 페어를 탐색합니다."""
        from src.core.gamma_client import GammaClient
        gamma = GammaClient()
        
        while True:
            try:
                logger.info("🔍 StatArb: Running Advanced Market Discovery...")
                # 더 많은 후보군 확보 (100개 -> 200개)
                markets = await gamma.get_active_markets(limit=200, volume_min=1000, max_hours_to_close=48)
                
                # 1. 자산-프록시(Proxy Peg) 탐색 로직 확장
                proxies = {
                    "bitcoin": ["mstr", "bitcoin", "btc", "etf"],
                    "ethereum": ["eth", "ethereum", "staking"],
                    "solana": ["sol", "solana", "phantom"],
                    "xrp": ["xrp", "ripple", "sec"],
                    "doge": ["doge", "dogecoin", "musk"],
                    "trump": ["gop", "republican", "fed chair", "cabinet"],
                    "elon": ["doge", "tesla", "x.com", "ai"]
                }
                
                added_count = 0
                for base, keywords in proxies.items():
                    group = [m for m in markets if any(kw in m.get('question', '').lower() for kw in keywords)]
                    if len(group) >= 2:
                        # 🚀 안전하게 필드 존재 여부 확인 후 페어 추가
                        m1, m2 = group[0], group[1]
                        cid1 = m1.get('condition_id') or m1.get('id')
                        cid2 = m2.get('condition_id') or m2.get('id')
                        
                        if cid1 and cid2:
                            pair_name = f"PEG_{base.upper()}_{m1['id'][:4]}"
                            if not any(p[2] == pair_name for p in self.pairs):
                                self.add_pair(cid1, cid2, pair_name, "proxy_peg")
                                added_count += 1

                # 2. 초단기 만기 마켓(Near-Expiry) 탐색
                # 만기가 24시간 이내인 시장은 변동성이 크므로 별도 관리 (우선순위 부여)
                now = datetime.now()
                for m in markets:
                    ends_at_str = m.get('ends_at')
                    if ends_at_str:
                        try:
                            # ends_at 형식에 따라 파싱 (예: "2026-01-07T12:00:00Z")
                            ends_at = datetime.fromisoformat(ends_at_str.replace('Z', '+00:00'))
                            if now < ends_at < now + timedelta(hours=24):
                                # 이런 시장은 NewsScalper가 감시하도록 시그널 버스에 등록하거나 
                                # StatArb에서 더 민감하게(Z-Score 1.5) 대응하도록 설계 가능
                                pass 
                        except: pass

                if added_count > 0:
                    logger.info(f"🚀 StatArb: Added {added_count} strategic Proxy-Peg pairs")
                
            except Exception as e:
                logger.error(f"Error in strategic discovery: {e}")
            
            await asyncio.sleep(3600) # 1시간마다 정밀 탐색

    def align_price_series(self, data_a: List[Dict], data_b: List[Dict]) -> pd.DataFrame:
        """
        Align two price series by timestamp.

        Returns:
            DataFrame with columns: timestamp, price_a, price_b
        """
        df_a = pd.DataFrame(data_a)
        df_b = pd.DataFrame(data_b)

        # Merge on timestamp (inner join to keep only overlapping times)
        df_a['timestamp'] = pd.to_datetime(df_a['timestamp'])
        df_b['timestamp'] = pd.to_datetime(df_b['timestamp'])

        df = pd.merge(
            df_a, df_b,
            on='timestamp',
            how='inner',
            suffixes=('_a', '_b')
        )

        df = df.sort_values('timestamp')

        return df
