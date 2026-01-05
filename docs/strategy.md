**폴리마켓(Polymarket) 차익거래(Arbitrage) 봇**을 구축하기 위한 단계별 가이드와 핵심 구현 로직을 정리해 드립니다.

폴리마켓은 현재 **CLOB(Central Limit Order Book)** 방식을 사용하고 있으며 Polygon(PoS) 네트워크 위에서 동작하므로, 이에 맞춘 기술 스택이 필요합니다.

---

### 1. 개발 환경 및 기술 스택

가장 먼저 봇이 구동될 환경을 구축해야 합니다.

* **언어:** Python (라이브러리 생태계 및 비동기 처리에 강점)
* **블록체인 통신:** `web3.py` (지갑 연동, 가스비 계산, 트랜잭션 서명)
* **폴리마켓 전용:** `py-clob-client` (폴리마켓 공식 Python 클라이언트, 주문 및 시세 조회용)
* **비동기 처리:** `asyncio`, `aiohttp`, `websockets` (실시간 데이터 처리 필수)
* **연산:** `decimal` (부동 소수점 오차 방지)

### 2. 핵심 아키텍처 설계

봇은 크게 **데이터 수집(Data Ingestion) -> 기회 포착(Strategy Engine) -> 주문 실행(Execution Engine)**의 3단계로 구성됩니다.

#### A. 데이터 수집 (Data Ingestion)

* **WebSocket 연결:** REST API(폴링 방식)는 느려서 아비트라지 기회를 놓칩니다. 폴리마켓의 WebSocket API를 통해 Order Book(호가창) 변경 사항을 실시간으로 수신해야 합니다.
* **데이터 필터링:** 유동성이 너무 적거나(Gap이 큰 시장), 마감이 임박한 시장 등은 미리 필터링합니다.

#### B. 전략 엔진 (Strategy Engine)

제공해주신 3가지 전략 중 봇으로 구현하기 가장 명확한 두 가지 로직입니다.

**① 싱글 컨디션 아비트라지 (Single-Condition)**

* **로직:** 특정 마켓의 `Yes 최저 매도 호가` + `No 최저 매도 호가`를 더합니다.
* **판단:** `(Price_Yes + Price_No) < (1.0 - 거래 수수료 - 가스비/예상수익)`
* **액션:** 조건 만족 시 즉시 두 포지션 모두 시장가 매수(Market Buy) 또는 지정가 매수.

**② 크로스 플랫폼 아비트라지 (Cross-Platform)**

* **로직:** Polymarket 가격과 Kalshi(또는 기타 예측 시장)의 API를 동시에 구독.
* **판단:** `|Polymarket_Price - Kalshi_Price| > (Spread + Platform Fees + Gas)`
* **액션:** 싼 곳에서 매수(Long), 비싼 곳에서 매도(Short)하거나 반대 포지션을 취해 헷징.
* *난이도:* 플랫폼 간 정산 통화가 다르고(USDC vs USD), API 속도 차이로 인한 리스크가 큽니다.

#### C. 주문 실행 (Execution Engine)

* **Atomic Transaction (원자적 실행):** 가장 중요한 부분입니다. `Yes`만 사지고 `No`를 못 사면 손실이 발생합니다(Leg Risk).
* *방법 1 (스마트 컨트랙트):* Solidity로 커스텀 컨트랙트를 짜서 "두 토큰을 동시에 사는 함수"를 만들고, 봇은 이 함수를 호출합니다. 하나라도 실패하면 전체 트랜잭션이 취소(Revert)되므로 안전합니다.
* *방법 2 (FOK 주문):* API 레벨에서 Fill-Or-Kill(전량 체결 아니면 취소) 주문을 활용하되, 완벽한 동시성은 보장하기 어렵습니다.



---

### 3. Python 봇 구현 예시 (싱글 컨디션 중심)

이 코드는 개념 이해를 위한 스켈레톤 코드입니다. 실제 사용 시에는 `py-clob-client` 설정과 개인키 보안이 필요합니다.

