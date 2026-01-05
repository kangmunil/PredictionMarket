# 📊 Paper Trading / Dry Run 가이드

**작성일**: 2026-01-04
**상태**: ✅ 완료
**승률 추적**: ✅ 가능

---

## 🎯 개요

두 봇 모두 **실제 시장 데이터를 사용한 Paper Trading** 지원합니다:

| 봇 | Dry Run 모드 | 승률 계산 | 실제 가격 사용 |
|-----|-------------|-----------|-------------|
| **News Scalper** | ✅ | ✅ | ✅ (실시간 조회) |
| **Pure Arbitrage** | ✅ | ✅ | ✅ (WebSocket) |

---

## 📈 News Scalper Paper Trading

### 작동 방식

```
뉴스 감지
   ↓
실제 시장 가격 조회 (Entry)
   ↓
Paper 포지션 오픈
   ↓
홀딩 (1-6시간)
   ↓
실제 시장 가격 조회 (Exit)
   ↓
P&L 계산 + 승률 업데이트
```

### 실행 방법

```bash
# Dry run (Paper Trading)
python3 run_news_scalper_optimized.py \
  --keywords bitcoin crypto \
  --verbose

# Live mode
python3 run_news_scalper_optimized.py \
  --keywords bitcoin crypto \
  --live
```

### Paper Trading 로그 예시

```
🧪 PAPER TRADING: Would execute slippage-protected BUY order
   Entry price: $0.5234
   Max slippage: 2.0%
   Order type: IOC Limit

...

🚪 Closing position: Max hold time (1.0h)
   📊 Paper Trading Results:
      Entry: $0.5234
      Exit:  $0.5489
      Move:  +4.87%
      P&L:   $+0.49 (WIN)
      Win Rate: 65.0% (13/20)
```

### 최종 리포트

```
📊 Final Performance Report:
   Runtime: 120.5m
   News Checked: 543
   Signals Generated: 47
   Trades Executed: 23
   Positions Closed: 23

💰 Trading Results:
   Total P&L: $+12.34
   Wins: 15
   Losses: 8
   Win Rate: 65.2%
   Avg P&L per trade: $+0.54

⚡ Performance:
   Average Latency: 127ms
   Target: <2000ms
   Status: ✅ PASS
```

---

## 🔄 Pure Arbitrage Dry Run

### 작동 방식

```
WebSocket 실시간 호가창
   ↓
YES + NO < $0.99 감지
   ↓
Paper 주문 시뮬레이션
   ↓
Expected Profit 계산
   ↓
승률 업데이트 (항상 WIN)
```

**특징**: Arbitrage는 원자적 실행 시 **100% 승률** (YES + NO = $1.00 보장)

### 실행 방법

```bash
# Dry run (Paper Trading)
python3 run_pure_arbitrage.py \
  --dry-run \
  --threshold 0.99 \
  --size 50

# Live mode
python3 run_pure_arbitrage.py \
  --threshold 0.99 \
  --size 50
```

### Paper Trading 로그 예시

```
💰 ARBITRAGE OPPORTUNITY #1
Token A: 0x1234... @ $0.4700
Token B: 0x5678... @ $0.5100
Total Cost: $0.9800
Profit: $0.0200 per share
Trade Size: $50.00 per leg
Expected Profit: $1.0000

✅ PAPER TRADE EXECUTED!
   📊 Results:
      Expected Profit: $1.0000
      Orders Executed: 1
      Total Profit: $1.00
      Win Rate: 100.0% (1/1)
```

---

## 🔍 승률 계산 로직

### News Scalper

```python
# Entry 시점
entry_price = await self._get_current_price(token_id)  # 실제 시장 가격

# Exit 시점
current_price = await self._get_current_price(token_id)  # 실제 시장 가격

# P&L 계산
if side == "BUY":
    pnl = (current_price - entry_price) / entry_price * size
else:
    pnl = (entry_price - current_price) / entry_price * size

# 승/패 판정
if pnl > 0:
    wins += 1
else:
    losses += 1

# 승률
win_rate = wins / (wins + losses) * 100
```

