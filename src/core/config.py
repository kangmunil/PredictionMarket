import os
from dotenv import load_dotenv

load_dotenv()

class Config:
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
        
        # 기본값 (최신 트렌드 반영)
        return [
            "sec-settlement", "stablecoin-regulation", "etf-approval", "gensler",
            "trump-policy", "fed-rate", "powell", "election-odds",
            "ai-agents", "depin", "rwa", "layer2-scaling", "meme-coins",
            "breaking", "hack", "exploit", "listing", "liquidation"
        ]

    @property
    def WS_URL(self):
        return "wss://ws-subscriptions-clob.polymarket.com"