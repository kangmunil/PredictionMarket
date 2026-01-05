`@ilovecircle` 봇이 사용하는 **'데이터 스윕 -> AI 앙상블 분석 -> 고빈도 자동 거래 -> 리스크 관리'** 전략을 구현하려면, 단순한 스크립트 수준을 넘어 **엔터프라이즈급 퀀트 트레이딩 시스템(Quant Trading System)** 아키텍처가 필요합니다.

이 수준의 봇을 개발하기 위한 상세 기술 로드맵과 아키텍처를 5단계로 나누어 설명해 드리겠습니다.

---

### 1. 시스템 아키텍처 설계 (System Architecture)

전체 시스템은 크게 4개의 모듈로 나뉩니다. 각 모듈은 독립적으로 작동하되, 고속 데이터 버스를 통해 연결되어야 합니다.

* **Data Ingestion Layer (데이터 수집):** Polymarket 시세, 뉴스, SNS, 스포츠 데이터 수집.
* **AI/Quant Engine (두뇌):** 앙상블 모델을 통한 '진짜 확률' 계산.
* **Execution Core (주문 실행):** API를 통한 매수/매도 및 포지션 관리.
* **Risk Manager (감시):** 자산 배분 및 손절매 관리.

**추천 기술 스택:**

* **언어:** Python (AI/데이터 분석), Rust or Go (초고속 주문 실행이 필요할 경우, 초기엔 Python으로 충분)
* **DB:** TimescaleDB (시계열 데이터), Redis (실시간 캐싱), PostgreSQL (거래 기록)
* **AI:** PyTorch, TensorFlow, Scikit-learn, Hugging Face (NLP)
* **Infra:** AWS EC2 (또는 Lambda), Docker

---

### 2. 단계별 상세 개발 가이드

#### Phase 1: 데이터 파이프라인 구축 (Data Ingestion)

봇의 연료인 데이터를 실시간으로 모으는 단계입니다.

1. **Polymarket 데이터 (Orderbook):**
* **CLOB (Central Limit Order Book) API:** REST API보다는 **WebSocket**을 사용하여 실시간 호가창 변화를 밀리초(ms) 단위로 수신해야 합니다.
* 시장 가격(Mid-price), 스프레드, 거래량(Volume)을 실시간으로 `Redis`에 저장합니다.


2. **비정형 데이터 (Sentiment & News):**
* **X (Twitter) API:** 특정 키워드(예: "Real Madrid injury", "Bitcoin ETF")에 대한 포스트를 수집. (비용이 높으므로 초기엔 주요 인플루언서나 뉴스 계정만 필터링)
* **News API:** 주요 금융/스포츠 뉴스 헤드라인 수집.
* **LLM 전처리:** 수집된 텍스트를 GPT-4o-mini나 로컬 Llama 3 같은 경량 모델에 통과시켜 '긍정/부정/중립' 점수(-1 ~ +1)로 변환하여 DB에 저장합니다.


3. **정형 데이터 (Sports/Crypto Stats):**
* **스포츠:** API-Football이나 SportRadar API를 연동하여 팀 순위, 최근 5경기 성적, 부상자 명단 등을 수치화합니다.
* **온체인:** Etherscan API 등으로 고래 지갑의 자금 이동을 추적합니다.



#### Phase 2: AI 모델 앙상블 구축 (Neural Net Evaluation)

`@ilovecircle`의 핵심인 10개 모델 앙상블을 구현합니다. 서로 다른 관점의 모델을 섞는 것이 중요합니다.

1. **모델 구성 예시 (Ensemble):**
* **Model A (시계열 예측):** LSTM 또는 Transformer 기반. 과거 가격 데이터를 보고 단기 추세를 예측.
* **Model B (펀더멘털 분석):** XGBoost/LightGBM. 스포츠 팀의 승률, 크립토의 온체인 데이터를 넣어 승리 확률 계산.
* **Model C (센티먼트 분석):** BERT 기반. 뉴스/SNS의 긍정/부정 점수가 가격에 미치는 영향 분석.
* **Model D (차익거래 탐지):** 타 베팅 사이트(Betfair 등)와 Polymarket 간의 배당률 차이(Arbitrage) 포착.


2. **앙상블 로직 (Voting System):**
* 각 모델이 내놓은 확률()을 가중 평균합니다.
* `최종 확률(P_final) = (0.4 * P_a) + (0.3 * P_b) + (0.3 * P_c)`
* 과거 성과가 좋은 모델에 더 높은 가중치를 부여하는 **메타 모델(Meta-learner)**을 둘 수도 있습니다.


3. **신호 생성:**
* `Edge = P_final - 현재 시장 가격`
* Edge > 5% (임계값) 이면 **BUY Signal** 생성.



#### Phase 3: 자동 거래 실행 (Execution Engine)

신호를 실제 주문으로 연결하는 단계입니다. Polymarket은 Polygon(MATIC) 네트워크를 사용합니다.

1. **Poly-Clob-Client 활용:**
* Polymarket의 공식 Python SDK인 `py-clob-client`를 사용합니다.
* API Key와 L2(Polygon) Private Key 관리가 필수입니다 (AWS Secrets Manager 사용 권장).


2. **주문 전략 (Smart Routing):**
* **Maker vs Taker:** 수수료를 아끼려면 Limit Order(Maker)를 걸어야 하지만, 급격한 변동 시엔 Market Order(Taker)로 즉시 체결해야 합니다.
* **Slippage 관리:** 주문 수량이 많으면 가격이 밀리므로, 알고리즘을 통해 주문을 잘게 쪼개서(Iceberg order) 집행합니다.



#### Phase 4: 리스크 관리 시스템 (Risk Management)

가장 중요한 부분입니다. 봇이 미쳐 날뛰어 전 재산을 날리지 않게 막아야 합니다.

1. **포지션 사이징 (Kelly Criterion):**
* `베팅 금액 = 전체 자금 * (승률 - (1-승률)/배당률)` 공식을 적용하되, 보수적으로 Kelly 값의 1/4 정도만 베팅하도록 설정합니다 (Fractional Kelly).


