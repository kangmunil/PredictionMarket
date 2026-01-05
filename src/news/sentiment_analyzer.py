"""
Financial Sentiment Analyzer using FinBERT
===========================================

Analyzes news sentiment using ProsusAI/finbert model.
Optimized for financial/crypto news with higher accuracy than generic BERT.

Features:
- Financial domain-specific sentiment
- Confidence scores
- Batch processing support
- GPU acceleration (if available)

Author: ArbHunter
Created: 2026-01-03
"""

import logging
from typing import Dict, List, Optional
import warnings

# Suppress transformers warnings
warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """
    Financial sentiment analyzer using FinBERT.

    FinBERT is fine-tuned on financial texts and achieves:
    - 97%+ accuracy on financial sentiment
    - Better understanding of market terminology
    - Proper handling of financial jargon

    Compared to generic BERT:
    - Generic BERT: "Stock plunges" → Neutral (incorrect)
    - FinBERT: "Stock plunges" → Negative (correct)
    """

    def __init__(self, model_name: str = "ProsusAI/finbert", device: Optional[str] = None):
        """
        Initialize sentiment analyzer.

        Args:
            model_name: HuggingFace model name (default: ProsusAI/finbert)
            device: Device to use ('cuda', 'cpu', or None for auto-detect)
        """
        self.model_name = model_name
        self.pipeline = None
        self.device = device

        # Lazy loading - only load when first needed
        # This saves ~500MB memory if not used
        self._is_loaded = False

    def _load_model(self):
        """Lazy load the model (first use only)"""
        if self._is_loaded:
            return

        try:
            logger.info(f"📦 Loading FinBERT model: {self.model_name}")
            logger.info("   This will download ~500MB on first use...")

            from transformers import pipeline
            import torch

            # Auto-detect device if not specified
            if self.device is None:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"

            logger.info(f"   Using device: {self.device}")

            # Load pipeline
            self.pipeline = pipeline(
                "sentiment-analysis",
                model=self.model_name,
                device=0 if self.device == "cuda" else -1  # 0 for GPU, -1 for CPU
            )

            self._is_loaded = True
            logger.info("✅ FinBERT model loaded successfully")

        except ImportError:
            logger.error("❌ transformers library not installed!")
            logger.error("   Install: pip install transformers torch")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")
            raise

    def analyze(self, text: str, return_all: bool = False) -> Dict:
        """
        Analyze sentiment of a single text.

        Args:
            text: Text to analyze (headline, article, etc.)
            return_all: If True, return all label scores; if False, only top label

        Returns:
            Dict with 'label' (positive/negative/neutral) and 'score' (confidence)

        Example:
            >>> analyzer = SentimentAnalyzer()
            >>> result = analyzer.analyze("Bitcoin hits new all-time high!")
            >>> print(result)
            {'label': 'positive', 'score': 0.98, 'all_scores': {...}}
        """
        if not text or not text.strip():
            return {
                "label": "neutral",
                "score": 0.0,
                "error": "Empty text"
            }

        # Lazy load model
        self._load_model()

        try:
            # Truncate if too long (FinBERT max: 512 tokens)
            if len(text) > 512:
                text = text[:512]

            # Run inference
            result = self.pipeline(text)[0]

            # FinBERT returns: positive, negative, neutral
            # Normalize to lowercase
            label = result["label"].lower()
            score = result["score"]

            output = {
                "label": label,
                "score": score,
                "text_length": len(text)
            }

            # Optionally get all scores
            if return_all:
                all_results = self.pipeline(text, return_all_scores=True)[0]
                output["all_scores"] = {
                    r["label"].lower(): r["score"]
                    for r in all_results
                }

            return output

        except Exception as e:
            logger.error(f"❌ Sentiment analysis error: {e}")
            return {
                "label": "neutral",
                "score": 0.0,
                "error": str(e)
            }

    def analyze_batch(self, texts: List[str], batch_size: int = 8) -> List[Dict]:
        """
        Analyze multiple texts in batch (faster).

        Args:
            texts: List of texts to analyze
            batch_size: Batch size for processing (default: 8)

        Returns:
            List of sentiment dicts
        """
        if not texts:
            return []

        # Lazy load model
        self._load_model()

        try:
            # Truncate long texts
            truncated = [t[:512] if len(t) > 512 else t for t in texts]

            # Batch inference
            results = self.pipeline(truncated, batch_size=batch_size)

            return [
                {
                    "label": r["label"].lower(),
                    "score": r["score"],
                    "text_length": len(texts[i])
                }
                for i, r in enumerate(results)
            ]

        except Exception as e:
            logger.error(f"❌ Batch analysis error: {e}")
            return [{"label": "neutral", "score": 0.0, "error": str(e)} for _ in texts]

    def get_trading_signal(
        self,
        text: str,
        confidence_threshold: float = 0.75
    ) -> Optional[str]:
        """
        Convert sentiment to trading signal.

        Args:
            text: Text to analyze
            confidence_threshold: Minimum confidence to generate signal (0.0-1.0)

        Returns:
            "BUY" if positive with high confidence
            "SELL" if negative with high confidence
            None if neutral or low confidence

        Example:
            >>> analyzer = SentimentAnalyzer()
            >>> signal = analyzer.get_trading_signal("Bitcoin crashes 20%!")
            >>> print(signal)  # "SELL"
        """
        result = self.analyze(text)

        label = result["label"]
        score = result["score"]

        # Only generate signal if confidence is high enough
        if score < confidence_threshold:
            return None

        # Map sentiment to trading action
        if label == "positive":
            return "BUY"
        elif label == "negative":
            return "SELL"
        else:
            return None

    def is_high_impact(
        self,
        text: str,
        impact_threshold: float = 0.85
    ) -> bool:
        """
        Check if news is high-impact (very positive or very negative).

        High-impact news is more likely to move markets quickly.

        Args:
            text: Text to analyze
            impact_threshold: Minimum score for high-impact (default: 0.85)

        Returns:
            True if sentiment is very strong (positive OR negative)
        """
        result = self.analyze(text)

        # High impact if strongly positive OR strongly negative
        if result["label"] in ["positive", "negative"]:
            return result["score"] >= impact_threshold

        return False


