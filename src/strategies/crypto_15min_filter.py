"""
Crypto 15-Minute Market Discovery Filter
Target: BTC, ETH, SOL, XRP 15-minute Up/Down markets
"""
from datetime import datetime, timedelta
import re
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class Crypto15MinFilter:
    """
    15분 단위 암호화폐 마켓을 정밀하게 필터링하는 클래스
    """

    CRYPTO_KEYWORDS = {
        'bitcoin': ['bitcoin', 'btc'],
        'ethereum': ['ethereum', 'eth'],
        'solana': ['solana', 'sol'],
        'xrp': ['xrp', 'ripple'],
        'bnb': ['bnb', 'binance coin'],
    }

    TIME_PATTERNS = [
        r'15\s*min',        # "15 min"
        r'15-min',          # "15-min"
        r'15min',           # "15min"
        r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)',  # 구체적인 시간 패턴
        r'Price of .* at', # Added: "Price of Bitcoin at 4:00 PM ET"
        r'at \d{1,2}:\d{2}\s*ET', # Added: "at 4:00 PM ET"
    ]

    DIRECTION_KEYWORDS = ['up', 'down', 'higher', 'lower', 'above', 'below']

    def is_crypto_15min_market(self, market: Dict) -> bool:
        """
        해당 마켓이 15분 단위 크립토 Up/Down 마켓인지 확인합니다.
        """
        question = market.get('question', '').lower()

        # 1. 크립토 키워드 확인
        has_crypto = any(
            keyword in question
            for keywords in self.CRYPTO_KEYWORDS.values()
            for keyword in keywords
        )
        if not has_crypto:
            return False

        # 2. 시간 패턴 확인 (15분 또는 특정 마감 시간)
        has_time_pattern = any(
            re.search(pattern, question, re.IGNORECASE)
            for pattern in self.TIME_PATTERNS
        )
        if not has_time_pattern:
            # Fallback check for new Polymarket format
            # e.g. "Bitcoin Price at 4pm ET: >$95k?" - handled by regex above
            return False

        # 3. 방향성 키워드 확인 (Up/Down 등)
        # Note: "Price of X at Y: >$Z?" implies direction (Above) implicitly?
        # But filter requires explicit keyword. Let's relax if ">" or "<" is present
        has_direction = any(kw in question for kw in self.DIRECTION_KEYWORDS)
        if not has_direction:
             # Check for mathematical direction symbols
             if ">" in question or "<" in question:
                 has_direction = True
             else:
                 return False

        # 4. 마감 임박 확인 (선택 사항: 20분 이내 마감되는 마켓 우선)
        try:
            end_date = market.get('end_date_iso')
            if end_date:
                end_time = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                time_to_close = end_time - datetime.now(end_time.tzinfo)
                # 마감되었거나 너무 많이 남은 마켓 제외 (여기선 1시간 이내로 설정)
                if not (timedelta(0) < time_to_close < timedelta(minutes=60)):
                    # 15분 마켓의 특성상 순환이 빠르므로 너무 먼 마켓은 필터링 가능
                    # 하지만 지금은 널널하게 60분으로 설정
                    pass 
        except:
            pass

        # 5. 거래량 체크
        volume = float(market.get('volume', 0))
        if volume < 10:  # Relaxed to $10 to catch fresh markets
            return False

        return True

    async def get_active_crypto_15min_markets(
        self,
        gamma_api,
        limit: int = 50
    ) -> List[Dict]:
        """
        활성화된 15분 크립토 마켓을 가져와 필터링합니다.
        """
        # 모든 활성 마켓 가져오기 (GammaClient는 closed 파라미터를 내부적으로 false로 설정함)
        all_markets = await gamma_api.get_active_markets(
            limit=limit * 3  # 필터링을 고려해 넉넉히 가져옴
        )

        # 15분 크립토 마켓 필터링
        crypto_15min = [
            m for m in all_markets
            if self.is_crypto_15min_market(m)
        ]

        # 거래량 순으로 정렬
        crypto_15min.sort(key=lambda m: float(m.get('volume', 0)), reverse=True)

        logger.info(f"🔍 Found {len(crypto_15min)} active crypto 15min markets")
        return crypto_15min[:limit]