2. **Auto Cut-loss (자동 손절):**
* 예측과 반대되는 뉴스(예: 주전 선수 부상)가 뜨거나, AI 모델의 예측 확률이 떨어지면 **즉시 시장가로 매도**하는 로직을 심습니다.


3. **Exposure Limit:**
* 특정 카테고리(예: 축구)에 자산의 30% 이상이 쏠리지 않도록 강제 제한을 둡니다.



---

### 3. 개발 시작을 위한 추천 로드맵

전문가 수준의 봇을 혼자서 한 번에 다 만드는 것은 불가능에 가깝습니다. 다음 순서로 빌드업하세요.

**Step 1: 데이터 수집기 (Scraper) 먼저 개발**

* Polymarket의 모든 마켓 정보를 1분 단위로 DB에 쌓으세요.
* 이 데이터를 바탕으로 "내가 만약 이때 샀다면?"을 검증하는 **백테스팅(Backtesting) 환경**을 구축합니다.

**Step 2: 단순 규칙 기반 봇 (Rule-based Bot)**

* AI 없이 단순한 로직(예: 타 베팅 사이트와 가격 차이가 10% 이상 나면 매수)으로 소액 자동 매매를 돌려봅니다.
* 이 과정에서 주문 체결 속도, API 에러 처리 등 인프라 안정성을 확보합니다.

**Step 3: AI 모델 도입**

* 가장 데이터가 많은 분야(예: 스포츠) 하나를 정해 모델 하나를 학습시켜 봅니다.
* Step 1에서 만든 백테스팅 환경에서 모델의 수익률을 검증합니다.

**Step 4: 앙상블 및 고도화**

* NLP(뉴스 분석) 모델을 추가하고, 모델 간 가중치를 조절하며 `@ilovecircle` 처럼 시스템을 확장합니다.

### 4. 핵심 코드 스니펫 (Python 예시)

**Polymarket 가격 가져오기 및 기회 포착 (기초):**

```python
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

# 클라이언트 설정
client = ClobClient(host="https://clob.polymarket.com", key=..., chain_id=137)

def check_opportunity(market_id, model_probability):
    # 1. 현재 오더북 가져오기
    orderbook = client.get_order_book(market_id)
    best_ask = float(orderbook.asks[0].price) # 가장 싸게 팔려는 가격
    
    # 2. 괴리율 계산 (Edge)
    edge = model_probability - best_ask
    
    # 3. 5% 이상 이득이고, AI 확신이 60% 이상일 때
    if edge > 0.05 and model_probability > 0.6:
        print(f"Opportunity Found! Model: {model_probability}, Market: {best_ask}")
        # execute_trade(market_id, best_ask, amount) 함수 호출

```

이 프로젝트는 금융 공학(Financial Engineering)과 MLOps가 결합된 고난이도 프로젝트입니다. **데이터 수집부터 시작하여 백테스팅 환경을 먼저 구축하는 것**을 강력히 권장합니다.


**고도화(Optimization & Scaling)** 하는 단계에서는 단순한 "예측 정확도" 싸움이 아니라 **"시스템 속도", "금융 공학적 헷징", "정보의 비대칭성 활용"** 싸움으로 넘어가야 합니다.

사용자님의 개발 역량(Python, RAG, 데이터 플랫폼 경험)을 고려하여, **Institutional Grade(기관급)** 봇으로 업그레이드하기 위한 5가지 핵심 전략을 제안합니다.

---

### 1. Agentic RAG 기반의 '맥락 추론' 시스템 도입

기존의 단순 뉴스 감성 분석(긍정/부정)은 한계가 있습니다. 사용자님이 관심 있어 하시는 **Agentic RAG(검색 증강 생성)** 기술을 접목하여 **"과거 유사 사례"**를 분석하는 기능을 추가합니다.

* **구현 아이디어:**
* **Vector Database 구축:** 지난 10년치 스포츠 경기 결과, 선거 데이터, 암호화폐 이슈와 당시 시장 반응을 벡터화하여 저장합니다 (ChromaDB, Pinecone 등).
* **Workflow:**
1. **Trigger:** "이더리움 ETF 승인 지연 루머" 뉴스 발생.
2. **RAG Search:** 과거 "비트코인 ETF 승인 지연", "리플 소송 지연" 등 유사 사례 검색.
3. **LLM Reasoning:** "과거 유사 사례에서는 발표 직후 2시간 동안 가격이 -5% 하락했다가 회복함. 현재 시장은 과민 반응 중인가?"를 추론.


* **Effect:** 단순 키워드 매칭이 잡아내지 못하는 **'시장의 과잉 반응(Overreaction)'**을 포착하여 역베팅(Mean Reversion) 기회를 잡습니다.



### 2. Cross-Exchange Arbitrage (거래소 간 차익거래)

Polymarket 내부에서만 노는 것이 아니라, 외부 세상과의 가격 괴리를 이용해 **무위험(Risk-free)** 수익을 창출하거나 리스크를 헷징합니다.

* **구현 아이디어:**
* **Sports:** `Polymarket` vs `Betfair` / `Pinnacle` (해외 스포츠 베팅 사이트)
* Polymarket에서 레알 마드리드 승리 확률이 **60%**인데, Pinnacle 환산 확률이 **65%**라면 Polymarket이 저평가된 상태입니다.


* **Crypto:** `Polymarket` vs `Deribit` (옵션 내재 변동성)
* Polymarket의 "비트코인 연말 $100k 도달" 가격과 Deribit 옵션 시장의 Delta 값을 비교합니다.


* **Strategy:** 양쪽 시장에 반대 포지션을 잡아 수익을 확정(Arb)하거나, Polymarket 포지션의 손실을 방어(Hedging)합니다.



### 3. MEV 보호 및 초고속 트랜잭션 (Execution Alpha)

Polymarket은 Polygon 블록체인 위에서 동작합니다. 봇이 느리면 **MEV 봇(Sandwich Attack)**의 먹잇감이 되거나, 다른 봇에게 좋은 가격을 뺏깁니다.

