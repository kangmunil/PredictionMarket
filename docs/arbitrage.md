**폴리마켓(Polymarket)의 CLOB(Central Limit Order Book) API를 활용한 차익거래(Arbitrage) 봇**을 개발

https://docs.polymarket.com/developers/CLOB/introduction
https://docs.polymarket.com/developers/CLOB/quickstart
https://docs.polymarket.com/developers/CLOB/authentication
https://docs.polymarket.com/developers/CLOB/geoblock
https://docs.polymarket.com/developers/CLOB/clients/methods-overview
https://docs.polymarket.com/developers/CLOB/clients/methods-public
https://docs.polymarket.com/developers/CLOB/clients/methods-l1
https://docs.polymarket.com/developers/CLOB/clients/methods-l2
https://docs.polymarket.com/developers/CLOB/clients/methods-builder
https://docs.polymarket.com/api-reference/orderbook/get-order-book-summary
https://docs.polymarket.com/api-reference/orderbook/get-multiple-order-books-summaries-by-request
https://docs.polymarket.com/api-reference/pricing/get-market-price
https://docs.polymarket.com/api-reference/pricing/get-multiple-market-prices
https://docs.polymarket.com/api-reference/pricing/get-multiple-market-prices-by-request
https://docs.polymarket.com/api-reference/pricing/get-midpoint-price
https://docs.polymarket.com/api-reference/pricing/get-price-history-for-a-traded-token
https://docs.polymarket.com/api-reference/spreads/get-bid-ask-spreads
https://docs.polymarket.com/developers/CLOB/timeseries
https://docs.polymarket.com/developers/CLOB/orders/orders
https://docs.polymarket.com/developers/CLOB/orders/create-order
https://docs.polymarket.com/developers/CLOB/orders/create-order-batch
https://docs.polymarket.com/developers/CLOB/orders/get-order
https://docs.polymarket.com/developers/CLOB/orders/get-active-order
https://docs.polymarket.com/developers/CLOB/orders/check-scoring
https://docs.polymarket.com/developers/CLOB/orders/cancel-orders
https://docs.polymarket.com/developers/CLOB/orders/onchain-order-info
https://docs.polymarket.com/developers/CLOB/trades/trades-overview
https://docs.polymarket.com/developers/CLOB/trades/trades
https://docs.polymarket.com/developers/CLOB/websocket/wss-overview
https://docs.polymarket.com/quickstart/websocket/WSS-Quickstart
https://docs.polymarket.com/developers/CLOB/websocket/wss-auth
https://docs.polymarket.com/developers/CLOB/websocket/user-channel
https://docs.polymarket.com/developers/CLOB/websocket/market-channel
https://docs.polymarket.com/developers/RTDS/RTDS-overview
https://docs.polymarket.com/developers/RTDS/RTDS-crypto-prices
https://docs.polymarket.com/developers/RTDS/RTDS-comments

**"시장(Market) 정보를 조회하여, 베팅 가능한 토큰(YES/NO)의 ID를 식별하는 전처리 과정"**을 다루고 있습니다. 이는 봇 개발의 가장 기초이자 필수적인 부분입니다.

공유해주신 텍스트의 **전략 1번(단순 차익거래: YES+NO < $1)**을 목표로 잡고, 개발 로드맵을 정리해 드리겠습니다.

---

### 1. 전체 시스템 아키텍처

봇은 크게 세 가지 모듈로 구성됩니다. 이미지 속 코드는 **1번 모듈**에 해당합니다.

1. **Data Collector (데이터 수집기):** 시장 정보를 가져오고 거래할 토큰 ID(`token_id`)를 파악합니다. (업로드하신 코드의 역할)
2. **Strategy Engine (전략 엔진):** 실시간 호가창(Orderbook)을 모니터링하다가 `YES 매수가 + NO 매수가 < $1` (수수료 포함)인 순간을 포착합니다.
3. **Execution Client (주문 실행기):** 포착 즉시 서명된 트랜잭션으로 매수 주문을 전송합니다.

---

### 2. 단계별 개발 가이드

#### Step 1. 개발 환경 및 필수 라이브러리 설정

폴리마켓은 Polygon 네트워크 기반이며, 주문은 오프체인(CLOB)으로 처리되지만 정산은 온체인입니다.