```python
import asyncio
import os
from decimal import Decimal, getcontext
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, Side

# 정밀도 설정
getcontext().prec = 18

class PolyArbBot:
    def __init__(self):
        # API 클라이언트 초기화 (환경변수에서 키 로드)
        self.client = ClobClient(
            host="https://clob.polymarket.com",
            key=os.getenv("POLY_API_KEY"),
            chain_id=137  # Polygon Mainnet
        )
        self.min_profit_threshold = Decimal("0.02") # 최소 2센트 이득일 때만 실행

    async def on_market_update(self, market_id, orderbook):
        """
        WebSocket으로 오더북 업데이트가 들어올 때 실행되는 함수
        """
        # 1. 최저 매도 호가(Best Ask) 추출
        yes_asks = orderbook.get('yes', [])
        no_asks = orderbook.get('no', [])

        if not yes_asks or not no_asks:
            return

        best_yes_price = Decimal(yes_asks[0]['price'])
        best_no_price = Decimal(no_asks[0]['price'])

        # 2. 가격 불일치 계산 (수수료 제외 전 단순 합계)
        total_cost = best_yes_price + best_no_price
        
        # 3. 기회 포착 로직
        # 1.0(만기 상환액) - 총 비용 > 목표 수익
        potential_profit = Decimal("1.0") - total_cost
        
        if potential_profit > self.min_profit_threshold:
            print(f"[기회 포착] Market: {market_id}, Cost: {total_cost}, Exp. Profit: {potential_profit}")
            await self.execute_atomic_trade(market_id, best_yes_price, best_no_price)

    async def execute_atomic_trade(self, market_id, yes_price, no_price):
        """
        주문 실행 (Leg Risk 방지를 위해 가능한 빠르게 혹은 스마트 컨트랙트 호출)
        """
        print(">>> 주문 실행 중...")
        
        # 실제 구현 시: 
        # 1. 스마트 컨트랙트를 통한 Batch Buy (가장 안전)
        # 2. 또는 비동기 함수로 동시에 API 호출 (아래는 예시)
        
        task_buy_yes = self.place_order(market_id, Side.BUY, "Yes", yes_price)
        task_buy_no = self.place_order(market_id, Side.BUY, "No", no_price)
        
        # 동시에 주문 전송
        results = await asyncio.gather(task_buy_yes, task_buy_no, return_exceptions=True)
        self.check_execution_results(results)

    async def place_order(self, market_id, side, token_type, price):
        # py-clob-client를 이용한 주문 생성 로직
        # FOK (Fill or Kill) 옵션을 사용하여 부분 체결 방지 권장
        pass

    def check_execution_results(self, results):
        # 한쪽만 체결되었는지 확인하고, 그렇다면 즉시 청산(Hedge)하는 로직 필요
        pass

async def main():
    bot = PolyArbBot()
    # WebSocket 구독 로직 (py-clob-client의 스트리밍 기능 활용)
    # await bot.start_listening()
    print("봇 시작...")

if __name__ == "__main__":
    asyncio.run(main())

```

---

### 4. 구현 시 고려해야 할 심화 팁 (Tips from Text)

1. **가스비 최적화 (Polygon Gas):**
* Polygon 네트워크는 가스비가 저렴하지만, 아비트라지 경쟁이 심할 때는 가스비를 높게(Priority Fee) 설정해야 트랜잭션이 먼저 처리됩니다.
* 수익 계산 시 `(예상 수익) - (가스비)`가 마이너스가 되지 않도록 로직에 가스비 추정치(Oracle)를 포함하세요.


2. **원자성(Atomicity) 확보:**
* 위 코드처럼 Python `asyncio.gather`를 써도 네트워크 지연으로 한쪽만 체결될 수 있습니다.
* **고급 구현:** Solidity로 `ArbContract`를 배포하세요. 이 컨트랙트에 자금을 넣어두고, 봇은 "시장 ID와 가격"만 매개변수로 보내 `buyBothTokens()` 함수를 호출합니다. 컨트랙트 내부에서 두 토큰 구매를 시도하고, 하나라도 실패하면 `revert` 시키면 **무위험(Risk-free)** 실행이 가능합니다.