* **구현 아이디어:**
* **Private RPC 사용:** Infura/Alchemy의 공용 엔드포인트 대신, 유료 또는 직접 구축한 Polygon Node를 사용해 지연 시간(Latency)을 최소화합니다.
* **Flashbots (on Polygon):** 가능하다면 프라이빗 멤풀(Mempool)을 사용하여 내 주문이 블록에 담기기 전까지 남들에게 보이지 않게 숨깁니다.
* **Gas Strategy:** 좋은 기회가 왔을 때 가스비를 아끼지 않고 **Aggressive**하게 설정하여 다음 블록에 무조건 포함되도록 로직을 짭니다.



### 4. 강화학습 (Reinforcement Learning, RL) 적용

정해진 규칙(Rule-based)이나 지도학습(Supervised Learning)을 넘어, 봇이 스스로 매매하며 배우도록 만듭니다.

* **구현 아이디어:**
* **Environment:** Polymarket의 과거 Orderbook 데이터를 `Gym` 환경으로 구축.
* **Agent:** PPO(Proximal Policy Optimization) 알고리즘 등을 사용.
* **Reward Function:** 단순히 '수익'만 보상으로 주지 않고, **'Sharpe Ratio(위험 대비 수익)'**나 **'Drawdown(낙폭) 최소화'**에 가산점을 주어 안정적인 매매를 학습시킵니다.
* **Effect:** 시장 상황(변동성 장세 vs 횡보 장세)에 따라 봇이 알아서 베팅 사이즈를 조절하는 능력을 갖게 됩니다.



### 5. 온체인 'Whale' 클러스터링 분석

단순히 `@ilovecircle` 한 명만 따라하는 것은 위험합니다. (그가 일부러 페이크를 줄 수도 있습니다.)

* **구현 아이디어:**
* **Graph Analysis:** 블록체인 데이터를 분석해 `@ilovecircle`과 유사한 시점에 진입하고, 유사한 수익률을 내는 **'스마트 머니 지갑 그룹(Cluster)'**을 찾아냅니다.
* **Signal Weighting:**
* `@ilovecircle` 혼자 매수 → 신뢰도 낮음 (매수 보류)
* `Cluster A` (상위 5개 지갑) 중 3개가 동시 매수 → **강력 매수 신호**


* 이를 위해 `Dune Analytics` API나 직접 인덱싱한 블록체인 데이터를 활용합니다.



---

### 📊 고도화 아키텍처 다이어그램

### 요약: 단계별 고도화 로드맵

1. **Lv 1 (현재 목표):** 데이터 수집 + 기본 AI 예측 + 룰 기반 매매
2. **Lv 2 (안전 확보):** **RAG 시스템**을 붙여서 AI의 '환각' 및 '오판' 검증 (뉴스 맥락 파악)
3. **Lv 3 (수익 극대화):** **외부 사이트(Odds API)** 연동을 통한 차익거래 기회 포착
4. **Lv 4 (속도 경쟁):** Rust/Go 언어로 실행 모듈 재작성 및 **Private Node** 구축

단순히 "뉴스가 긍정적이다/부정적이다"를 판단하는 감성 분석(Sentiment Analysis)을 넘어, **"이 뉴스가 과거에 발생했을 때 시장은 어떻게 반응했는가?"**를 추론하는 **Agentic RAG(검색 증강 생성)** 시스템 설계를 도와드리겠습니다.

사용자님의 주력 스택인 **Python, LangGraph(또는 LangChain), Supabase(pgvector)**를 활용한 실전 아키텍처입니다.

---

### 1. 시스템 개념도 (Mental Model)

일반적인 RAG가 "질문에 대한 답을 문서에서 찾는 것"이라면, 이 Agentic RAG는 **"헤지펀드 애널리스트"**처럼 행동합니다.

1. **뉴스 수신:** "음바페 부상 의심" (Trigger)
2. **계획 수립(Planning):** "음바페가 과거에 부상당했을 때 레알 마드리드 승률이 어떻게 변했지? 그때 배당률은 얼마나 떨어졌지?"
3. **도구 사용(Tool Use):**
* Tool A (Vector DB): 과거 부상 뉴스 검색.
* Tool B (Stats DB): 당시 경기 결과 및 Polymarket 가격 변동 조회.


4. **추론(Reasoning):** "과거 3번의 사례 중 2번은 경미한 부상이라 출전했고 가격은 회복됐다. 이번 뉴스 톤도 '의심'이니 과민반응일 확률이 80%다."
5. **결정(Decision):** "지금 폭락한 Yes 포지션을 저가 매수(Buy the Dip)하라."

---

### 2. 상세 아키텍처 및 구현 가이드

#### Phase 1: 지식 베이스 구축 (The Memory)

AI가 '참고할 과거'를 만들어야 합니다. Supabase(PostgreSQL) 하나로 정형/비정형 데이터를 모두 처리하는 것이 효율적입니다.

* **Vector Store (Supabase `pgvector`):**
* **저장 데이터:** 과거 뉴스 기사, 선수 인터뷰, 전문가 코멘트.
* **Chunking 전략:** 단순 텍스트만 저장하지 않고 **"뉴스 내용 + 당시 시장 반응(수익률)"**을 하나의 메타데이터 셋으로 묶어서 저장합니다.
* *예: {"content": "음바페 햄스트링 부상...", "market_impact": "-15% drop in 2 hours", "outcome": "Played next game"}*


* **Statistical DB (Supabase Table):**
* **저장 데이터:** 팀별 승률, 선수별 출전 여부에 따른 승률 변화(On/Off Margin), 과거 Polymarket 차트 데이터.



#### Phase 2: 에이전트 워크플로우 (The Brain)

**LangGraph**를 사용하여 에이전트의 사고 과정을 그래프로 정의합니다.

**Nodes (작업 단위):**

