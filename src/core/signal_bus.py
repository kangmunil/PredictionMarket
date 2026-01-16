import asyncio
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.core.config import Config

logger = logging.getLogger(__name__)

@dataclass
class MarketSignal:
    """
    각 시장(Token/Market)에 대한 실시간 통합 정보
    """
    token_id: str
    
    # News Sentiment
    sentiment_score: float = 0.0      # -1.0(악재) ~ 1.0(호재)
    sentiment_label: str = "neutral"
    news_count: int = 0
    
    # Whale Activity
    whale_activity_score: float = 0.0 # 0.0 ~ 1.0 (비정상적 매수세)
    recent_whale_side: Optional[str] = None # 'BUY' or 'SELL'
    
    # Volatility / Arb
    is_volatile: bool = False
    arb_opportunity_detected: bool = False
    delta_exposure: float = 0.0
    long_avg_price: float = 0.0
    short_avg_price: float = 0.0
    spread: float = 0.0
    spread_bps: float = 0.0
    spread_regime: str = "UNKNOWN"
    expires_at: Optional[datetime] = None
    
    last_updated: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

class SignalBus:
    """
    Central Nervous System (중추 신경계)
    모든 봇이 이 버스를 통해 시장 상황을 실시간으로 공유합니다.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SignalBus, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._signals: Dict[str, MarketSignal] = {} # token_id -> MarketSignal
        self._global_mode: str = "NORMAL" # NORMAL, BULL_FRENZY, PANIC_SELL
        self._lock = asyncio.Lock()
        self._initialized = True
        cfg = Config()
        thresholds = cfg.SPREAD_REGIME_THRESHOLDS
        self._spread_thresholds = {
            "efficient": float(thresholds.get("efficient", 0.01)),
            "neutral": float(thresholds.get("neutral", 0.03)),
        }
        self.redis = None
        logger.info("🧠 SignalBus (Hive Mind) Initialized")

    def set_redis(self, redis_client):
        """Inject Redis client for persistence"""
        self.redis = redis_client

    async def load_state(self):
        """Restore signals from Redis on startup"""
        if not self.redis: return
        try:
            # Load all signal keys
            keys = await self.redis.keys("signal:*")
            count = 0
            for key in keys:
                token_id = key.decode().split(":")[1]
                data = await self.redis.get(key)
                if data:
                    try:
                        import json
                        sig_dict = json.loads(data)
                        # Reconstruct MarketSignal
                        # Handle datetime fields
                        if 'last_updated' in sig_dict:
                            if isinstance(sig_dict['last_updated'], str):
                                sig_dict['last_updated'] = datetime.fromisoformat(sig_dict['last_updated'])
                        
                        self._signals[token_id] = MarketSignal(**sig_dict)
                        count += 1
                    except Exception as e:
                        logger.error(f"Failed to deserialze signal {token_id}: {e}")
            if count > 0:
                logger.info(f"🧠 SignalBus Restored {count} signals from Redis")
        except Exception as e:
            logger.error(f"SignalBus restore error: {e}")

    async def _persist_signal(self, token_id: str):
        """Save single signal to Redis"""
        if not self.redis: return
        try:
            signal = self._signals.get(token_id)
            if not signal: return
            
            import json
            from dataclasses import asdict
            
            # Helper for datetime serialization
            def json_serial(obj):
                if isinstance(obj, (datetime, date)):
                    return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")

            data = json.dumps(asdict(signal), default=json_serial)
            # Set with 24h expiry (volatile markets)
            await self.redis.setex(f"signal:{token_id}", 86400, data)
        except Exception as e:
            logger.debug(f"Redis save failed for {token_id}: {e}")

    async def update_signal(self, token_id: str, source: str, **kwargs):
        """
        봇들이 정보를 업데이트하는 메서드
        source: 'NEWS', 'WHALE', 'ARB'
        """
        async with self._lock:
            if token_id not in self._signals:
                self._signals[token_id] = MarketSignal(token_id=token_id)
            
            signal = self._signals[token_id]
            signal.last_updated = datetime.now()
            
            # 정보 출처에 따른 업데이트
            if source == 'NEWS':
                if 'score' in kwargs: signal.sentiment_score = kwargs['score']
                if 'label' in kwargs: signal.sentiment_label = kwargs['label']
                signal.news_count += 1
                
            elif source == 'WHALE':
                if 'score' in kwargs: signal.whale_activity_score = kwargs['score']
                if 'side' in kwargs: signal.recent_whale_side = kwargs['side']
                
            if source == 'ARB':
                if 'volatile' in kwargs: signal.is_volatile = kwargs['volatile']
                if 'opportunity' in kwargs: signal.arb_opportunity_detected = kwargs['opportunity']

            logger.debug(f"🧠 Bus Updated [{source}] for {token_id[:10]}... | Sent:{signal.sentiment_score:.2f} Whale:{signal.whale_activity_score:.2f}")
            
            # Persist to Redis
            asyncio.create_task(self._persist_signal(token_id))

    async def update_market_metrics(
        self,
        token_id: str,
        *,
        delta_exposure: Optional[float] = None,
        long_avg_price: Optional[float] = None,
        short_avg_price: Optional[float] = None,
        spread: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        best_bid: Optional[float] = None,
        best_ask: Optional[float] = None,
        mid_price: Optional[float] = None,
    ):
        async with self._lock:
            if token_id not in self._signals:
                self._signals[token_id] = MarketSignal(token_id=token_id)
            signal = self._signals[token_id]
            signal.last_updated = datetime.now()

            if delta_exposure is not None:
                signal.delta_exposure = delta_exposure
            if long_avg_price is not None:
                signal.long_avg_price = long_avg_price
            if short_avg_price is not None:
                signal.short_avg_price = short_avg_price
            spread_value = None
            mid_reference = mid_price
            if best_bid and best_ask and best_bid > 0 and best_ask > 0:
                spread_value = max(best_ask - best_bid, 0.0)
                mid_reference = (best_ask + best_bid) / 2.0
                signal.metadata["best_bid"] = best_bid
                signal.metadata["best_ask"] = best_ask
            elif spread is not None:
                spread_value = max(spread, 0.0)

            if spread_value is not None:
                if mid_reference is None and signal.long_avg_price and signal.short_avg_price:
                    avg_prices = [signal.long_avg_price, signal.short_avg_price]
                    positives = [p for p in avg_prices if p and p > 0]
                    if len(positives) == 2:
                        mid_reference = sum(positives) / 2.0

                signal.spread = spread_value
                spread_ratio = (
                    (spread_value / mid_reference) if mid_reference and mid_reference > 0 else None
                )
                if spread_ratio is not None:
                    signal.spread_bps = spread_ratio * 10000.0
                else:
                    signal.spread_bps = 0.0
                signal.spread_regime = self._classify_spread(spread_ratio)

            if metadata:
                signal.metadata.update(metadata)

            expires_at_val = None
            if metadata and metadata.get("expires_at"):
                expires_at_val = metadata["expires_at"]
            elif signal.metadata.get("expires_at"):
                expires_at_val = signal.metadata.get("expires_at")

            if expires_at_val:
                expiry_ctx = self._calculate_expiry_phase(expires_at_val)
                signal.metadata["expiry"] = expiry_ctx
            
            # Persist to Redis
            asyncio.create_task(self._persist_signal(token_id))

    async def get_signal(self, token_id: str) -> MarketSignal:
        """특정 토큰의 종합 상태 조회"""
        if token_id not in self._signals:
            return MarketSignal(token_id=token_id) # 빈 신호 반환
        return self._signals[token_id]

    async def get_hot_tokens(self, min_sentiment: float = 0.6, min_whale: float = 0.5) -> Dict[str, MarketSignal]:
        """지금 가장 뜨거운(호재+고래) 토큰 목록 조회"""
        return {
            k: v for k, v in self._signals.items() 
            if abs(v.sentiment_score) >= min_sentiment or v.whale_activity_score >= min_whale
        }

    async def get_spread_snapshot(
        self,
        max_entries: int = 6,
        max_age_seconds: int = 300,
    ) -> list[Dict[str, Any]]:
        """
        Return a prioritized snapshot of spread regimes for observability.
        """
        severity = {"INEFFICIENT": 2, "EFFICIENT": 1, "NEUTRAL": 0, "UNKNOWN": -1}
        now = datetime.now()
        entries = []
        async with self._lock:
            for token_id, signal in self._signals.items():
                age = (now - signal.last_updated).total_seconds()
                if age > max_age_seconds:
                    continue
                regime = (signal.spread_regime or "UNKNOWN").upper()
                if regime == "NORMAL":
                    regime = "NEUTRAL"
                entry = {
                    "token_id": token_id,
                    "regime": regime,
                    "spread_bps": round(signal.spread_bps or 0.0, 2),
                    "updated_at": signal.last_updated.isoformat(),
                }
                entries.append((severity.get(regime, -1), entry))

        entries.sort(key=lambda item: (item[0], item[1]["spread_bps"]), reverse=True)
        return [entry for _, entry in entries[:max_entries]]

    def _classify_spread(self, spread_ratio: Optional[float]) -> str:
        if spread_ratio is None or spread_ratio <= 0:
            return "UNKNOWN"
        if spread_ratio < self._spread_thresholds["efficient"]:
            return "EFFICIENT"
        if spread_ratio < self._spread_thresholds["neutral"]:
            return "NEUTRAL"
        return "INEFFICIENT"

    def _calculate_expiry_phase(self, expires_at_value: str) -> Dict[str, Any]:
        try:
            expiry_dt = datetime.fromisoformat(str(expires_at_value).replace("Z", "+00:00"))
        except Exception:
            return {"minutes_remaining": 9999, "phase": "EARLY"}

        now = datetime.now(timezone.utc)
        delta = expiry_dt - now
        minutes = max(0, delta.total_seconds() / 60)

        if minutes < 15:
            phase = "ENDGAME"
        elif minutes < 60:
            phase = "LATE"
        elif minutes < 240:
            phase = "MID"
        else:
            phase = "EARLY"

        return {
            "minutes_remaining": minutes,
            "phase": phase,
            "expires_at": expiry_dt.isoformat(),
        }
