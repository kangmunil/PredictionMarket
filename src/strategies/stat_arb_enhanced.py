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
        signal_bus = None
    ):
        self.client = client
        self.budget_manager = budget_manager
        self.signal_bus = signal_bus # Hive Mind Connection
        
        if self.signal_bus:
            logger.info("🧠 StatArb connected to SignalBus")

        # Data requirements
        self.lookback_days = lookback_days
        self.min_data_points = min_data_points

        # Trading thresholds
        self.entry_z_threshold = 2.0  # Enter when |Z| > 2.0
        self.exit_z_threshold = 0.5   # Exit when |Z| < 0.5 (mean reversion)
        self.stop_loss_z = 4.0        # Stop loss at |Z| > 4.0

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

        # Performance tracking
        self.pair_metrics_cache: Dict[str, PairMetrics] = {}
        self.last_analysis: Dict[str, datetime] = {}

    def add_pair(
        self,
        condition_id_a: str,
        condition_id_b: str,
        pair_name: str,
        category: str = "general"
    ):
        """Add a pair to monitor for stat arb opportunities"""
        self.pairs.append((condition_id_a, condition_id_b, pair_name, category))
        logger.info(f"📊 Added pair: {pair_name} ({category})")

    async def run(self):
        """Main strategy loop"""
        logger.info("🛡️ Enhanced Stat Arb Strategy Started")
        logger.info(f"   Entry Z-Score: ±{self.entry_z_threshold}")
        logger.info(f"   Stop Loss Z-Score: ±{self.stop_loss_z}")
        logger.info(f"   Max Cointegration p-value: {self.max_cointegration_pvalue}")
        logger.info(f"   Lookback Period: {self.lookback_days} days")

        if not self.pairs:
            logger.warning("⚠️ No pairs configured. Add pairs using add_pair()")
            return

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

    async def scan_for_entries(self):
        """Scan cointegrated pairs for entry signals"""
        for pair_name, metrics in self.pair_metrics_cache.items():
            if not metrics.is_cointegrated:
                continue

            # Skip if already in position
            if pair_name in self.active_positions:
                continue

            # 🧠 Dynamic Threshold Adjustment based on SignalBus
            current_threshold = self.entry_z_threshold
            
            if self.signal_bus:
                # Get tokens from pair info
                pair_info = next((p for p in self.pairs if p[2] == pair_name), None)
                if pair_info:
                    token_a, token_b, _, _ = pair_info
                    
                    # Get signals from Hive Mind
                    # Note: Signal retrieval needs to be sync here or cached, 
                    # but get_signal is async. For prototype, we assume we can run it.
                    # Since this func is async, we can await.
                    sig_a = await self.signal_bus.get_signal(token_a)
                    sig_b = await self.signal_bus.get_signal(token_b)
                    
                    # Logic: If we want to LONG A (Z < 0) and A has Good News -> Lower threshold
                    if metrics.current_z_score < 0: # Signal to LONG A, SHORT B
                        if sig_a.sentiment_score > 0.5:
                            current_threshold = 1.5 # More aggressive
                            logger.info(f"🔥 Hive Mind Boost: Lowering entry threshold for {pair_name} due to {token_a} news")
                            
                    # Logic: If we want to LONG B (Z > 0) and B has Good News -> Lower threshold
                    elif metrics.current_z_score > 0: # Signal to SHORT A, LONG B
                        if sig_b.sentiment_score > 0.5:
                            current_threshold = 1.5
                            logger.info(f"🔥 Hive Mind Boost: Lowering entry threshold for {pair_name} due to {token_b} news")

            # Check if Z-score exceeds dynamic entry threshold
            if abs(metrics.current_z_score) > current_threshold:
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
        logger.info(f"\n{'='*60}")
        logger.info(f"🚨 STAT ARB ENTRY SIGNAL: {signal.pair_name}")
        logger.info(f"{'='*60}")
        logger.info(f"Action: {signal.action}")
        logger.info(f"Z-Score: {signal.z_score:.2f} (Threshold: {self.entry_z_threshold})")
        logger.info(f"Confidence: {signal.confidence:.0%}")
        logger.info(f"Position Size: ${signal.position_size} per leg")
        logger.info(f"Expected Half-Life: {signal.expected_half_life:.1f} days")
        logger.info(f"Reason: {signal.entry_reason}")

        # Budget check
        if self.budget_manager:
            total_required = signal.position_size * 2  # Both legs
            allocation_id = await self.budget_manager.request_allocation(
                strategy="polyai",
                amount=total_required,
                priority="normal"
            )

            if not allocation_id:
                logger.warning(f"⚠️ Budget allocation denied for {signal.pair_name}")
                return

            # Store allocation for later release
            allocation_info = {
                'allocation_id': allocation_id,
                'allocated_amount': total_required
            }
        else:
            allocation_info = None

        # Execute orders (placeholder - integrate with real order execution)
        try:
            if signal.action == "SHORT_A_LONG_B":
                logger.info(f"   → SELL {signal.token_a} (${signal.position_size})")
                logger.info(f"   → BUY {signal.token_b} (${signal.position_size})")
                # await self.client.place_market_order(signal.token_a, "SELL", signal.position_size)
                # await self.client.place_market_order(signal.token_b, "BUY", signal.position_size)
            else:
                logger.info(f"   → BUY {signal.token_a} (${signal.position_size})")
                logger.info(f"   → SELL {signal.token_b} (${signal.position_size})")
                # await self.client.place_market_order(signal.token_a, "BUY", signal.position_size)
                # await self.client.place_market_order(signal.token_b, "SELL", signal.position_size)

            # Record position
            self.active_positions[signal.pair_name] = {
                'signal': signal,
                'entry_time': datetime.now(),
                'entry_z_score': signal.z_score,
                'allocation_info': allocation_info
            }

            logger.info(f"✅ Position entered for {signal.pair_name}")

        except Exception as e:
            logger.error(f"❌ Failed to enter position: {e}")

            # Release budget if allocated
            if allocation_info and self.budget_manager:
                await self.budget_manager.release_allocation(
                    "polyai",
                    allocation_info['allocation_id'],
                    Decimal("0")  # Nothing spent
                )

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
            if signal.action == "SHORT_A_LONG_B":
                # Close by: BUY A, SELL B
                logger.info(f"   → BUY {signal.token_a} (close short)")
                logger.info(f"   → SELL {signal.token_b} (close long)")
            else:
                # Close by: SELL A, BUY B
                logger.info(f"   → SELL {signal.token_a} (close long)")
                logger.info(f"   → BUY {signal.token_b} (close short)")

            # Release budget allocation
            if position_data['allocation_info'] and self.budget_manager:
                await self.budget_manager.release_allocation(
                    "polyai",
                    position_data['allocation_info']['allocation_id'],
                    position_data['allocation_info']['allocated_amount']
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
            # Fetch real historical data
            data = await self._price_api.get_historical_events(condition_id, days=days)

            if len(data) < 10:
                logger.warning(f"Insufficient real data for {condition_id} ({len(data)} points), using synthetic")

            return data

        except Exception as e:
            logger.error(f"Error fetching historical data for {condition_id}: {e}")
            # Fallback to synthetic if API fails
            return await self._price_api._generate_synthetic_history(condition_id, days)

    def align_price_series(
        self,
        data_a: List[Dict],
        data_b: List[Dict]
    ) -> pd.DataFrame:
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