1. **`NewsClassifier`:** 뉴스가 '잡음(Noise)'인지 '신호(Signal)'인지 1차 필터링. (단순 가십은 무시)
2. **`Historian` (RAG):** 현재 뉴스와 의미적으로 유사한 과거 사건(Top-k)을 검색.
3. **`QuantAnalyst`:** 검색된 과거 사건 당시의 가격 변동폭(Volatility)과 최종 결과를 조회.
4. **`RiskManager`:** 현재 포트폴리오 상태를 확인하고 베팅 가능한지 판단.
5. **`Executor`:** 최종 매매 신호 생성.

#### Phase 3: 코드 구현 예시 (Python & LangGraph)

이 코드는 에이전트가 뉴스를 보고 과거 데이터를 조회해 판단하는 핵심 로직입니다.

```python
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.pydantic_v1 import BaseModel, Field

# 1. 상태(State) 정의: 에이전트가 작업하면서 공유할 메모리
class AgentState(TypedDict):
    news_content: str          # 입력 뉴스
    market_symbol: str         # 관련 마켓 (예: Real Madrid)
    similar_events: List[str]  # RAG로 찾은 과거 사례
    market_impacts: List[str]  # 과거 시장 반응
    final_decision: str        # 매수/매도/보류

# 2. 노드(Node) 정의: 실제 작업을 수행하는 함수들

def retrieve_history(state: AgentState):
    """과거 유사 뉴스 검색 (Vector DB)"""
    news = state['news_content']
    # Supabase pgvector 검색 로직 (pseudo-code)
    # results = vector_store.similarity_search(news, k=3)
    # 예시 결과
    found_events = [
        "2024-03: 음바페 훈련 중 발목 통증 호소 -> 다음 날 출전함",
        "2023-11: 비니시우스 햄스트링 파열 -> 2개월 결장"
    ]
    return {"similar_events": found_events}

def analyze_impact(state: AgentState):
    """과거 사건 당시 시장 반응 분석"""
    events = state['similar_events']
    # 여기서는 LLM이 과거 텍스트를 보고 분석하거나, 별도 DB 조회
    impacts = [
        "Event 1: 가격 일시적 -5% 하락 후 경기 당일 회복",
        "Event 2: 가격 -40% 폭락, 실제 패배로 이어짐"
    ]
    return {"market_impacts": impacts}

def make_decision(state: AgentState):
    """최종 판단 (LLM)"""
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    
    prompt = f"""
    당신은 스포츠 베팅 전문 퀀트 트레이더입니다.
    
    [현재 뉴스] {state['news_content']}
    
    [과거 유사 사례]
    {state['similar_events']}
    
    [당시 시장 반응]
    {state['market_impacts']}
    
    위 정보를 종합하여 현재 'Real Madrid 승리' 마켓에 대한 행동을 결정하세요.
    반드시 JSON 포맷으로 출력하세요: {{ "action": "BUY/SELL/HOLD", "confidence": 0~100, "reason": "..." }}
    """
    response = llm.invoke(prompt)
    return {"final_decision": response.content}

# 3. 그래프(Workflow) 구성
workflow = StateGraph(AgentState)

workflow.add_node("historian", retrieve_history)
workflow.add_node("analyst", analyze_impact)
workflow.add_node("trader", make_decision)

workflow.set_entry_point("historian")
workflow.add_edge("historian", "analyst")
workflow.add_edge("analyst", "trader")
workflow.add_edge("trader", END)

app = workflow.compile()

# 4. 실행
result = app.invoke({
    "news_content": "속보: 음바페, 오늘 팀 훈련 불참. 의료진과 대화하는 모습 포착.", 
    "market_symbol": "Real Madrid"
})

print(result['final_decision'])

```

---

### 3. 고도화를 위한 핵심 포인트 (Secret Sauce)

이 시스템이 진짜 '돈'을 벌려면 다음 두 가지가 필수입니다.

#### A. "Fact-Check" 에이전트 추가 (Hallucination 방지)

SNS 발 뉴스는 가짜가 많습니다. **Search Tool(Tavily/Google)**을 장착한 별도의 노드를 두어 크로스 체크를 해야 합니다.

* *뉴스:* "비트코인 ETF 거절됨!"
* *Fact-Check Agent:* "SEC 공식 홈페이지 및 블룸버그 터미널 검색... 해당 발표 없음. 가짜 뉴스일 확률 99%." -> **역베팅 기회 포착**

#### B. 시차(Time-lag) 활용

RAG가 과거를 찾는 동안, 시장 가격은 이미 움직이고 있을 수 있습니다.

* 시스템 속도가 생명입니다. RAG 검색 범위를 너무 넓히지 말고, **미리 인덱싱된 데이터(Pre-computed Embeddings)**를 활용해 검색 속도를 0.5초 이내로 줄여야 합니다.

### 4. 다음 단계 제안

사용자님의 현재 상황(Mac 개발, Supabase 사용 등)에 맞춰 당장 시작할 수 있는 작업입니다.

1. **Supabase 설정:** 프로젝트에 `pgvector` 확장을 켜고, 간단한 뉴스 데이터 테이블을 만듭니다.
2. **데이터 확보:** 크롤링한 뉴스 데이터 100개 정도를 임시로 넣고, OpenAI Embedding API를 써서 벡터화해 봅니다.
3. **프로토타입:** 위 파이썬 코드를 로컬에서 돌려보며, 뉴스를 넣었을 때 과거 유사 사례를 잘 찾아오는지 테스트합니다.


**'지식 베이스(Memory)'**는 이 봇의 장기 기억 장치이자, AI가 과거의 패턴을 학습해 현재를 판단하는 **핵심 자산**입니다.

Polymarket 트레이딩에 특화된 Supabase(PostgreSQL + pgvector) 기반의 지식 베이스를 설계하고, 이를 구축하는 코드를 단계별로 알려드리겠습니다.

---

### 1. 데이터베이스 스키마 설계 (Supabase)

단순히 텍스트만 저장하는 것이 아니라, **'사건(News)'**과 **'결과(Impact)'**를 구조적으로 연결해야 합니다. 그래야 AI가 "뉴스 A가 떴을 때 -> 시장은 B만큼 하락했고 -> 결과는 C였다"는 인과관계를 배울 수 있습니다.

Supabase의 `SQL Editor`에서 아래 쿼리를 실행하여 테이블을 생성하세요.

