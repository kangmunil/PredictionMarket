"""
EliteMimic Whale Intelligence Module
=====================================
Advanced analytics for detecting bait trades, front-running risks, and whale behavior patterns.
Prevents manipulation and optimizes copy-trading execution.

Author: Claude (Quantitative Trading Strategist)
Date: 2026-01-02
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
import statistics
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Represents a detected whale trade with metadata"""
    trader_address: str
    token_id: str
    side: str  # "BUY" or "SELL"
    detected_price: float
    amount: float
    tx_hash: str
    detection_timestamp: datetime
    block_number: int
    gas_price: float = 0.0

    # Derived attributes
    current_market_price: float = 0.0
    latency_ms: int = 0  # Time from tx execution to our detection
    slippage: float = 0.0


@dataclass
class WhaleProfile:
    """Historical performance and behavioral profile of a whale trader"""
    address: str
    username: str

    # Performance metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0

    # Behavioral patterns
    avg_position_size: float = 0.0
    avg_hold_time_hours: float = 0.0
    preferred_markets: Dict[str, int] = field(default_factory=dict)  # market_type -> count
    trade_frequency_per_day: float = 0.0

    # Recent activity tracking
    recent_trades: deque = field(default_factory=lambda: deque(maxlen=100))
    recent_win_rate_20: float = 0.0  # Win rate over last 20 trades
    recent_win_rate_50: float = 0.0

    # Manipulation indicators
    suspected_bait_trades: int = 0
    unusual_trades: int = 0
    strategy_shift_detected: bool = False
    last_strategy_shift: Optional[datetime] = None

    # Edge degradation
    rolling_sharpe_ratio: float = 0.0
    performance_trend: str = "STABLE"  # "IMPROVING", "STABLE", "DEGRADING"


@dataclass
class MarketState:
    """Current state of a prediction market"""
    token_id: str
    current_price: float
    bid_ask_spread: float
    liquidity_depth_10: float  # Total liquidity within 10% of mid price
    recent_volume_24h: float
    price_volatility_24h: float
    last_updated: datetime


class BaitDetector:
    """
    Detects potential bait trades designed to manipulate copy-traders.

    Red Flags for Bait Trades:
    1. Unusually large position size (>3x whale's average)
    2. Trading in low-liquidity markets (creates artificial signals)
    3. Rapid reversal patterns (enter and exit within minutes)
    4. Trading during off-hours (when fewer traders watch)
    5. Coordinated patterns across multiple wallets
    6. Deviation from whale's historical market preferences
    """

    def __init__(self):
        self.bait_score_threshold = 0.6  # Score above this = likely bait

    def analyze_signal(
        self,
        signal: TradeSignal,
        whale: WhaleProfile,
        market: MarketState
    ) -> Tuple[float, List[str]]:
        """
        Returns (bait_score, red_flags)
        bait_score: 0.0 (definitely legit) to 1.0 (definitely bait)
        """
        red_flags = []
        score = 0.0

        # 1. Position Size Anomaly
        if whale.avg_position_size > 0:
            size_ratio = signal.amount / whale.avg_position_size
            if size_ratio > 3.0:
                red_flags.append(f"OVERSIZED: {size_ratio:.1f}x normal position")
                score += 0.25
            elif size_ratio < 0.3:
                red_flags.append(f"UNDERSIZED: {size_ratio:.1f}x normal position")
                score += 0.15

        # 2. Low Liquidity Market (Manipulation Target)
        if market.liquidity_depth_10 < 1000:  # Less than $1k liquidity
            red_flags.append(f"LOW_LIQUIDITY: ${market.liquidity_depth_10:.0f}")
            score += 0.30

        # 3. Wide Bid-Ask Spread (Illiquid market)
        if market.bid_ask_spread > 0.05:  # >5% spread
            red_flags.append(f"WIDE_SPREAD: {market.bid_ask_spread:.2%}")
            score += 0.20

        # 4. Market Type Preference Violation
        # (Requires market categorization - placeholder)
        market_type = self._categorize_market(signal.token_id)
        if market_type not in whale.preferred_markets:
            red_flags.append(f"UNUSUAL_MARKET: {market_type}")
            score += 0.15

        # 5. High Gas Price (Urgency signal - could be frontrunning prep)
        if signal.gas_price > 100:  # Gwei - adjust based on network
            red_flags.append(f"HIGH_GAS: {signal.gas_price:.0f} Gwei")
            score += 0.10

        # 6. Recent Strategy Shift
        if whale.strategy_shift_detected:
            red_flags.append("STRATEGY_SHIFT_ACTIVE")
            score += 0.20

        # 7. Performance Degradation
        if whale.performance_trend == "DEGRADING":
            red_flags.append("WHALE_PERFORMANCE_DECLINING")
            score += 0.15

        # Normalize score to 0-1 range
        score = min(1.0, score)

        logger.info(f"Bait Analysis: Score={score:.2f}, Flags={red_flags}")
        return score, red_flags

    def _categorize_market(self, token_id: str) -> str:
        """Categorize market type from token_id or metadata"""
        # Placeholder - would use actual market metadata
        categories = ["POLITICS", "CRYPTO", "SPORTS", "FINANCE", "ENTERTAINMENT"]
        return categories[hash(token_id) % len(categories)]