3. **오라클 및 리스크 관리:**
* **UMA Optimistic Oracle:** 폴리마켓은 UMA로 결과를 처리하는데, 분쟁(Dispute)이 발생하면 자금이 묶일 수 있습니다. 분쟁 가능성이 높은 애매한 주제의 시장은 블랙리스트 처리하여 봇이 건드리지 않게 하십시오.
* **자금 관리:** 한 거래에 올인하지 말고, 전체 시드의 10~20%씩만 진입하도록 설정하여 "Gambler's Ruin"을 방지하세요.


폴리마켓 아비트라지 봇의 **핵심 아키텍처**를 실무적인 관점에서 심층 분석해 드리겠습니다.

성공적인 아비트라지 봇은 단순히 "가격을 보고 주문을 넣는" 스크립트가 아니라, **나노초(ns) 또는 밀리초(ms) 단위의 경쟁을 처리하는 고성능 시스템**이어야 합니다.

전체 시스템은 크게 **① 데이터 수집 및 상태 관리**, **② 전략 판단 및 계산**, **③ 실행 및 트랜잭션 관리**의 3계층(Tier)으로 나뉩니다.

---

### [아키텍처 다이어그램]

```mermaid
graph TD
    subgraph "External World (Polymarket & Blockchain)"
        WS[Polymarket WebSocket] -->|Real-time Order Updates| I_Layer
        RPC[Polygon RPC Node] -->|Gas Price / Nonce| E_Layer
        SC[Smart Contract (Atomic Swap)] <-->|Execute Trade| E_Layer
    end

    subgraph "Bot Internal Architecture"
        subgraph "1. Ingestion Layer (Observer)"
            WS_H[WS Handler] -->|Raw Data| OB_M[Local Orderbook Manager]
        end
        
        subgraph "2. Strategy Layer (Brain)"
            OB_M -->|Snapshot| CALC[Oppotunity Calculator]
            CALC -->|Signal| FILTER[Risk & Profit Filter]
        end
        
        subgraph "3. Execution Layer (Actor)"
            FILTER -->|Trigger| TX_B[Tx Builder]
            TX_B -->|Signed Tx| TX_M[Tx Manager]
        end
    end
    
    TX_M -->|Broadcast| RPC

```

---

### 1. 데이터 수집 및 상태 관리 (Ingestion Layer)

이 계층의 목표는 **"네트워크 지연을 최소화하여 최신 시장 상황을 메모리에 복제하는 것"**입니다.

* **WebSocket Streamer (비동기 리스너)**
* **역할:** 폴리마켓 서버(CLOB)로부터 실시간 데이터(`OrderBook Update`, `Trade History`)를 수신합니다.
* **핵심 기술:** `asyncio`와 `websockets` 라이브러리를 사용하여 Non-blocking으로 구현해야 합니다. 연결이 끊기면 즉시 재접속하는 `Heartbeat/Reconnection` 로직이 필수입니다.


* **Local Orderbook Manager (로컬 오더북)**
* **중요:** API를 매번 호출해서 가격을 조회하면 이미 늦습니다.
* **구현:** 봇은 메모리 상에 폴리마켓의 호가창(Orderbook)을 그대로 복제한 객체(Dictionary 또는 Sorted Map)를 가지고 있어야 합니다.
* **동작:** WebSocket으로 들어오는 `Delta`(변경분) 데이터만 실시간으로 반영하여 로컬 오더북을 갱신합니다. 전략 엔진은 이 로컬 메모리를 조회하므로 지연시간이 '0'에 수렴합니다.



### 2. 전략 판단 및 계산 (Strategy Layer)

이 계층은 로컬 데이터를 바탕으로 **수익성을 수학적으로 검증**합니다.

