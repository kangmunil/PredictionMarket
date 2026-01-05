import aiohttp
import logging

logger = logging.getLogger(__name__)

class GammaClient:
    """
    Client for Polymarket's Gamma API (Query Layer).
    Used to efficiently filter markets by volume, category, etc.
    Endpoint: https://gamma-api.polymarket.com
    """
    BASE_URL = "https://gamma-api.polymarket.com"

    async def get_active_markets(self, limit=50, volume_min=1000):
        """
        Fetch active markets with significant volume.
        Query: Active, sorted by volume desc.
        """
        url = f"{self.BASE_URL}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "order": "volume",
            "ascending": "false",
            "limit": limit,
            "offset": 0
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Filter by volume threshold locally if API doesn't support range
                        markets = [m for m in data if float(m.get('volume', 0)) >= volume_min]
                        return markets
                    else:
                        logger.error(f"Gamma API Error: {resp.status}")
                        return []
            except Exception as e:
                logger.error(f"Gamma Fetch Error: {e}")
                return []
