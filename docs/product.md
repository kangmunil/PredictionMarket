### 주요 전략: Pure Arbitrage (무위험 가격 불일치 활용)
programmers are making $10k-200k monthly on polymarket

here's how they actually do it

///

1. arbitrage bots

buy YES + NO when combined price < $1

example: YES at 48¢ + NO at 49¢ = 97¢ total

you lock $0.03 profit per $1 no matter who wins

trader "distinct-baguette" made $242k in 1.5 months doing this

targets 15-min crypto markets where prices move fast

python script polls API every 1-3 seconds, executes when sum < 99¢

///

2. statistical arbitrage

find correlated markets that drift apart

"trump wins" vs "GOP senate control" should move together

when spread hits 4-7%, short expensive one, long cheap one

close when they converge

trader "sharky6999" made $480k scanning 100+ markets per minute

///

3. AI probability models

train ML models to estimate real odds from news/social data

if your model says 60% YES but market at 50¢, buy

trader "ilovecircle" made $2.2M in 2 months with 74% accuracy

uses ensemble of 10 AI models, retrains weekly

///

4. spread farming

buy at bid (5¢), sell at ask (6¢), repeat

or hedge across platforms (short polymarket, long binance)

trader "cry.eth2" made $194k with 1M trades

high-frequency loop via CLOB API

///

5. copy-trading automation

mirror successful whale traders automatically

scan profiles, execute proportional trades

one bot made $80k in 2 weeks copying near-resolved markets

///

tech stack:

python + requests library for API calls 

web3-py for blockchain interactions deploy on VPS for 24/7 operation

polymarket has REST APIs for everything:

gamma markets API (prices/volumes)
CLOB API (place orders)
data API (track positions)

///

starting point:

> build simple arbitrage bot first
> fund with $100-1k for testing target high-volume markets (politics/crypto)
 > expect 50-70% win rate but focus on positive EV


- **작동 원리**:
  - 모든 바이너리 시장(Yes/No)에서 Yes 가격 + No 가격은 이론적으로 항상 **정확히 $1**이어야 합니다. (하나가 $1로 해결되기 때문)
  - 하지만 단기 크립토 시장처럼 변동성이 크고 유동성이 불안정한 곳에서는 가격이 순간적으로 어긋납니다.
  - 예: Yes $0.48 + No $0.49 = $0.97 (합계 $1 미만)
  - 이 때 봇이 **Yes와 No를 동시에 매수**합니다.
  - 시장 해결 시 무조건 하나가 $1이 되므로, 투자한 $0.97로 $1을 받아 **$0.03 무위험 수익**锁定.
  - 반대로 합계 > $1일 때는 둘 다 매도하지만, 주로 < $1 기회를 노림.

- **왜 15분 크립토 시장에서 효과적인가?**
  - 시장 오픈 직후나 가격 급변 시 스프레드가 넓어지고 mispricing(가격 불일치)이 자주 발생.
  - 수초~수분 만에 사라지는 기회라 인간은 놓치지만, 봇은 실시간 스캔으로 포착.
  - 거래량이 높아 실행 가능.

- **봇 구현 특징**:
  - Python 스크립트로 Polymarket API(CLOB 포함)를 1~3초마다 폴링.
  - 합계 < $0.99 (또는 설정 threshold) 시 자동으로 둘 다 매수 (atomic 실행으로 위험 최소화).
  - 수천~만 번 반복: 작은 edge(1~3¢ per trade)를 고빈도로 쌓음.
  - Win rate는 70%대지만, 이는 예측이 아니라 volume에서 오는 안정적 수익.

- **성과 증거**:
  - 10,000+ 거래 대부분 15분 크립토.
  - PnL 그래프가 거의 직선으로 상승 (큰 드로우다운 없음).
  - 리더보드 crypto 카테고리 상위 (e.g., monthly +$175K).
  - 방향성 베팅 없음: 결과 상관없이 수익.

### 이 전략 카피하는 방법 (Copy Trading)
이 사람을 카피하려면 **자동 카피 트레이딩 봇**을 사용하는 게 가장 효과적입니다.

1. **월렛 주소 추적**:
   - 주소: 0xe00740bce98a594e26861838885ab310ec3b548c (ScanWhale 등에서 확인)
   - Dune Analytics, Polymarket Analytics, PolyTrack, PolyAlertHub 같은 툴로 실시간 거래 모니터링.

2. **카피 봇 추천**:
   - GitHub에 오픈소스 Polymarket Trade Copier 많음 (e.g., MaxWell219/Polymarket-betting-bot).
   - blockchain event monitoring으로 대상 월렛 거래 감지 → 즉시 동일/비례 포지션 실행.
   - 설정: 지연 최소화 (VPS 사용), 거래당 1-5% 자본 할당, crypto 15분 시장만 필터.

3. **주의점**:
   - 기회는 경쟁 심해짐 (봇 많아 mispricing 빨리 사라짐).
   - 가스비/슬리피지 고려: Polygon 네트워크지만 고빈도 시 비용 누적.
   - 소액 테스트 먼저 ($100~1K).
   - Win rate 낮아 보이지만 (28~71%), 실제는 무위험 edge라 안정적.

이 전략은 "예측 시장을 카지노가 아닌 아비트라지 머신으로 보는" 전형적 퀀트 접근입니다. 방향 예측 없이도 꾸준히 수익 내는 게 매력적이죠. 실제로 따라 하려면 코딩 지식이나 기존 봇 활용이 필요합니다!