* **Opportunity Calculator (기회 탐색기)**
* 로컬 오더북의 `Best Ask(최저 매도 호가)`를 기준으로 계산합니다.
* **공식:** 

* **최적화:** 단순히 `Yes`와 `No` 가격만 보는 것이 아니라, **Depth(깊이)**를 봐야 합니다.
* *예:* 100달러 수익 기회가 보여도, 매물(Liquidity)이 5달러치 밖에 없다면 가스비만 날립니다. "내가 먹을 수 있는 물량"까지 계산하는 로직이 필요합니다.




* **Risk Filter (리스크 필터)**
* **가스비 추정:** Polygon 네트워크의 현재 `BaseFee`와 `PriorityFee`를 실시간으로 조회하여 비용에 반영합니다.
* **중복 실행 방지:** 이미 주문이 들어간 마켓에 대해 중복으로 주문을 생성하지 않도록 `Pending` 상태를 관리합니다.



### 3. 실행 및 트랜잭션 관리 (Execution Layer)

가장 기술적인 난이도가 높은 부분으로, **Leg Risk(한쪽만 체결되는 위험)**를 기술적으로 제거해야 합니다.

* **Transaction Builder (트랜잭션 생성기)**
* 단순 API 호출이 아니라, **블록체인 트랜잭션(Raw Transaction)**을 직접 생성합니다.
* `web3.py`를 사용해 Nonce 관리, Gas Limit 설정, 서명(Signing)을 수행합니다.


* **Atomic Executor (원자적 실행기) - ★핵심**
* **문제점:** Python 코드에서 `API_Buy_Yes()` 하고 `API_Buy_No()`를 순차적으로 보내면, 첫 번째는 성공하고 두 번째는 가격 변동으로 실패할 수 있습니다. (이 경우 50% 확률의 도박 포지션이 되어버립니다.)
* **해결책 (Custom Smart Contract):**
1. `ArbBot`이라는 스마트 컨트랙트를 Polygon 네트워크에 미리 배포합니다.
2. 봇은 이 컨트랙트의 `executeArb(marketId, maxPriceYes, maxPriceNo)` 함수를 호출합니다.
3. **컨트랙트 내부 로직(Solidity):**
```solidity
function executeArb(...) public {
    // 1. CTF Exchange에서 Yes 토큰 구매 시도
    bool successYes = CTF.buy(yesToken, ...);
    // 2. CTF Exchange에서 No 토큰 구매 시도
    bool successNo = CTF.buy(noToken, ...);

    // 3. 둘 중 하나라도 조건(가격/수량) 안 맞으면 전체 취소
    require(successYes && successNo, "Leg risk detected! Reverting...");
}

```


4. 이렇게 하면 블록체인 레벨에서 **"둘 다 사지거나, 아무것도 안 사지거나"** 둘 중 하나만 발생하므로 리스크가 0이 됩니다.





### 4. 인프라 및 최적화 (Infrastructure)

* **RPC Node:** 공용 RPC(Polygon Public RPC)는 느리고 요청 제한이 있습니다. **Alchemy**나 **Infura**의 유료/전용 노드, 혹은 직접 구축한 노드를 사용해야 트랜잭션 전파 속도가 빠릅니다.
* **서버 위치:** 폴리마켓의 매칭 엔진 서버와 물리적으로 가까운 곳(AWS us-east-1 등)이나 Polygon 노드와 가까운 리전에 서버를 두는 것이 유리합니다.

---

### 💡 개발자를 위한 요약 (Next Step)

이 아키텍처를 구현하기 위해 지금 당장 필요한 작업 순서는 다음과 같습니다.

1. **Local Orderbook 구현:** `py-clob-client`의 WebSocket 예제를 변형하여, 데이터를 받아 화면에 출력하는 것이 아니라 Python `dict` 객체를 실시간 갱신하는 코드를 먼저 작성하세요.
2. **스마트 컨트랙트 작성:** Solidity로 간단한 `Atomic Swap` 컨트랙트를 작성하고 Remix 등을 통해 테스트넷(Amoy)에 배포해 보세요. (이 부분이 없으면 고수익 아비트라지는 불가능합니다.)



