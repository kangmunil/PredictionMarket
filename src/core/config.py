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