* **언어:** Python (FastAPI/Asyncio 추천 - 속도가 생명)
* **핵심 라이브러리:**
* `py-clob-client`: 폴리마켓 공식 Python SDK (주문 및 서명 처리).
* `aiohttp`: 비동기 API 요청 (공유해주신 코드에서도 `await _try_get_json`을 쓰는 것으로 보아 이미 비동기 구조로 짜고 계신 듯합니다).
* `web3.py`: 지갑 서명 및 블록체인 상호작용.



#### Step 2. 시장 데이터 파싱 (이미지 코드 활용)

감마(Gamma - 폴리마켓의 데이터 API)나 CLOB API에서 받은 지저분한 JSON 응답에서 깔끔하게 `YES_TOKEN_ID`와 `NO_TOKEN_ID`를 추출하는 로직입니다.

* **역할:** API마다 데이터 구조가 (`question`, `outcomes`, `tokens` 등) 제각각인데, 이를 정규화하여 **"어떤 토큰을 사야 하는지"** ID를 확보합니다.
* **개발 포인트:** 이 함수들을 활용해 모니터링할 시장 리스트(예: "Crypto", "Politics" 카테고리의 상위 볼륨 시장)의 ID 맵(Map)을 메모리에 캐싱해둬야 합니다. 매번 API를 호출하면 늦습니다.

#### Step 3. 전략 로직 구현 (Strategy #1: YES/NO Arbitrage)

가장 구현하기 명확한 1번 전략의 핵심 로직입니다.

1. **호가창 조회:** `GET /book` 엔드포인트를 1~3초(또는 더 빠르게) 간격으로 폴링합니다.
2. **가격 계산:**
* `Best Ask (YES)`: YES 토큰을 즉시 살 수 있는 최저가
* `Best Ask (NO)`: NO 토큰을 즉시 살 수 있는 최저가


3. **진입 조건:**


* *예: YES(0.48) + NO(0.49) = 0.97*
* *이익: 1.0 - 0.97 = $0.03 (확정 수익)*


4. **주문 실행:** 조건 만족 시 **동시에** YES와 NO를 시장가(또는 최우선 지정가)로 매수합니다.

#### Step 4. 주문 실행 (Execution)

속도가 생명인 경쟁 시장이므로 `py-clob-client`를 사용하여 미리 서명된(Pre-signed) 주문을 날리거나, API 키를 통해 빠르게 주문을 넣어야 합니다.

---

### 3. 개발 시 주의사항 (Real World Tips)

사용자님은 개발자이시므로 아래의 기술적 디테일이 중요할 것입니다.

1. **Rate Limit 관리:** 폴리마켓 API는 요청 제한이 있습니다. 무턱대고 `while True`로 요청하면 밴 당합니다. 여러 API 키를 로테이션하거나, WebSocket을 지원하는 엔드포인트가 있다면 소켓 연결을 우선하세요.
2. **경쟁자 (MEV/Bots):** 텍스트에 나온 대로 이미 많은 봇이 돌아가고 있습니다. 파이썬 스크립트의 실행 속도(Latency)를 줄이는 것이 관건입니다.
* AWS나 Google Cloud의 도쿄/미국 리전(폴리마켓 서버 위치와 가까운 곳)에 VPS를 구축하는 것이 유리합니다.


3. **유동성(Liquidity) 확인:** 가격 조건(`합 < 1`)이 맞더라도, 해당 가격에 걸린 물량(Size)이 너무 적으면 수수료만 나가고 체결이 안 될 수 있습니다. 호가창의 `size`도 반드시 조건문에 넣어야 합니다.

### 4. 다음 단계 제안

사용자님이 공유해주신 코드(`resolve_outcome_token_ids`)는 데이터를 가져오는 부분은 잘 짜여 있습니다. 이제 **실제 가격을 비교하고 주문을 넣는 루프(Loop)**가 필요합니다.

**다음으로 "전략 1번(YES+NO 차익거래)"을 수행하는 구체적인 파이썬 코드 예시(스켈레톤 코드)를 작성해 드릴까요?** (공유해주신 함수들과 `py-clob-client`를 어떻게 연결하는지 보여드릴 수 있습니다.)