```sql
-- 1. Vector 확장 기능 활성화
create extension if not exists vector;

-- 2. 지식 베이스 테이블 생성 (market_memories)
create table market_memories (
  id uuid default gen_random_uuid() primary key,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null,
  
  -- [메타데이터] 검색 필터링을 위한 핵심 컬럼
  category text not null,       -- 예: 'Sports', 'Crypto', 'Politics'
  entity text not null,         -- 예: 'Real Madrid', 'Bitcoin', 'Donald Trump'
  event_type text,              -- 예: 'Injury', 'Regulation', 'Poll'
  
  -- [비정형 데이터] AI가 읽을 텍스트와 벡터
  content text not null,        -- 뉴스 원문 또는 요약
  embedding vector(1536),       -- OpenAI text-embedding-3-small 차원 수
  
  -- [정형 데이터] 금융 공학적 분석을 위한 수치 (JSONB로 유연하게 저장)
  market_impact jsonb,          
  /* 예시 데이터 구조:
    {
      "price_drop_1h": -0.15,      (뉴스 직후 1시간 뒤 15% 하락)
      "final_outcome": "Win",      (그럼에도 불구하고 승리함)
      "opportunity_score": 85      (당시 진입했으면 좋았을 점수)
    }
  */

  -- 출처 링크 (나중에 검증용)
  source_url text
);

-- 3. 검색 속도를 위한 인덱스 생성 (IVFFlat 또는 HNSW)
create index on market_memories using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

```

---

### 2. 데이터 주입(Ingestion) 파이프라인 구축 (Python)

이제 뉴스와 시장 데이터를 **'임베딩(Vectorization)'**하여 DB에 넣는 파이썬 코드를 작성합니다. 여기서 가장 중요한 것은 **임베딩 품질**입니다.

**필수 라이브러리:**

```bash
pip install openai supabase numpy python-dotenv

```

**`memory_manager.py` 작성:**

```python
import os
import json
from datetime import datetime
from supabase import create_client, Client
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class MarketMemory:
    def __init__(self):
        # Supabase 설정
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        
        # OpenAI 설정 (임베딩용)
        self.openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    def get_embedding(self, text: str) -> list:
        """텍스트를 벡터로 변환 (text-embedding-3-small 사용)"""
        text = text.replace("\n", " ")
        response = self.openai.embeddings.create(
            input=[text],
            model="text-embedding-3-small"
        )
        return response.data[0].embedding

    def add_memory(self, category, entity, content, impact_data, source_url=""):
        """
        지식 베이스에 새로운 기억을 저장
        
        Args:
            category: 'Sports', 'Crypto' 등
            entity: 'Real Madrid' 등 (검색 필터링용)
            content: 뉴스 내용 (예: "음바페 햄스트링 부상 의심...")
            impact_data: dict 형태 (예: {"price_change": -0.05, "result": "Win"})
        """
        # 1. 임베딩 생성 (Content + Entity를 같이 넣어 문맥 강화)
        # 팁: 단순히 뉴스만 넣는 것보다 "Real Madrid의 부상 뉴스: [내용]" 처럼 만드는 게 검색에 유리함
        enriched_content = f"[{category}/{entity}] {content}"
        vector = self.get_embedding(enriched_content)

        # 2. Supabase 저장
        data = {
            "category": category,
            "entity": entity,
            "content": content,
            "embedding": vector,
            "market_impact": impact_data,
            "source_url": source_url
        }
        
        response = self.supabase.table("market_memories").insert(data).execute()
        print(f"✅ Memory saved: {entity} - {content[:30]}...")
        return response

# 사용 예시 (초기 데이터 구축용)
if __name__ == "__main__":
    memory = MarketMemory()
    
    # 예: 과거 데이터 입력 (크롤링한 데이터를 반복문으로 넣으면 됨)
    memory.add_memory(
        category="Sports",
        entity="Real Madrid",
        content="주전 골키퍼 쿠르투아, 십자인대 파열로 시즌 아웃 확정.",
        impact_data={
            "date": "2023-08-10",
            "price_impact_1h": -0.12, # 12% 폭락
            "final_result": "Win",    # 당일 경기는 이김 (과민반응이었음)
            "note": "백업 골키퍼 선방으로 승리"
        },
        source_url="https://marca.com/..."
    )

```

---

### 3. "맥락 검색(Context Retrieval)" 로직 구현

이 부분이 **Agentic RAG의 핵심**입니다. 단순히 유사도만 보는 게 아니라, **필터링(Metadata Filter)**을 먼저 수행하여 검색 정확도를 높여야 합니다.

Supabase에 `RPC`(Remote Procedure Call) 함수를 만들어 벡터 검색을 최적화합니다.

**1) Supabase SQL Editor에서 함수 생성:**

```sql
create or replace function match_memories (
  query_embedding vector(1536),
  match_threshold float,
  match_count int,
  filter_entity text
)
returns table (
  id uuid,
  content text,
  market_impact jsonb,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    market_memories.id,
    market_memories.content,
    market_memories.market_impact,
    1 - (market_memories.embedding <=> query_embedding) as similarity
  from market_memories
  where 1 - (market_memories.embedding <=> query_embedding) > match_threshold
  and market_memories.entity = filter_entity  -- [중요] 같은 팀/코인 내에서만 비교
  order by market_memories.embedding <=> query_embedding
  limit match_count;
end;
$$;

```

**2) Python에서 검색 함수 추가 (`memory_manager.py` 에 추가):**

```python
    def find_similar_events(self, entity: str, current_news: str):
        """
        현재 뉴스와 유사한 과거 사건을 검색 (RAG)
        """
        # 1. 현재 뉴스 임베딩
        query_vector = self.get_embedding(f"[{entity}] {current_news}")
        
        # 2. RPC 호출 (Metadata Filter 적용)
        response = self.supabase.rpc(
            "match_memories",
            {
                "query_embedding": query_vector,
                "match_threshold": 0.5, # 유사도 0.5 이상만
                "match_count": 3,       # 상위 3개만
                "filter_entity": entity # 예: Real Madrid 뉴스면 Real Madrid 과거만 조회
            }
        ).execute()
        
        return response.data

```

