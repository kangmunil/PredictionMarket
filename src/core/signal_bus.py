import asyncio
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

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
        logger.info("🧠 SignalBus (Hive Mind) Initialized")

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
                
            elif source == 'ARB':
                if 'volatile' in kwargs: signal.is_volatile = kwargs['volatile']
                if 'opportunity' in kwargs: signal.arb_opportunity_detected = kwargs['opportunity']

            logger.debug(f"🧠 Bus Updated [{source}] for {token_id[:10]}... | Sent:{signal.sentiment_score:.2f} Whale:{signal.whale_activity_score:.2f}")

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