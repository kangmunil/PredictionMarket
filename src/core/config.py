import json
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self._dry_run_override = None

    @property
    def HOST(self):
        return os.getenv("POLY_HOST", "https://clob.polymarket.com")

    @property
    def CHAIN_ID(self):
        return int(os.getenv("POLY_CHAIN_ID", 137))

    @property
    def SIGNATURE_TYPE(self):
        return int(os.getenv("POLY_SIGNATURE_TYPE", 1))

    @property
    def PRIVATE_KEY(self):
        return os.getenv("PRIVATE_KEY")

    @property
    def FUNDER_ADDRESS(self):
        return os.getenv("FUNDER_ADDRESS")
    
    @property
    def NEWS_API_KEY(self):
        return os.getenv("NEWS_API_KEY")

    @property
    def TREE_NEWS_API_KEY(self):
        return os.getenv("TREE_NEWS_API_KEY")
    
    @property
    def TARGET_WALLETS(self) -> list:
        """Returns a list of all active target wallets from env"""
        return [
            addr for addr in [
                os.getenv("TARGET_WALLET_1"),
                os.getenv("TARGET_WALLET_2"),
                os.getenv("TARGET_WALLET_3")
            ] if addr
        ]

    @property
    def MONITOR_KEYWORDS(self) -> list:
        """감시할 뉴스 키워드 리스트 ( .env에서 설정 가능 )"""
        kw_env = os.getenv("MONITOR_KEYWORDS")
        if kw_env:
            return [k.strip() for k in kw_env.split(",")]
        
        # 최적화된 메이저 코인 + 정책 키워드 (범위 확장)
        return [
            "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "doge",
            "trump", "elon musk", "fed rate", "powell", "inflation", 
            "sec", "crypto regulation", "binance", "coinbase",
            "hack", "listing", "liquidation"
            "hack", "listing", "liquidation"
        ]

    @property
    def IGNORED_MARKETS(self) -> list:
        """Blacklisted markets to avoid trading"""
        return [
            "Will bitcoin hit $1m before GTA VI?",
        ]

    @property
    def WS_URL(self):
        return "wss://ws-subscriptions-clob.polymarket.com"

    @property
    def RPC_URL(self):
        return os.getenv("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")

    @property
    def DRY_RUN(self) -> bool:
        """
        Master switch for trading execution.
        If True, no real transactions are sent.
        """
        if self._dry_run_override is not None:
            return self._dry_run_override
            
        val = os.getenv("DRY_RUN", "True").lower()
        return val in ("true", "1", "yes", "on")

    @DRY_RUN.setter
    def DRY_RUN(self, value: bool):
        self._dry_run_override = bool(value)

    @property
    def BUDGET_MODE(self) -> str:
        return os.getenv("BUDGET_MODE", "simulation")

    @property
    def MAX_POSITION_SIZE(self) -> float:
        """Max USD size for a single position"""
        return float(os.getenv("MAX_POSITION_SIZE", "10.0"))

    @property
    def RISK_PER_TRADE_PERCENT(self) -> float:
        """Percentage of portfolio to risk per trade (0.01 = 1%)"""
        return float(os.getenv("RISK_PER_TRADE_PERCENT", "0.02"))

    @property
    def TAKER_FEE(self) -> float:
        return float(os.getenv("TAKER_FEE", "0.002"))

    @property
    def SLIPPAGE_BUFFER(self) -> float:
        return float(os.getenv("SLIPPAGE_BUFFER", "0.001"))  # 0.0015 -> 0.001 (0.1%)

    @property
    def DISABLE_SLIPPAGE_PROTECTION(self) -> bool:
        val = os.getenv("DISABLE_SLIPPAGE_PROTECTION", "false").lower()
        return val in ("true", "1", "yes", "on")

    @property
    def DELTA_LIMITS(self) -> dict:
        """
        Returns a dictionary of market-group delta limits.
        Structure:
        {
            "BTC_15M": {"hard": 2000.0, "soft": 1500.0},
            "ETH_15M": {"hard": 1500.0, "soft": 1100.0},
            "DEFAULT": {"hard": 800.0, "soft": 600.0},
        }
        """
        defaults = {
            "BTC_15M": {
                "hard": float(os.getenv("DELTA_LIMIT_BTC15M_HARD", "2000")),
                "soft": float(os.getenv("DELTA_LIMIT_BTC15M_SOFT", "1500")),
            },
            "ETH_15M": {
                "hard": float(os.getenv("DELTA_LIMIT_ETH15M_HARD", "1500")),
                "soft": float(os.getenv("DELTA_LIMIT_ETH15M_SOFT", "1100")),
            },
            "CRYPTO": {
                "hard": float(os.getenv("DELTA_LIMIT_CRYPTO_HARD", "1200")),
                "soft": float(os.getenv("DELTA_LIMIT_CRYPTO_SOFT", "900")),
            },
            "DEFAULT": {
                "hard": float(os.getenv("DELTA_LIMIT_DEFAULT_HARD", "800")),
                "soft": float(os.getenv("DELTA_LIMIT_DEFAULT_SOFT", "600")),
            },
        }

        overrides = os.getenv("DELTA_LIMITS_JSON")
        if overrides:
            try:
                parsed = json.loads(overrides)
                for key, value in parsed.items():
                    if isinstance(value, dict):
                        normalized_key = str(key).upper()
                        defaults[normalized_key] = {
                            "hard": float(value.get("hard"))
                            if value.get("hard") is not None
                            else None,
                            "soft": float(value.get("soft"))
                            if value.get("soft") is not None
                            else None,
                        }
            except json.JSONDecodeError:
                pass

        return defaults

    @property
    def SPREAD_REGIME_THRESHOLDS(self) -> dict:
        """
        Returns thresholds for classifying spread regimes.
        efficient: spreads below this are considered efficient (skip/size down)
        neutral: spreads below this (but above efficient) are neutral; above is inefficient
        """
        # Defaults expressed as ratios of mid-price (0.005 == 50 bps, 0.02 == 200 bps)
        efficient = float(os.getenv("SPREAD_EFFICIENT_MAX", "0.005"))
        neutral = float(os.getenv("SPREAD_NEUTRAL_MAX", "0.02"))
        if neutral <= efficient:
            neutral = efficient * 2.0
        return {"efficient": efficient, "neutral": neutral}