### 1. Local Orderbook을 왜 구현해야 하는가? (Why)

아비트라지 봇에서 **Local Orderbook(로컬 오더북)**은 선택이 아니라 **필수**입니다. 단순히 API를 호출하는 방식과 비교하면 다음과 같은 결정적인 차이가 있습니다.

#### ① 속도 (Latency)

* **API 호출 방식 (REST HTTP):** 가격을 확인할 때마다 서버에 요청을 보냅니다. 요청 → 서버 처리 → 응답까지 최소 **200ms ~ 500ms**가 걸립니다. 그 사이에 이미 다른 봇이 기회를 채가거나 가격이 변해버립니다.
* **로컬 오더북 방식 (WebSocket):** 서버가 변경 사항(누가 주문을 넣거나 뺐을 때)을 쏴주면(Push), 봇은 내 컴퓨터 메모리에 있는 장부를 갱신합니다. 전략을 계산할 때 내 메모리만 읽으면 되므로 소요 시간은 **수 마이크로초(µs)** 단위입니다.

#### ② API 제한 (Rate Limits)

* 폴리마켓 API는 초당 요청 횟수 제한이 있습니다. 수백 개의 시장을 감시해야 하는데, 매번 `GET /prices`를 호출하면 금방 차단당합니다.
* 로컬 오더북은 처음에만 연결하고 변경분만 받으므로 제한에 걸리지 않습니다.

#### ③ 데이터 정합성 (Accuracy)

* "내가 본 가격"과 "실제 체결될 가격"의 오차(Slippage)를 줄이려면, 호가창의 가장 최신 상태를 유지해야 합니다.

---

### 2. 어떻게 구현해야 하는가? (How)

로컬 오더북 구현의 핵심은 **"빠른 검색"**과 **"정렬 상태 유지"**입니다.

#### 핵심 자료구조: `SortedDict` (또는 B-Tree)

파이썬의 기본 `dict`는 순서가 보장되지 않고, `list`는 매번 정렬(sort)해야 해서 느립니다. 따라서 **입력과 동시에 가격순으로 자동 정렬**되는 자료구조가 필요합니다. 파이썬에서는 `sortedcontainers` 라이브러리가 표준처럼 쓰입니다.

* **Bids (매수):** 가격이 **높은** 순서대로 정렬 (비싸게 사겠다는 사람이 우선)
* **Asks (매도):** 가격이 **낮은** 순서대로 정렬 (싸게 팔겠다는 사람이 우선)

#### 구현 로직 흐름

1. **Snapshot (초기화):** 봇 시작 시 현재 호가창 전체를 한 번 받아옵니다.
2. **Delta (업데이트):** WebSocket을 통해 변경된 주문 정보가 들어옵니다.
* `price`, `size`, `side` 정보가 들어옴.
* **Size > 0:** 해당 가격에 주문 수량을 갱신(Update)하거나 새로 추가(Insert).
* **Size == 0:** 해당 가격의 주문이 사라졌으므로 삭제(Delete).



---

### 3. Python 구현 예시 코드

이 코드는 실무에서 바로 참고할 수 있는 로컬 오더북 클래스입니다.

**준비물:**

```bash
pip install sortedcontainers

```

**코드 (`orderbook.py`):**