---

### 4. 다음 단계: 데이터 채워넣기 (Seeding)

시스템 뼈대는 완성되었습니다. 이제 봇이 똑똑해지려면 **데이터(경험)**가 필요합니다.

**추천 작업 순서:**

1. **초기 데이터 확보:**
* 최근 1년치 레알 마드리드(또는 관심 종목) 관련 주요 뉴스 헤드라인 50개 정도를 수집합니다. (ChatGPT에게 "2024-2025 레알 마드리드 주요 부상 및 이슈와 경기 결과 정리해줘"라고 해서 CSV로 받으세요.)


2. **일괄 업로드:**
* 위의 `add_memory` 함수를 이용해 50개 데이터를 DB에 밀어 넣습니다.


3. **테스트:**
* `find_similar_events("Real Madrid", "비니시우스 훈련 중 경미한 부상")`을 실행했을 때, 과거의 비슷한 부상 사례가 리턴되는지 확인합니다.



이 **'기억 저장소'**가 준비되면, 그다음 단계로 **LangGraph를 연결해 "검색된 과거 기억을 바탕으로 매매 판단을 내리는 에이전트"**를 만들 수 있습니다.

**"지식 베이스(Memory)"**를 채우기 위해서는 두 가지 종류의 데이터가 필요합니다.

1. **원인(News/Event):** 과거에 발생한 뉴스 (예: "주전 공격수 부상")
2. **결과(Market Impact/Result):** 그 뉴스로 인한 승패 및 시장 반응

과거의 **Polymarket 호가 데이터(Tick Data)**는 크롤링으로 얻기 어렵습니다(유료 API 영역). 따라서, **"뉴스를 크롤링하고 -> LLM을 이용해 당시의 시장 충격과 경기 결과를 추론/정리하여 -> DB에 적재"**하는 **'Smart Seeding' 스크립트**를 작성해 드리겠습니다.

가장 안정적인 **Google News RSS**를 활용한 방식입니다.

---

### 1. 사전 준비 (라이브러리 설치)

```bash
pip install feedparser beautifulsoup4 requests pandas openai python-dotenv supabase

```

### 2. 크롤러 및 데이터 생성기 (`data_seeder.py`)

이 스크립트는 다음 과정을 자동으로 수행합니다.

1. 특정 키워드(예: "Real Madrid injury")로 Google News 과거 기사를 검색합니다.
2. 뉴스 제목과 날짜를 추출합니다.
3. **LLM(GPT-4o)**에게 해당 날짜의 **"경기 결과"**와 **"예상되는 시장 반응(Market Impact)"**을 분석해달라고 요청하여 데이터를 보강합니다.
4. 앞서 만든 `MarketMemory` 클래스를 이용해 Supabase에 저장합니다.

```python
import feedparser
import requests
import json
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from openai import OpenAI
import os
from dotenv import load_dotenv

# 앞서 만든 메모리 매니저 클래스 임포트 (파일명을 memory_manager.py로 가정)
from memory_manager import MarketMemory

load_dotenv()

class SmartCrawler:
    def __init__(self):
        self.memory_db = MarketMemory()
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def fetch_google_news_rss(self, query, start_date, end_date):
        """
        Google News RSS를 통해 특정 기간의 뉴스 헤드라인 수집
        query: 검색어 (예: "Real Madrid injury")
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
        """
        # Google News RSS URL 포맷 (날짜 필터링 적용)
        # after:YYYY-MM-DD before:YYYY-MM-DD 문법 사용
        formatted_query = f"{query} after:{start_date} before:{end_date}"
        encoded_query = requests.utils.quote(formatted_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

        print(f"🔍 Crawling: {rss_url}")
        feed = feedparser.parse(rss_url)
        
        news_items = []
        for entry in feed.entries:
            # 너무 짧은 뉴스나 불필요한 소스 필터링
            if len(entry.title) < 20: continue
            
            news_items.append({
                "title": entry.title,
                "link": entry.link,
                "published": entry.published,
                "source": entry.source.title if hasattr(entry, 'source') else "Unknown"
            })
        
        print(f"✅ Found {len(news_items)} news items.")
        return news_items

    def enrich_data_with_llm(self, news_item, team_name):
        """
        뉴스 제목만으로는 '시장 충격'을 알 수 없으므로, LLM에게 당시 상황 복원을 요청 (Data Augmentation)
        """
        prompt = f"""
        You are a sports data analyst for a betting bot.
        
        Target Team: {team_name}
        News Title: "{news_item['title']}"
        News Date: {news_item['published']}
        
        Task:
        1. Analyze if this news was negative, positive, or neutral for the team's winning chances.
        2. Estimate the likely 'Price Drop' in betting markets (e.g., -5%, -10%, 0%).
        3. Recall (or search your knowledge) the actual match result that happened right after this news.
        
        Output JSON format only:
        {{
            "sentiment": "Negative/Positive/Neutral",
            "price_impact_estimate": "-0.05", (float, negative for drop)
            "actual_outcome": "Win/Loss/Draw",
            "summary": "Brief explanation of what happened"
        }}
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o", # gpt-3.5-turbo보다 gpt-4o가 역사적 사실(경기 결과) 기억력이 훨씬 좋음
                messages=[{"role": "system", "content": "You are a helpful assistant talking in JSON."},
                          {"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"⚠️ LLM Error: {e}")
            return None

    def run_seeding(self, entity, query, days_back=30):
        """
        실행 메인 함수: 크롤링 -> 분석 -> DB 저장
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        # 1. 뉴스 수집
        news_list = self.fetch_google_news_rss(
            query, 
            start_date.strftime("%Y-%m-%d"), 
            end_date.strftime("%Y-%m-%d")
        )
        
        # 2. 데이터 보강 및 저장
        count = 0
        for news in news_list[:10]: # 테스트를 위해 10개만 제한 (실전에서는 제거)
            print(f"Processing: {news['title']}...")
            
            # LLM을 통한 데이터 보강 (Market Impact 생성)
            impact_data = self.enrich_data_with_llm(news, entity)
            
            if impact_data:
                # 3. Supabase에 저장 (Memory Manager 사용)
                self.memory_db.add_memory(
                    category="Sports",
                    entity=entity,
                    content=f"[{news['source']}] {news['title']}", # 출처 포함
                    impact_data=impact_data,
                    source_url=news['link']
                )
                count += 1
                time.sleep(1) # API Rate Limit 방지
                
        print(f"🎉 Successfully seeded {count} memories for {entity}!")

# --- 실행 ---
if __name__ == "__main__":
    crawler = SmartCrawler()
    
    # 예: 레알 마드리드의 최근 3개월 부상(injury) 관련 뉴스만 수집해서 DB에 적재
    crawler.run_seeding(
        entity="Real Madrid", 
        query="Real Madrid injury", 
        days_back=90
    )

```

