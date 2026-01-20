import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class PolymarketHistoryAPI:
    """
    Polymarket Gamma API를 통해 실제 가격 히스토리(캔들 데이터)를 가져오는 클래스
    """

    def __init__(self):
        self.base_url = "https://gamma-api.polymarket.com"

    async def get_market_candles(
        self,
        condition_id: str,
        interval: str = "1h",
        days_back: int = 30
    ) -> List[Dict]:
        """
        특정 시장의 가격 캔들을 가져옵니다.

        Args:
            condition_id: 시장의 Condition ID
            interval: "1m", "5m", "15m", "1h", "1d"
            days_back: 조회할 과거 기간 (일 단위)

        Returns:
            [{'timestamp': datetime, 'price': float, 'volume': float}, ...]
        """
        end_ts = int(datetime.now().timestamp())
        start_ts = int((datetime.now() - timedelta(days=days_back)).timestamp())

        # Gamma API 엔드포인트: /markets/{condition_id}/prices
        url = f"{self.base_url}/markets/{condition_id}/prices"
        params = {
            "interval": interval,
            "startTs": start_ts,
            "endTs": end_ts
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        history = data.get('history', [])
                        
                        if not history:
                            logger.warning(f"No price history found for {condition_id}")
                            return []

                        return [
                            {
                                'timestamp': datetime.fromtimestamp(candle['t']),
                                'price': float(candle['c']),  # Close price
                                'volume': float(candle.get('v', 0))
                            }
                            for candle in history
                        ]
                    else:
                        logger.error(f"API Error ({response.status}) fetching history for {condition_id}")
                        return []
        except Exception as e:
            logger.error(f"Exception fetching history: {e}")
            return []

    async def get_aligned_prices(
        self,
        condition_a: str,
        condition_b: str,
        interval: str = "1h",
        days_back: int = 30
    ) -> tuple:
        """
        두 시장의 가격 데이터를 가져와 타임스탬프 기준으로 정렬(Align)합니다.

        Returns:
            (data_a, data_b) - 매칭되는 타임스탬프를 가진 데이터 쌍
        """
        results = await asyncio.gather(
            self.get_market_candles(condition_a, interval, days_back),
            self.get_market_candles(condition_b, interval, days_back)
        )

        data_a, data_b = results[0], results[1]
        
        if not data_a or not data_b:
            return [], []

        # 타임스탬프 기준 매칭 (간단한 동기화)
        ts_map_b = {d['timestamp']: d['price'] for d in data_b}
        
        aligned_a = []
        aligned_b = []
        
        for item_a in data_a:
            ts = item_a['timestamp']
            if ts in ts_map_b:
                aligned_a.append(item_a['price'])
                aligned_b.append(ts_map_b[ts])
                
        return aligned_a, aligned_b

if __name__ == "__main__":
    # 간단한 테스트를 위한 메인 함수
    async def test():
        api = PolymarketHistoryAPI()
        # BTC 위클리 시장 예시 ID (실제 동작 시 유효한 ID 필요)
        test_id = "0x..." 
        candles = await api.get_market_candles(test_id, days_back=1)
        print(f"Fetched {len(candles)} candles")
        if candles:
            print(f"Latest price: {candles[-1]['price']}")

    # asyncio.run(test())