```python
from decimal import Decimal
from sortedcontainers import SortedDict

class LocalOrderBook:
    def __init__(self):
        # Bids: 내림차순 정렬 (높은 가격이 먼저 와야 함 -> -가격으로 키 저장하거나 역순 순회)
        # 여기서는 편의상 오름차순으로 저장하고 가져올 때 뒤에서부터 가져옵니다.
        self.bids = SortedDict() 
        
        # Asks: 오름차순 정렬 (낮은 가격이 먼저 와야 함 -> 기본 동작)
        self.asks = SortedDict()

    def update(self, side: str, price: float, size: float):
        """
        WebSocket으로 들어온 데이터(Delta)를 처리하는 함수
        :param side: "BUY" or "SELL"
        :param price: 주문 가격
        :param size: 주문 잔량 (0이면 삭제)
        """
        price_dec = Decimal(str(price)) # 부동소수점 오차 방지
        size_dec = Decimal(str(size))

        # 대상 장부(Book) 선택
        book = self.bids if side.upper() == "BUY" else self.asks

        if size_dec == 0:
            # 수량이 0이면 해당 가격 레벨 삭제
            if price_dec in book:
                del book[price_dec]
        else:
            # 수량이 있으면 갱신 또는 추가
            book[price_dec] = size_dec

    def get_best_ask(self):
        """
        가장 싸게 팔겠다는 가격(Best Ask)과 수량 반환
        """
        if not self.asks:
            return None, None
        
        # SortedDict는 오름차순이므로 첫 번째 아이템이 최저가
        price, size = self.asks.peekitem(0) 
        return price, size

    def get_best_bid(self):
        """
        가장 비싸게 사겠다는 가격(Best Bid)과 수량 반환
        """
        if not self.bids:
            return None, None
        
        # 오름차순의 마지막 아이템이 최고가
        price, size = self.bids.peekitem(-1)
        return price, size

    def get_snapshot(self):
        """
        현재 오더북 상태 디버깅용
        """
        return {
            "best_bid": self.get_best_bid(),
            "best_ask": self.get_best_ask()
        }

# --- 사용 예시 ---
if __name__ == "__main__":
    book = LocalOrderBook()

    # 1. 초기 스냅샷 or 실시간 데이터 수신 상황 가정
    print("--- 데이터 수신 중 ---")
    book.update("SELL", 0.60, 100) # 0.60에 100개 매도 주문
    book.update("SELL", 0.59, 50)  # 0.59에 50개 매도 주문 (더 싼 가격 등장!)
    book.update("SELL", 0.61, 200)

    best_ask_price, best_ask_size = book.get_best_ask()
    print(f"현재 최저가 매도(살 수 있는 가격): ${best_ask_price}, 수량: {best_ask_size}")
    # 출력: $0.59, 수량: 50

    # 2. 누군가 0.59 물량을 다 사가서 수량이 0이 됨 (Update)
    print("\n--- 0.59 물량 체결됨 (삭제) ---")
    book.update("SELL", 0.59, 0) 

    best_ask_price, best_ask_size = book.get_best_ask()
    print(f"현재 최저가 매도(살 수 있는 가격): ${best_ask_price}, 수량: {best_ask_size}")
    # 출력: $0.60, 수량: 100 (자동으로 다음 호가로 변경됨)

```

### 4. 실제 적용 시 주의사항