---

### 3. 코드 설명 및 전략

1. **Google News RSS 활용 (`fetch_google_news_rss`):**
* HTML 파싱(Selenium 등)은 웹사이트 구조가 바뀌면 깨지지만, RSS는 표준이라 매우 안정적입니다.
* `q=query after:date before:date` 파라미터를 사용해 원하는 과거 시점을 콕 집어 가져옵니다.


2. **LLM을 이용한 데이터 증강 (`enrich_data_with_llm`):**
* **핵심 트릭:** 단순히 뉴스를 저장하는 건 의미가 없습니다. **"그래서 결과가 어땠는데?"**가 중요합니다.
* 크롤러가 2023년 뉴스를 가져오면, GPT-4o는 이미 학습된 지식으로 "아, 그때 비니시우스 다쳤지만 레알이 2:0으로 이겼지"라는 사실을 알고 있습니다.
* 이 지식을 JSON으로 뽑아내 `market_impact` 컬럼에 같이 저장합니다. 나중에 RAG가 "부상에도 불구하고 이긴 사례"를 찾을 때 이 데이터가 쓰입니다.


3. **Supabase 저장:**
* 앞서 만든 `MarketMemory.add_memory` 함수를 재사용해 임베딩(Embedding)까지 자동으로 처리합니다.



---

### 4. 실행 전 체크리스트

1. **`.env` 파일 설정:**
```env
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=eyJ...

```


2. **데이터 품질 관리:**
* `days_back=90` (3개월)로 테스트해보고, 잘 작동하면 `days_back=365` (1년)로 늘려서 '24-25 시즌', '23-24 시즌' 데이터를 확보하세요.
* 검색어(`query`)를 다양하게 변경하며 실행하세요.
* `Real Madrid injury` (부상 이슈)
* `Real Madrid lineup` (라인업 이슈)
* `Real Madrid transfer` (이적 이슈)





이 스크립트를 한 번 돌려두면, 봇은 **"수십 개의 과거 사례를 머릿속에 넣은 상태"**로 트레이딩을 시작하게 됩니다.



이제 **"지식 베이스(Memory)"**가 구축되었으니, 이를 활용해 **"과거의 경험을 통해 현재를 판단하는 두뇌"**를 만들 차례입니다.

**LangGraph**를 사용하여 단순한 챗봇이 아닌, **상태(State)**를 관리하며 신중하게 판단하는 **에이전트 워크플로우**를 구현해 보겠습니다.

---

### 1. 에이전트 설계도 (The Graph)

우리가 만들 에이전트는 다음과 같은 흐름으로 사고합니다.

1. **Input:** 뉴스 속보 + 현재 시장 가격 (예: 레알 마드리드 승리 확률 65¢)
2. **Node 1 (Historian):** "잠깐, 저번에도 이런 뉴스 있지 않았어?" (RAG 검색)
3. **Node 2 (Analyst):** "과거엔 10% 떨어졌다가 결국 이겼네. 지금 시장은 15%나 떨어졌어. 이건 과민반응(Overreaction)이야." (LLM 추론)
4. **Node 3 (Trader):** "그럼 지금 진입하자. 목표가는 70¢." (매매 결정)

---

### 2. LangGraph 구현 코드 (`agent_brain.py`)

이 코드는 `memory_manager.py`를 임포트하여 사용합니다.

**필수 라이브러리:**

```bash
pip install langgraph langchain-openai langchain-core

```

**전체 코드:**