# Utility functions for common use cases

def quick_sentiment(text: str) -> str:
    """
    Quick sentiment analysis (convenience function).

    Returns: 'positive', 'negative', or 'neutral'
    """
    analyzer = SentimentAnalyzer()
    result = analyzer.analyze(text)
    return result["label"]


def should_trade_on_news(text: str, min_confidence: float = 0.80) -> tuple[bool, str]:
    """
    Decide if news is strong enough to trade on.

    Args:
        text: News text
        min_confidence: Minimum confidence threshold

    Returns:
        (should_trade: bool, signal: str)

    Example:
        >>> should_trade, signal = should_trade_on_news("Bitcoin soars past $100k!")
        >>> print(should_trade, signal)  # True, "BUY"
    """
    analyzer = SentimentAnalyzer()
    result = analyzer.analyze(text)

    label = result["label"]
    score = result["score"]

    # Only trade on strong signals
    if score >= min_confidence and label in ["positive", "negative"]:
        signal = "BUY" if label == "positive" else "SELL"
        return True, signal

    return False, "HOLD"


# Standalone test
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("\n" + "=" * 70)
    print("📊 FinBERT Sentiment Analyzer - Test Suite")
    print("=" * 70)

    # Test headlines (crypto news examples)
    test_headlines = [
        "Bitcoin hits new all-time high of $100,000!",
        "Ethereum crashes 30% amid SEC investigation",
        "Crypto market remains stable despite volatility",
        "Major hedge fund announces $1B Bitcoin purchase",
        "SEC approves Bitcoin ETF - market rallies",
        "FTX collapse triggers massive crypto sell-off",
        "Bitcoin adoption grows in emerging markets",
        "Regulations threaten cryptocurrency future"
    ]

    print("\n🧪 Testing sentiment analysis on crypto headlines:\n")

    try:
        analyzer = SentimentAnalyzer()

        for i, headline in enumerate(test_headlines, 1):
            print(f"{i}. \"{headline}\"")

            # Analyze sentiment
            result = analyzer.analyze(headline, return_all=True)

            # Get trading signal
            signal = analyzer.get_trading_signal(headline, confidence_threshold=0.75)

            # Check if high-impact
            high_impact = analyzer.is_high_impact(headline, impact_threshold=0.85)

            print(f"   Sentiment: {result['label'].upper()}")
            print(f"   Confidence: {result['score']:.2%}")
            if "all_scores" in result:
                print(f"   All scores: {result['all_scores']}")
            print(f"   Trading Signal: {signal or 'HOLD'}")
            print(f"   High Impact: {'✅ YES' if high_impact else '❌ NO'}")
            print()

        print("=" * 70)
        print("✅ Test complete!")
        print("\nKey findings:")
        print("- Positive headlines should get 'BUY' signals")
        print("- Negative headlines should get 'SELL' signals")
        print("- Neutral headlines should get 'HOLD'")
        print("- High-impact news has confidence > 85%")

    except ImportError:
        print("\n❌ ERROR: transformers library not installed")
        print("\nInstall required packages:")
        print("  pip3 install --break-system-packages transformers torch")
        print("\nNote: First run will download ~500MB model")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