1. **WebSocket 메시지 파싱:** 폴리마켓(Clob) WebSocket 메시지는 JSON 포맷으로 옵니다. 여기서 `price`, `size`, `side`를 추출해서 위 클래스의 `update` 메서드에 넣어주면 됩니다.
2. **데이터 타입:** 가격과 수량은 반드시 `Decimal`을 사용하세요. `float`를 쓰면 $0.1 + 0.2 = 0.30000000000000004` 같은 오차가 발생하여 아비트라지 계산이 틀리게 됩니다.
3. **시장별 관리:** 실제 봇은 여러 시장을 감시하므로 `Dict[MarketID, LocalOrderBook]` 형태의 딕셔너리로 수백 개의 오더북 인스턴스를 관리해야 합니다.

이제 이 `LocalOrderBook` 클래스를 WebSocket 클라이언트와 연결하는 부분이 필요합니다. **폴리마켓 WebSocket에 연결해서 데이터를 받아오는 코드**로 넘어가시겠습니까?


스마트 컨트랙트를 이용한 **Atomic Swap(여기서는 Atomic Batch Execution, 즉 일괄 실행을 의미)**은 아비트라지 봇의 **안전장치이자 핵심 엔진**입니다.

왜 이것이 필수적이며, 어떻게 작성하고 배포하는지 단계별로 설명해 드립니다.

---

### 1. 왜(Why) 스마트 컨트랙트가 필요한가?

파이썬 봇에서 API를 두 번 호출하는 것(`buy(Yes)`, `buy(No)`)과 스마트 컨트랙트를 쓰는 것의 차이는 **"도박이냐, 확정 수익이냐"**의 차이입니다.

#### ① Leg Risk (한쪽 다리만 걸치는 위험) 제거

* **API 방식:** `Yes`를 샀는데, 그 0.1초 사이에 `No` 가격이 폭등하거나 누군가 물량을 다 사가버리면? 당신은 `No`를 못 사고 `Yes`만 들고 있게 됩니다. 이건 아비트라지가 아니라 그냥 도박(Position Taking)이 되어버립니다.
* **스마트 컨트랙트:** `Yes 구매`와 `No 구매`를 하나의 트랜잭션으로 묶습니다. 블록체인의 특성상 트랜잭션 내의 명령은 **모두 성공하거나, 모두 실패(Revert)**합니다. `No` 구매가 실패하면 `Yes` 구매도 없던 일로 되돌려집니다. **원금 손실 위험이 0이 됩니다.**

#### ② 속도 경쟁 (Gas War)

* 남들보다 빠르게 트랜잭션을 처리하려면 가스비를 더 내야 합니다. 스마트 컨트랙트를 쓰면 여러 작업을 한 번의 트랜잭션으로 처리하므로 가스비 관리와 경쟁에서 훨씬 유리합니다.

#### ③ 테스트넷(Amoy) 배포 이유

* **비용:** 메인넷(Polygon)은 실수할 때마다 실제 돈(MATIC, USDC)이 나갑니다.
* **검증:** 논리적 오류(버그)가 있으면 아비트라지 과정에서 자금이 묶일 수 있습니다. Polygon의 공식 테스트넷인 **Amoy**에서 모의 토큰으로 충분히 연습해야 합니다.

---

### 2. 어떻게(How) 구현하는가? : Solidity 코드

가장 유연하고 강력한 방식은 **"일괄 실행(Batch Executor)"** 패턴입니다.
봇(Python)이 구체적인 매수 주문 데이터(Calldata)를 만들어서 컨트랙트에 넘겨주면, 컨트랙트는 묻지도 따지지도 않고 순서대로 실행만 합니다. 하나라도 실패하면 전체 취소됩니다.

#### Solidity 코드 예시 (`ArbExecutor.sol`)

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.18;

// ERC20 토큰(USDC 등)을 다루기 위한 인터페이스
interface IERC20 {
    function approve(address spender, uint256 amount) external returns (bool);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract ArbExecutor {
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    /**
     * @dev 여러 거래를 한 번에 실행하는 함수 (Atomic Batch Execution)
     * @param targets 호출할 대상 주소 배열 (예: 폴리마켓 거래소 주소)
     * @param data 각 대상에게 보낼 데이터 배열 (예: buy 함수 호출 데이터)
     * @param values 각 호출에 보낼 ETH 양 (USDC 거래면 보통 0)
     */
    function executeBatch(
        address[] calldata targets,
        bytes[] calldata data,
        uint256[] calldata values
    ) external payable onlyOwner {
        require(targets.length == data.length && data.length == values.length, "Length mismatch");

        for (uint256 i = 0; i < targets.length; i++) {
            // 외부 컨트랙트 호출 (Low-level call)
            (bool success, ) = targets[i].call{value: values[i]}(data[i]);
            
            // ★ 핵심: 하나라도 실패하면 전체 트랜잭션을 되돌림 (Revert)
            require(success, "Transaction failed: Leg risk detected");
        }
    }

    // 봇이 사용할 자금(USDC)을 출금하거나 관리하는 함수들
    function withdrawToken(address token, uint256 amount) external onlyOwner {
        IERC20(token).transfer(msg.sender, amount);
    }

    function withdrawETH() external onlyOwner {
        payable(msg.sender).transfer(address(this).balance);
    }
    
    // 입금 받기 위함
    receive() external payable {}
}

```