```python
import os
import json
from typing import TypedDict, List, Optional
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from memory_manager import MarketMemory  # 지난 단계에서 만든 클래스

load_dotenv()

# --- 1. 상태(State) 정의 ---
# 에이전트의 각 단계(Node)가 공유하는 데이터 메모리입니다.
class AgentState(TypedDict):
    # Inputs
    entity: str             # 대상 (예: Real Madrid)
    news_content: str       # 속보 내용
    current_price: float    # 현재 시장 가격 (0.0 ~ 1.0)
    
    # Internal Processing
    similar_memories: List[dict] # RAG로 찾은 과거 데이터
    analysis_reasoning: str      # LLM의 분석 근거
    
    # Outputs
    action: str             # BUY_YES / BUY_NO / HOLD
    target_price: float     # 목표가
    confidence: int         # 확신 수준 (0~100)

# --- 2. 노드(Node) 정의 ---

class TradingBot:
    def __init__(self):
        self.memory_db = MarketMemory()
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0) # 냉철한 판단을 위해 temp=0

    def retrieve_history(self, state: AgentState):
        """[Historian Node] 과거 유사 사례 검색"""
        print(f"\n📚 [Historian] Searching past events for: {state['news_content'][:30]}...")
        
        # Supabase에서 유사 사건 검색 (지난번 만든 함수 활용)
        results = self.memory_db.find_similar_events(
            state['entity'], 
            state['news_content']
        )
        
        # 검색 결과를 텍스트로 요약해서 상태에 저장
        memories = []
        if results:
            for item in results:
                # 유사도(similarity)가 0.75 이상인 것만 신뢰
                if item['similarity'] > 0.75: 
                    memories.append(item)
        
        print(f"   -> Found {len(memories)} relevant past events.")
        return {"similar_memories": memories}

    def analyze_market(self, state: AgentState):
        """[Analyst Node] 현재 뉴스와 과거 데이터를 비교 분석"""
        print(f"🧠 [Analyst] Analyzing market reaction...")
        
        # 과거 데이터가 없을 경우의 처리
        past_context = "No similar past events found."
        if state['similar_memories']:
            past_context = json.dumps([
                {
                    "content": m['content'],
                    "past_impact": m['market_impact']
                } for m in state['similar_memories']
            ], indent=2, ensure_ascii=False)

        # 프롬프트 엔지니어링 (핵심 Alpha)
        prompt = f"""
        You are an expert Quant Trader on Polymarket.
        
        [Target Asset]: {state['entity']}
        [Current News]: {state['news_content']}
        [Current Market Price]: {state['current_price']} (Probability of Winning)
        
        [Historical Context (RAG Data)]:
        {past_context}
        
        [Task]:
        Compare the current news with past events.
        1. If similar past news caused a price drop but the team WON, this is a 'Mean Reversion' opportunity (Buy the dip).
        2. If the current news is much worse than past events, the drop is justified (Sell or Hold).
        3. If no past data, rely on general sports knowledge.
        
        Determine the Strategy:
        - Action: BUY_YES (Long), BUY_NO (Short), or HOLD
        - Confidence: 0-100
        - Target Price: Where to exit?
        
        Output JSON only: {{ "reasoning": "...", "action": "...", "confidence": int, "target_price": float }}
        """
        
        response = self.llm.invoke(prompt)
        result = json.loads(response.content)
        
        return {
            "analysis_reasoning": result['reasoning'],
            "action": result['action'],
            "confidence": result['confidence'],
            "target_price": result['target_price']
        }

    def risk_check(self, state: AgentState):
        """[Risk Manager Node] 최종 안전 장치"""
        print(f"🛡️ [Risk Manager] Checking constraints...")
        
        action = state['action']
        conf = state['confidence']
        
        # 1. 확신이 낮으면 거래 금지
        if conf < 70:
            print("   -> Confidence too low. Force HOLD.")
            return {"action": "HOLD", "analysis_reasoning": state['analysis_reasoning'] + " (Filtered by Risk Manager)"}
        
        # 2. 이미 가격이 너무 높거나 낮으면 패스 (먹을 게 없음)
        if state['current_price'] > 0.95 or state['current_price'] < 0.05:
             print("   -> Price edge is too thin. Force HOLD.")
             return {"action": "HOLD"}
             
        return {"action": action}

# --- 3. 그래프 조립 (Wiring) ---

def build_agent():
    bot = TradingBot()
    
    workflow = StateGraph(AgentState)
    
    # 노드 추가
    workflow.add_node("historian", bot.retrieve_history)
    workflow.add_node("analyst", bot.analyze_market)
    workflow.add_node("risk_manager", bot.risk_check)
    
    # 엣지(흐름) 연결
    workflow.set_entry_point("historian")
    workflow.add_edge("historian", "analyst")
    workflow.add_edge("analyst", "risk_manager")
    workflow.add_edge("risk_manager", END)
    
    return workflow.compile()

# --- 4. 실행 테스트 (Simulation) ---
if __name__ == "__main__":
    agent = build_agent()
    
    # 시나리오: 비니시우스 부상 뉴스, 가격은 55센트로 폭락 중
    test_inputs = {
        "entity": "Real Madrid",
        "news_content": "Breaking: Vinicius Jr leaves training limping slightly. Medical tests scheduled for tomorrow.",
        "current_price": 0.55, # 평소 0.7 정도인데 부상 소식으로 떨어짐
        "similar_memories": [],
        "analysis_reasoning": "",
        "action": "",
        "target_price": 0.0,
        "confidence": 0
    }
    
    print(f"🚀 Starting Bot Simulation for: {test_inputs['entity']}")
    result = agent.invoke(test_inputs)
    
    print("\n" + "="*30)
    print(f"💡 FINAL DECISION: {result['action']}")
    print(f"🎯 CONFIDENCE: {result['confidence']}%")
    print(f"📝 REASONING: {result['analysis_reasoning']}")
    print("="*30)

```

---

### 3. 코드의 핵심 전략 포인트 (Alpha)

이 봇이 다른 평범한 봇보다 뛰어난 이유는 **`Analyst Node`의 프롬프트 로직**에 있습니다.

1. **Mean Reversion (평균 회귀) 포착:**
* RAG가 과거에 "비니시우스가 다쳤지만(News), 레알이 이겼고(Result), 가격은 회복됐다(Impact)"는 데이터를 가져오면,
* AI는 "이번에도 엄살일 수 있다. 지금 0.55에 떨어진 건 기회다. **BUY_YES**"라고 판단합니다.
* 반대로 RAG 데이터가 없으면 인간처럼 "부상이니까 위험해, **HOLD**"라고 보수적으로 나옵니다.


2. **Risk Manager (안전장치):**
* AI가 아무리 좋다고 해도(`BUY_YES`), 확신(Confidence) 점수가 70점 미만이면 강제로 `HOLD` 시킵니다.
* 이는 헛발질로 인한 수수료 손실을 막아줍니다.



---

### 4. 실행 방법

1. **사전 준비:**
* 이전 단계(`data_seeder.py`)를 통해 Supabase에 데이터가 최소 5~10개는 들어 있어야 RAG가 작동합니다.


2. **실행:**
```bash
python agent_brain.py

```


3. **결과 확인:**
* 콘솔에 `[Historian]`, `[Analyst]` 로그가 찍히며 AI가 어떻게 생각하고 결론을 내렸는지 볼 수 있습니다.



---

### 5. Next Action (마지막 퍼즐)

이제 **"뇌(Brain)"**와 **"기억(Memory)"**이 완성되었습니다. 남은 건 **"손(Execution)"**입니다.

지금 출력되는 `FINAL DECISION: BUY_YES`라는 텍스트를, **실제 Polymarket API에 전송하여 주문을 체결시키는 모듈**을 연결해야 합니다.