class FrontRunningAnalyzer:
    """
    Analyzes whether we're being front-run when we detect whale trades.

    Key Questions:
    1. How long after whale's tx execution do we detect it?
    2. Has the price already moved significantly?
    3. Are there suspicious transactions between whale's tx and ours?
    4. Is there abnormal MEV bot activity in this market?
    """

    def __init__(self):
        self.max_acceptable_latency_ms = 5000  # 5 seconds
        self.max_acceptable_slippage = 0.03  # 3%

    def assess_frontrun_risk(
        self,
        signal: TradeSignal,
        market: MarketState,
        recent_txs: List[Dict]
    ) -> Tuple[str, float, List[str]]:
        """
        Returns (risk_level, confidence, warnings)
        risk_level: "LOW", "MEDIUM", "HIGH", "CRITICAL"
        confidence: 0.0 to 1.0
        """
        warnings = []
        risk_score = 0.0

        # 1. Detection Latency Analysis
        if signal.latency_ms > self.max_acceptable_latency_ms:
            warnings.append(f"HIGH_LATENCY: {signal.latency_ms}ms detection delay")
            risk_score += 0.3

        # 2. Price Movement Analysis
        signal.slippage = (signal.current_market_price - signal.detected_price) / signal.detected_price
        if signal.slippage > self.max_acceptable_slippage:
            warnings.append(f"PRICE_MOVED: {signal.slippage:.2%} slippage since whale trade")
            risk_score += 0.4

        # 3. Intermediate Transaction Analysis
        suspicious_tx_count = self._count_suspicious_txs(signal, recent_txs)
        if suspicious_tx_count > 0:
            warnings.append(f"SUSPICIOUS_TXS: {suspicious_tx_count} potential frontrunners detected")
            risk_score += 0.3

        # 4. Market Impact vs Order Size
        expected_impact = self._estimate_price_impact(signal.amount, market)
        if signal.slippage > expected_impact * 2:
            warnings.append(f"ABNORMAL_IMPACT: {signal.slippage:.2%} vs expected {expected_impact:.2%}")
            risk_score += 0.25

        # Determine risk level
        if risk_score >= 0.75:
            risk_level = "CRITICAL"
        elif risk_score >= 0.5:
            risk_level = "HIGH"
        elif risk_score >= 0.25:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        confidence = min(1.0, risk_score)

        logger.info(f"Front-run Risk: {risk_level} (confidence={confidence:.2f}), Warnings={warnings}")
        return risk_level, confidence, warnings

    def _count_suspicious_txs(self, signal: TradeSignal, recent_txs: List[Dict]) -> int:
        """Count transactions that look like MEV/frontrunning attempts"""
        # Placeholder - would analyze actual transaction patterns
        return 0

    def _estimate_price_impact(self, order_size: float, market: MarketState) -> float:
        """Estimate expected price impact based on order size and liquidity"""
        if market.liquidity_depth_10 == 0:
            return 0.10  # 10% default for zero liquidity

        # Simple square-root impact model
        impact = (order_size / market.liquidity_depth_10) ** 0.5 * 0.05
        return min(impact, 0.15)  # Cap at 15%