---

### 3. 배포 및 테스트 가이드 (Remix & Amoy)

이 과정은 개발 환경 설정과 배포 실습입니다.

#### 준비물

1. **Metamask 지갑:** 브라우저 확장 프로그램.
2. **Polygon Amoy Testnet 설정:**
* Metamask에 네트워크 추가:
* Network Name: `Polygon Amoy Testnet`
* RPC URL: `https://rpc-amoy.polygon.technology/` (또는 Alchemy/Infura 사용)
* Chain ID: `80002`
* Currency Symbol: `POL`




3. **테스트넷 토큰(Faucet):** [Polygon Faucet](https://faucet.polygon.technology/) 사이트에서 무료 POL(가스비용)을 받습니다.

#### 배포 단계 (Remix IDE 사용)

1. **Remix 접속:** [remix.ethereum.org](https://www.google.com/search?q=https://remix.ethereum.org) 로 이동합니다.
2. **파일 생성:** `contracts` 폴더에 `ArbExecutor.sol`을 만들고 위 코드를 붙여넣습니다.
3. **컴파일 (Compile):**
* 좌측 메뉴의 'Solidity Compiler' 아이콘 클릭.
* `Compile ArbExecutor.sol` 버튼 클릭 (파란색 체크가 뜨면 성공).


4. **배포 (Deploy):**
* 좌측 메뉴의 'Deploy & Run Transactions' 아이콘 클릭.
* **Environment:** `Injected Provider - MetaMask` 선택 (메타마스크가 Amoy 네트워크인지 확인).
* **Contract:** `ArbExecutor` 선택.
* `Deploy` 버튼 클릭 -> 메타마스크 승인.


5. **확인:**
* 하단 'Deployed Contracts'에 배포된 컨트랙트 주소가 뜹니다. 이 주소(`0x...`)를 복사해두세요. 이것이 당신의 **봇 전용 지갑** 역할을 합니다.



---

### 4. Python 봇과의 연동 (개념)

이제 Python 봇은 직접 매수 함수를 호출하는 것이 아니라, **"매수 주문서"를 만들어서 이 컨트랙트에게 전달**합니다.

```python
# Python Bot Pseudo-code

# 1. 구매하고 싶은 주문 데이터(Calldata) 생성
# web3.py 등을 이용해 Polymarket Exchange 컨트랙트의 buy() 함수 호출 데이터 생성
tx_data_yes = polymarket_contract.encodeABI(fn_name="buy", args=[...Yes Token Args...])
tx_data_no = polymarket_contract.encodeABI(fn_name="buy", args=[...No Token Args...])

# 2. 내 컨트랙트(ArbExecutor)의 executeBatch 함수 호출
my_contract.functions.executeBatch(
    targets=[polymarket_exchange_address, polymarket_exchange_address], # 대상은 동일
    data=[tx_data_yes, tx_data_no], # 실행할 명령들
    values=[0, 0]
).transact({'from': my_wallet_address})

```

### 요약 및 다음 단계

1. **Revert의 마법:** 위 Solidity 코드의 `require(success)` 한 줄이 당신의 자산을 보호하는 핵심입니다. `Yes`는 사졌는데 `No`가 실패하면, 블록체인이 시간을 되돌려 `Yes` 구매도 없던 일로 만듭니다.
2. **테스트:** Amoy 테스트넷에서 가짜 토큰으로 이 `executeBatch`가 잘 작동하는지(하나가 실패했을 때 전체가 취소되는지) 확인해야 합니다.

이제 **Python 봇이 이 컨트랙트에 보낼 `Calldata`(주문 데이터)를 만드는 방법**을 알아야 실제로 주문을 넣을 수 있습니다. 이 부분(Web3.py 활용법)을 설명해 드릴까요?