### Pure Arbitrage

```python
# Arbitrage는 원자적 실행 시 무조건 WIN
# (YES + NO = $1.00 payout 보장)

expected_profit = (1.0 - (price_yes + price_no)) * trade_size

if expected_profit > 0:
    wins += 1  # 항상 WIN

win_rate = wins / (wins + losses) * 100  # 100%
```

---

## 📊 예상 승률

### News Scalper

| 조건 | 예상 승률 |
|------|-----------|
| 고신뢰도 뉴스만 (>85%) | 60-70% |
| 중신뢰도 포함 (>80%) | 55-65% |
| 슬리피지 방어 ON | +5-10% |

**현실적 목표**: **60% 승률**

### Pure Arbitrage

| 조건 | 예상 승률 |
|------|-----------|
| 원자적 실행 | 100% |
| 순차 실행 (leg risk) | 90-95% |
| 슬리피지 고려 | 85-90% |

**현실적 목표**: **90% 승률**

---

## ⚠️ 주의사항

### 1. Paper Trading vs Live Trading 차이

**Paper Trading**:
- ✅ 실제 가격 사용
- ✅ 실제 호가창 사용
- ❌ 슬리피지 없음 (best price에 100% 체결 가정)
- ❌ 유동성 문제 없음
- ❌ 실제 자금 손실 없음

**Live Trading**:
- ✅ 모든 시장 마찰 반영
- ⚠️ 슬리피지 발생 가능
- ⚠️ 체결 안 될 수 있음
- ⚠️ 실제 자금 손실 가능

**결론**: Paper Trading 승률이 Live Trading보다 **5-10% 높게 나올 수 있음**

### 2. 권장 테스트 절차

```bash
# 1단계: Paper Trading 1주일
python3 run_news_scalper_optimized.py --keywords bitcoin --verbose
python3 run_pure_arbitrage.py --dry-run

# 목표: 60% 이상 승률 달성

# 2단계: Live Trading 소액 ($10-20/trade)
python3 run_news_scalper_optimized.py --keywords bitcoin --live --size 10
python3 run_pure_arbitrage.py --size 10

# 목표: 55% 이상 승률 유지

# 3단계: 본격 운영 ($50-100/trade)
# 승률이 안정적이면 투자금 증액
```

### 3. 예상 손실

**News Scalper**:
- 승률 60% → 40% 손실 trades
- 평균 손실: -2% to -5% per losing trade
- **Max Drawdown**: -20% to -30%

**Pure Arbitrage**:
- 승률 90% → 10% 손실 trades
- 평균 손실: -1% to -2% per losing trade (leg risk)
- **Max Drawdown**: -5% to -10%

---

## 🎯 실전 활용

### News Scalper 최적화

```bash
# 고승률 전략 (보수적)
python3 run_news_scalper_optimized.py \
  --keywords "bitcoin etf" "sec approval" \
  --min-confidence 0.90 \
  --size 10 \
  --max-positions 3

# 기대 승률: 65-75%
```

### Pure Arbitrage 최적화

```bash
# 고빈도 전략 (공격적)
python3 run_pure_arbitrage.py \
  --threshold 0.985 \
  --min-profit 0.005 \
  --size 50

# 기대 승률: 90-95%
```

---

## ✅ 검증 완료

- [x] News Scalper: Paper Trading 구현
- [x] Pure Arbitrage: Dry Run 구현
- [x] 실제 가격 조회 로직
- [x] P&L 계산 로직
- [x] 승률 계산 로직
- [x] 최종 리포트 표시
- [x] 테스트 코드 작성
- [ ] 1주일 Paper Trading 실행 (대기 중)
- [ ] Live Trading 검증 (대기 중)

---

**다음 단계**: NewsAPI 키를 받아서 1주일 Paper Trading 실행 후 승률 검증

**Last Updated**: 2026-01-04