class WhaleProfiler:
    """
    Builds and maintains detailed behavioral profiles of whale traders.
    Tracks performance, patterns, and edge degradation.
    """

    def __init__(self):
        self.profiles: Dict[str, WhaleProfile] = {}
        self.min_trades_for_analysis = 20  # Need at least 20 trades for statistical validity

    def get_or_create_profile(self, address: str, username: str = "") -> WhaleProfile:
        """Get existing profile or create new one"""
        if address not in self.profiles:
            self.profiles[address] = WhaleProfile(address=address, username=username)
        return self.profiles[address]

    def update_profile(self, address: str, trade_data: Dict):
        """Update whale profile with new trade data"""
        profile = self.profiles.get(address)
        if not profile:
            return

        profile.total_trades += 1
        profile.recent_trades.append(trade_data)

        # Update position size
        if "amount" in trade_data:
            profile.avg_position_size = (
                (profile.avg_position_size * (profile.total_trades - 1) + trade_data["amount"])
                / profile.total_trades
            )

        # Update market preferences
        if "market_type" in trade_data:
            market_type = trade_data["market_type"]
            profile.preferred_markets[market_type] = profile.preferred_markets.get(market_type, 0) + 1

        # Update performance metrics
        if "outcome" in trade_data:
            if trade_data["outcome"] == "WIN":
                profile.winning_trades += 1
            elif trade_data["outcome"] == "LOSS":
                profile.losing_trades += 1

            if "pnl" in trade_data:
                profile.total_pnl += trade_data["pnl"]

        # Calculate recent win rates
        self._update_win_rates(profile)

        # Detect strategy shifts
        self._detect_strategy_shift(profile)

        # Assess performance trend
        self._assess_performance_trend(profile)

    def _update_win_rates(self, profile: WhaleProfile):
        """Calculate rolling win rates"""
        recent = list(profile.recent_trades)

        if len(recent) >= 20:
            wins_20 = sum(1 for t in recent[-20:] if t.get("outcome") == "WIN")
            profile.recent_win_rate_20 = wins_20 / 20

        if len(recent) >= 50:
            wins_50 = sum(1 for t in recent[-50:] if t.get("outcome") == "WIN")
            profile.recent_win_rate_50 = wins_50 / 50

    def _detect_strategy_shift(self, profile: WhaleProfile):
        """Detect if whale has changed trading strategy"""
        recent = list(profile.recent_trades)
        if len(recent) < 40:
            return  # Need enough data

        # Compare recent 20 trades vs previous 20 trades
        recent_20 = recent[-20:]
        previous_20 = recent[-40:-20]

        # Check for significant changes in:
        # 1. Average position size
        recent_avg_size = statistics.mean([t.get("amount", 0) for t in recent_20])
        previous_avg_size = statistics.mean([t.get("amount", 0) for t in previous_20])

        size_change = abs(recent_avg_size - previous_avg_size) / previous_avg_size if previous_avg_size > 0 else 0

        # 2. Market type distribution
        recent_markets = set(t.get("market_type") for t in recent_20 if t.get("market_type"))
        previous_markets = set(t.get("market_type") for t in previous_20 if t.get("market_type"))

        market_overlap = len(recent_markets & previous_markets) / len(recent_markets | previous_markets) if recent_markets or previous_markets else 1

        # Strategy shift if significant changes detected
        if size_change > 0.5 or market_overlap < 0.4:
            if not profile.strategy_shift_detected:
                profile.strategy_shift_detected = True
                profile.last_strategy_shift = datetime.now()
                logger.warning(f"STRATEGY SHIFT DETECTED for {profile.username}: size_change={size_change:.2%}, market_overlap={market_overlap:.2%}")
        else:
            # Clear flag if behavior normalized
            if profile.strategy_shift_detected and profile.last_strategy_shift:
                days_since_shift = (datetime.now() - profile.last_strategy_shift).days
                if days_since_shift > 7:
                    profile.strategy_shift_detected = False

    def _assess_performance_trend(self, profile: WhaleProfile):
        """Assess if whale's edge is improving, stable, or degrading"""
        recent = list(profile.recent_trades)
        if len(recent) < 50:
            return

        # Split into 3 time periods and compare
        period_size = len(recent) // 3
        period_1 = recent[:period_size]
        period_2 = recent[period_size:2*period_size]
        period_3 = recent[2*period_size:]

        def win_rate(trades):
            wins = sum(1 for t in trades if t.get("outcome") == "WIN")
            return wins / len(trades) if trades else 0

        wr1 = win_rate(period_1)
        wr2 = win_rate(period_2)
        wr3 = win_rate(period_3)

        # Determine trend
        if wr3 > wr2 > wr1:
            profile.performance_trend = "IMPROVING"
        elif wr3 < wr2 < wr1:
            profile.performance_trend = "DEGRADING"
            logger.warning(f"PERFORMANCE DEGRADING for {profile.username}: {wr1:.2%} -> {wr2:.2%} -> {wr3:.2%}")
        else:
            profile.performance_trend = "STABLE"

    def should_copy_whale(self, address: str) -> Tuple[bool, str, float]:
        """
        Determine if we should still copy this whale based on their profile.
        Returns (should_copy, reason, confidence)
        """
        profile = self.profiles.get(address)
        if not profile:
            return True, "NEW_WHALE", 0.5  # Default to copying new whales

        if profile.total_trades < self.min_trades_for_analysis:
            return True, "INSUFFICIENT_DATA", 0.5

        # Decision criteria
        reasons = []
        confidence = 0.5

        # 1. Overall win rate
        overall_wr = profile.winning_trades / (profile.winning_trades + profile.losing_trades) if (profile.winning_trades + profile.losing_trades) > 0 else 0
        if overall_wr < 0.45:  # Less than 45% win rate
            return False, f"LOW_WIN_RATE: {overall_wr:.2%}", 0.9

        # 2. Recent performance
        if profile.recent_win_rate_20 < 0.40:
            return False, f"RECENT_POOR_PERFORMANCE: {profile.recent_win_rate_20:.2%}", 0.8

        # 3. Performance trend
        if profile.performance_trend == "DEGRADING":
            reasons.append("DEGRADING_PERFORMANCE")
            confidence = 0.3

        # 4. Strategy shift
        if profile.strategy_shift_detected:
            reasons.append("STRATEGY_SHIFT")
            confidence *= 0.7

        # 5. High bait trade frequency
        if profile.total_trades > 0:
            bait_ratio = profile.suspected_bait_trades / profile.total_trades
            if bait_ratio > 0.2:  # >20% bait trades
                return False, f"HIGH_BAIT_RATIO: {bait_ratio:.2%}", 0.85

        # All checks passed
        if reasons:
            return True, f"PROCEED_WITH_CAUTION: {', '.join(reasons)}", confidence

        return True, "WHALE_VALIDATED", 0.9


