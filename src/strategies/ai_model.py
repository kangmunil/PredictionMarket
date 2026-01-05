import logging
import asyncio
import random
import requests
from textblob import TextBlob
from src.core.config import Config

logger = logging.getLogger(__name__)

class AIModelStrategy:
    """
    EliteMimic AI Brain: Evaluates if a trade is worth copying.
    Integrates Real-Time News Sentiment and EV calculation.
    """
    def __init__(self, client=None):
        self.client = client
        self.config = Config()
        self.threshold_prob = 0.55  # Only copy if AI probability > 55%
        self.min_ev = 0.02          # Minimum 2% EV required
        
        # Check API Key
        if not self.config.NEWS_API_KEY:
            logger.warning("⚠️ NEWS_API_KEY not found in .env. AI will run in simulation mode.")

    async def predict_probability(self, market_id: str, outcome: str) -> float:
        """
        AI Model Prediction: Uses news/social signals to predict outcome probability.
        """
        # 1. Identify keywords from market_id or context (Simplified mapping)
        query = self._extract_keywords(market_id)
        
        # 2. Fetch External Data (News Sentiment)
        sentiment_score = await self.fetch_market_sentiment(query)
        
        # 3. Model Inference
        # Base probability (Neutral) is 0.5
        # Sentiment (-1.0 to 1.0) shifts the probability by up to +/- 15%
        base_prob = 0.5
        adjustment = sentiment_score * 0.15 
        final_prob = base_prob + adjustment
        
        # Clamp probability to reasonable bounds (10% - 90%)
        final_prob = max(0.1, min(0.9, final_prob))
        
        logger.info(f"🧠 AI Analysis for '{query}': Sentiment={sentiment_score:.2f} -> Prob={final_prob:.2%}")
        return final_prob

    def _extract_keywords(self, market_id: str) -> str:
        """
        Extracts search query from market_id or token info.
        For prototype, uses heuristics.
        """
        mid = market_id.lower()
        if "btc" in mid or "bitcoin" in mid: return "bitcoin"
        if "eth" in mid or "ethereum" in mid: return "ethereum"
        if "biden" in mid: return "biden"
        if "trump" in mid: return "trump"
        if "fed" in mid or "rate" in mid: return "federal reserve"
        return "crypto" # Default fallback

    async def fetch_market_sentiment(self, query: str) -> float:
        """
        Fetches news via NewsAPI and calculates average sentiment (-1.0 to 1.0).
        """
        if not self.config.NEWS_API_KEY:
            return 0.0 # Neutral if no key

        url = "https://newsapi.org/v2/everything"
        params = {
            'q': query,
            'sortBy': 'publishedAt',
            'language': 'en',
            'pageSize': 5,
            'apiKey': self.config.NEWS_API_KEY
        }

        try:
            # Blocking call run in executor to avoid freezing async loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: requests.get(url, params=params))
            data = response.json()

            if data.get('status') != 'ok':
                logger.warning(f"NewsAPI Error: {data.get('message', 'Unknown error')}")
                return 0.0

            articles = data.get('articles', [])
            if not articles:
                return 0.0

            total_polarity = 0.0
            count = 0
            
            log_msg = f"\n📰 [AI Brain] Reading News for '{query}'..."
            for article in articles:
                title = article.get('title', "")
                if not title: continue
                
                # Sentiment Analysis
                analysis = TextBlob(title)
                polarity = analysis.sentiment.polarity
                total_polarity += polarity
                count += 1
                log_msg += f"\n   - {title[:60]}... (Score: {polarity:.2f})"
            
            logger.info(log_msg)
            
            avg_sentiment = total_polarity / count if count > 0 else 0.0
            return avg_sentiment

        except Exception as e:
            logger.error(f"Error fetching news: {e}")
            return 0.0

    def calculate_ev(self, predicted_prob: float, market_price: float) -> float:
        """
        Calculate Expected Value.
        EV = (Win Prob * Profit) - (Loss Prob * Cost)
        Profit = (1 - Price), Cost = Price.
        Simplifies to: Prob - Price.
        """
        if market_price <= 0: return 0.0
        return predicted_prob - market_price

    async def validate_trade(self, market_id: str, outcome: str, price: float) -> bool:
        """
        Validates if the trade should be copied based on AI analysis.
        """
        prob = await self.predict_probability(market_id, outcome)
        ev = self.calculate_ev(prob, price)
        
        is_valid = prob >= self.threshold_prob and ev >= self.min_ev
        
        status = "APPROVED" if is_valid else "REJECTED"
        logger.info(f"⚖️ AI Verdict: {status} (Price: {price:.2f}, AI Prob: {prob:.2%}, EV: {ev:.4f})")
        return is_valid

    async def run(self):
        logger.info("Starting EliteMimic AI Brain loop...")
        while True:
            # Periodic scan (can be expanded later)
            await asyncio.sleep(60)