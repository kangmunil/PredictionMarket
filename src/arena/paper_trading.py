import asyncio
import logging
import random
import csv
import os
from datetime import datetime
from src.core.clob_client import PolyClient
from src.strategies.ai_model import AIModelStrategy

# 로그 폴더 생성
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 로깅 설정: 콘솔과 파일에 동시 기록
log_formatter = logging.Formatter("%(asctime)s [ARENA] %(message)s")
logger = logging.getLogger("Arena")
logger.setLevel(logging.INFO)

# 파일 핸들러 (logs 폴더 내부)
file_handler = logging.FileHandler(os.path.join(LOG_DIR, "arena_activity.log"))
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

# 콘솔 핸들러
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

class ArenaRunner:
    def __init__(self):
        self.client = PolyClient()
        self.ai_brain = AIModelStrategy()
        self.csv_file = os.path.join(LOG_DIR, "arena_trades.csv")
        self._init_csv()
        
        # 동적으로 활성 마켓을 가져오기 위해 초기화 시점에는 비워둠
        self.target_tokens = []
        
        self.scores = {
            "Blind_Bot": {"balance": 1000.0, "trades": 0},
            "Random_Bot": {"balance": 1000.0, "trades": 0},
            "EliteMimic_Bot": {"balance": 1000.0, "trades": 0}
        }

    async def fetch_active_markets(self):
        """폴리마켓에서 현재 활성화된 상위 마켓을 가져옵니다."""
        logger.info("🔍 Fetching active markets from Polymarket...")
        try:
            # PolyClient를 통해 마켓 조회 (rest_client 사용)
            # get_markets가 next_cursor 등을 반환하므로 data['data'] 등을 파싱해야 함
            # py-clob-client의 get_markets 사용
            resp = self.client.rest_client.get_markets(limit=5)
            
            # 응답 구조에 따라 파싱 (라이브러리 버전에 따라 다를 수 있음)
            # 보통 resp는 리스트거나 딕셔너리
            markets = resp if isinstance(resp, list) else resp.get('data', [])
            
            active_markets = []
            for m in markets:
                # active하고 tokens가 있는 마켓만
                if m.get('active') and m.get('tokens'):
                    # YES 토큰 ID 추출 (보통 tokens[0]이 Long/Yes, tokens[1]이 Short/No)
                    token_id = m['tokens'][0]['token_id']
                    question = m.get('question', 'Unknown Market')
                    
                    # 키워드 추출 (간단히)
                    query = "crypto"
                    if "Trump" in question: query = "trump"
                    elif "Bitcoin" in question: query = "bitcoin"
                    elif "Ethereum" in question: query = "ethereum"
                    
                    active_markets.append({
                        "name": question[:30], # 너무 길면 자름
                        "id": token_id,
                        "query": query
                    })
                    
            if active_markets:
                self.target_tokens = active_markets[:3] # 상위 3개만
                logger.info(f"✅ Loaded {len(self.target_tokens)} active markets.")
                for tm in self.target_tokens:
                    logger.info(f"   - {tm['name']} (ID: {tm['id'][:10]}...)")
            else:
                logger.warning("⚠️ No active markets found. Using fallback.")
                self._use_fallback_markets()
                
        except Exception as e:
            logger.error(f"❌ Failed to fetch markets: {e}")
            self._use_fallback_markets()

    def _use_fallback_markets(self):
        self.target_tokens = [
            {"name": "Fallback BTC", "id": "21742633143463906290569050155826241533067272736897614382221909761164580721494", "query": "bitcoin"}
        ]

    def _init_csv(self):
        """CSV 파일 헤더 초기화"""
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "Bot", "Market", "Action", "Price", "Reason"])

    async def run_round(self):
        logger.info("--- New Arena Round Started ---")
        
        # 마켓이 없으면 로드 시도
        if not self.target_tokens:
            await self.fetch_active_markets()
        
        for market in self.target_tokens:
            current_price = self.client.get_best_ask_price(market['id'])
            if current_price == 0: current_price = 0.5
            
            logger.info(f"📍 Market: {market['name']} | Current Price: {current_price:.2f}")
            logger.info(f"🐳 Whale Alert! Detection for {market['name']}")

            # EliteMimic은 실제 뉴스를 분석함
            ai_approved = await self.ai_brain.validate_trade(market['id'], "YES", current_price)

            decisions = [
                ("Blind_Bot", True, "Followed signal blindly"),
                ("Random_Bot", random.choice([True, False]), "Flipped a coin"),
                ("EliteMimic_Bot", ai_approved, "Analyzed news & EV")
            ]

            for bot_name, action, reason in decisions:
                self.record_decision(bot_name, market['name'], action, current_price, reason)

        self.print_standings()

    def record_decision(self, bot_name, market_name, bought, price, reason):
        action_str = "BUY" if bought else "SKIP"
        if bought:
            self.scores[bot_name]["trades"] += 1
        
        # 1. 로그 파일 기록
        logger.info(f"   [{bot_name}] -> {action_str} | Price: {price} | Reason: {reason}")
        
        # 2. CSV 파일 기록
        with open(self.csv_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([datetime.now().isoformat(), bot_name, market_name, action_str, price, reason])

    def print_standings(self):
        logger.info("\n🏆 --- Current Arena Standings ---")
        for bot, data in self.scores.items():
            print(f"   - {bot:15}: Trades: {data['trades']}, Initial: $1000")
        print("-----------------------------------\n")

    async def start(self, rounds=5):
        logger.info("🏟️ Real-time Arena is LIVE. May the smartest bot win.")
        for i in range(rounds):
            await self.run_round()
            if i < rounds - 1:
                logger.info("Waiting 30 seconds for next news cycle...")
                await asyncio.sleep(30) # 실시간 데이터 수집 간격

if __name__ == "__main__":
    arena = ArenaRunner()
    asyncio.run(arena.start())