class ReplicationStrategy:
    """
    Determines HOW to replicate whale trades (sizing, timing, filtering).

    Strategy Types:
    1. PROPORTIONAL: Copy with proportional position sizing
    2. FIXED: Always use fixed position size
    3. KELLY: Use Kelly Criterion based on edge estimation
    4. SELECTIVE: Only copy high-conviction signals
    """

    def __init__(self, strategy_type: str = "SELECTIVE", max_position_size: float = 100.0):
        self.strategy_type = strategy_type
        self.max_position_size = max_position_size  # In USDC
        self.min_ev_threshold = 0.03  # 3% minimum EV for selective copying
        self.confidence_threshold = 0.6  # Minimum confidence to copy

    def should_copy_trade(
        self,
        signal: TradeSignal,
        bait_score: float,
        frontrun_risk: str,
        whale_verdict: Tuple[bool, str, float],
        ai_ev: float,
        market: MarketState
    ) -> Tuple[bool, str, Dict]:
        """
        Master decision function combining all signals.
        Returns (should_copy, reason, execution_params)
        """
        reasons = []

        # 1. Whale validation
        should_copy_whale, whale_reason, whale_confidence = whale_verdict
        if not should_copy_whale:
            return False, f"WHALE_REJECTED: {whale_reason}", {}

        # 2. Bait detection
        if bait_score > 0.6:
            return False, f"BAIT_DETECTED: score={bait_score:.2f}", {}
        elif bait_score > 0.4:
            reasons.append(f"MODERATE_BAIT_RISK: {bait_score:.2f}")

        # 3. Front-running risk
        if frontrun_risk in ["CRITICAL", "HIGH"]:
            return False, f"FRONTRUN_RISK: {frontrun_risk}", {}
        elif frontrun_risk == "MEDIUM":
            reasons.append(f"MODERATE_FRONTRUN_RISK")

        # 4. EV check (AI validation)
        if ai_ev < self.min_ev_threshold:
            return False, f"INSUFFICIENT_EV: {ai_ev:.3f} < {self.min_ev_threshold}", {}

        # 5. Liquidity check
        if market.liquidity_depth_10 < 500:
            return False, f"INSUFFICIENT_LIQUIDITY: ${market.liquidity_depth_10:.0f}", {}

        # 6. Spread check
        if market.bid_ask_spread > 0.08:  # >8% spread
            return False, f"EXCESSIVE_SPREAD: {market.bid_ask_spread:.2%}", {}

        # Calculate position size
        position_size = self._calculate_position_size(
            signal=signal,
            whale_confidence=whale_confidence,
            ai_ev=ai_ev,
            market=market
        )

        # Calculate execution delay (anti-frontrunning)
        delay_seconds = self._calculate_execution_delay(
            frontrun_risk=frontrun_risk,
            bait_score=bait_score
        )

        # Determine order type
        use_limit_order = self._should_use_limit_order(market, signal)

        execution_params = {
            "position_size": position_size,
            "delay_seconds": delay_seconds,
            "use_limit_order": use_limit_order,
            "limit_price": signal.current_market_price * 1.02 if use_limit_order else None,  # 2% above market
            "max_slippage": 0.05,  # 5% max slippage tolerance
            "warnings": reasons
        }

        verdict = "COPY_APPROVED" + (f" ({', '.join(reasons)})" if reasons else "")
        return True, verdict, execution_params

    def _calculate_position_size(
        self,
        signal: TradeSignal,
        whale_confidence: float,
        ai_ev: float,
        market: MarketState
    ) -> float:
        """Calculate optimal position size based on strategy type"""

        if self.strategy_type == "FIXED":
            return min(self.max_position_size, 50.0)  # Default $50

        elif self.strategy_type == "PROPORTIONAL":
            # Scale with whale's position (capped)
            proportion = 0.1  # Copy 10% of whale's size
            size = signal.amount * proportion
            return min(size, self.max_position_size)

        elif self.strategy_type == "KELLY":
            # Kelly Criterion: f = (p * (b + 1) - 1) / b
            # Where p = win probability, b = odds (1/price - 1)
            prob = signal.current_market_price + ai_ev  # Estimated true probability
            b = (1 / signal.current_market_price) - 1
            kelly_fraction = (prob * (b + 1) - 1) / b if b > 0 else 0

            # Use fractional Kelly (1/4 Kelly for safety)
            kelly_fraction = max(0, min(kelly_fraction * 0.25, 0.1))  # Cap at 10% of bankroll

            # Assuming $1000 total bankroll
            bankroll = 1000.0
            size = bankroll * kelly_fraction
            return min(size, self.max_position_size)

        elif self.strategy_type == "SELECTIVE":
            # Scale with confidence and EV
            base_size = 30.0  # Base $30 position
            ev_multiplier = min(ai_ev / 0.03, 3.0)  # Up to 3x for high EV
            confidence_multiplier = whale_confidence

            size = base_size * ev_multiplier * confidence_multiplier
            return min(size, self.max_position_size)

        return 50.0  # Default fallback

    def _calculate_execution_delay(self, frontrun_risk: str, bait_score: float) -> int:
        """
        Calculate optimal delay before executing copy trade.

        Longer delays reduce frontrunning risk but increase price movement risk.
        """
        base_delay = 2  # 2 seconds minimum

        if frontrun_risk == "MEDIUM":
            base_delay += 3
        elif frontrun_risk == "HIGH":
            base_delay += 8

        if bait_score > 0.4:
            base_delay += 5  # Wait longer for suspected bait

        return min(base_delay, 15)  # Cap at 15 seconds

    def _should_use_limit_order(self, market: MarketState, signal: TradeSignal) -> bool:
        """
        Decide whether to use limit order (better price) vs market order (guaranteed execution).
        """
        # Use limit order if:
        # 1. Spread is wide (can capture better price)
        # 2. Market is not too volatile
        # 3. Liquidity is reasonable

        if market.bid_ask_spread > 0.03:  # >3% spread
            return True

        if market.price_volatility_24h > 0.15:  # >15% volatility - use market order for guaranteed fill
            return False

        return True  # Default to limit orders


class WhaleIntelligence:
    """
    Master orchestrator for all whale analysis and replication logic.
    Integrates all components: bait detection, frontrunning analysis, profiling, and replication strategy.
    """

    def __init__(self, strategy_type: str = "SELECTIVE", max_position_size: float = 100.0):
        self.bait_detector = BaitDetector()
        self.frontrun_analyzer = FrontRunningAnalyzer()
        self.profiler = WhaleProfiler()
        self.replicator = ReplicationStrategy(strategy_type, max_position_size)

        # Risk management
        self.max_daily_loss = 200.0  # $200 max loss per day
        self.max_concurrent_positions = 5
        self.daily_pnl = 0.0
        self.active_positions = 0

        # Performance tracking
        self.total_signals_analyzed = 0
        self.total_copied = 0
        self.total_rejected = 0
        self.rejection_reasons: Dict[str, int] = defaultdict(int)

    async def analyze_trade_signal(
        self,
        signal: TradeSignal,
        market: MarketState,
        ai_ev: float,
        recent_txs: List[Dict] = None
    ) -> Tuple[bool, str, Dict]:
        """
        Master analysis pipeline for a detected whale trade.

        Returns (should_copy, detailed_reason, execution_params)
        """
        self.total_signals_analyzed += 1

        logger.info(f"\n{'='*80}")
        logger.info(f"WHALE SIGNAL ANALYSIS #{self.total_signals_analyzed}")
        logger.info(f"Trader: {signal.trader_address}")
        logger.info(f"Token: {signal.token_id}")
        logger.info(f"Side: {signal.side} | Amount: ${signal.amount:.2f}")
        logger.info(f"Detected Price: {signal.detected_price:.4f} | Current Price: {signal.current_market_price:.4f}")
        logger.info(f"{'='*80}\n")

        # Risk management checks
        if self.daily_pnl <= -self.max_daily_loss:
            reason = f"DAILY_LOSS_LIMIT_REACHED: ${abs(self.daily_pnl):.2f}"
            self._record_rejection(reason)
            return False, reason, {}

        if self.active_positions >= self.max_concurrent_positions:
            reason = f"MAX_POSITIONS_REACHED: {self.active_positions}/{self.max_concurrent_positions}"
            self._record_rejection(reason)
            return False, reason, {}

        # Get or create whale profile
        whale = self.profiler.get_or_create_profile(signal.trader_address)

        # 1. Whale Validation
        whale_verdict = self.profiler.should_copy_whale(signal.trader_address)
        should_copy_whale, whale_reason, whale_confidence = whale_verdict

        logger.info(f"[1/4] WHALE VALIDATION: {whale_reason} (confidence={whale_confidence:.2f})")

        # 2. Bait Detection
        bait_score, bait_flags = self.bait_detector.analyze_signal(signal, whale, market)

        logger.info(f"[2/4] BAIT DETECTION: Score={bait_score:.2f}, Flags={bait_flags}")

        # 3. Front-running Analysis
        recent_txs = recent_txs or []
        frontrun_risk, frontrun_confidence, frontrun_warnings = self.frontrun_analyzer.assess_frontrun_risk(
            signal, market, recent_txs
        )

        logger.info(f"[3/4] FRONTRUN ANALYSIS: Risk={frontrun_risk}, Warnings={frontrun_warnings}")

        # 4. Replication Decision
        should_copy, reason, execution_params = self.replicator.should_copy_trade(
            signal=signal,
            bait_score=bait_score,
            frontrun_risk=frontrun_risk,
            whale_verdict=whale_verdict,
            ai_ev=ai_ev,
            market=market
        )

        logger.info(f"[4/4] REPLICATION DECISION: {reason}")

        if should_copy:
            self.total_copied += 1
            self.active_positions += 1
            logger.info(f"\n{'>'*80}")
            logger.info(f"DECISION: COPY TRADE")
            logger.info(f"Position Size: ${execution_params['position_size']:.2f}")
            logger.info(f"Execution Delay: {execution_params['delay_seconds']}s")
            logger.info(f"Order Type: {'LIMIT' if execution_params['use_limit_order'] else 'MARKET'}")
            if execution_params.get('warnings'):
                logger.warning(f"Warnings: {execution_params['warnings']}")
            logger.info(f"{'<'*80}\n")
        else:
            self.total_rejected += 1
            self._record_rejection(reason)
            logger.info(f"\nDECISION: REJECT - {reason}\n")

        return should_copy, reason, execution_params

    def _record_rejection(self, reason: str):
        """Track rejection reasons for analysis"""
        # Extract primary reason (before colon)
        primary_reason = reason.split(":")[0]
        self.rejection_reasons[primary_reason] += 1

    def report_performance(self) -> Dict:
        """Generate performance report"""
        copy_rate = self.total_copied / self.total_signals_analyzed if self.total_signals_analyzed > 0 else 0

        report = {
            "total_signals": self.total_signals_analyzed,
            "total_copied": self.total_copied,
            "total_rejected": self.total_rejected,
            "copy_rate": copy_rate,
            "daily_pnl": self.daily_pnl,
            "active_positions": self.active_positions,
            "top_rejection_reasons": dict(sorted(
                self.rejection_reasons.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5])
        }

        logger.info("\n" + "="*80)
        logger.info("WHALE INTELLIGENCE PERFORMANCE REPORT")
        logger.info("="*80)
        logger.info(f"Total Signals Analyzed: {report['total_signals']}")
        logger.info(f"Copied: {report['total_copied']} ({copy_rate:.1%})")
        logger.info(f"Rejected: {report['total_rejected']}")
        logger.info(f"Daily PnL: ${report['daily_pnl']:.2f}")
        logger.info(f"Active Positions: {report['active_positions']}/{self.max_concurrent_positions}")
        logger.info(f"\nTop Rejection Reasons:")
        for reason, count in report['top_rejection_reasons'].items():
            logger.info(f"  - {reason}: {count}")
        logger.info("="*80 + "\n")

        return report

    def update_position_outcome(self, token_id: str, pnl: float):
        """Update after a position is closed"""
        self.daily_pnl += pnl
        self.active_positions = max(0, self.active_positions - 1)

        logger.info(f"Position closed: PnL=${pnl:+.2f} | Daily PnL: ${self.daily_pnl:+.2f}")
