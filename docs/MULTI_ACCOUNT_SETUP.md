# 🔐 Multi-Account Setup Guide

**Purpose**: Run multiple bots with separate wallets for risk isolation
**Status**: ✅ Recommended for production

---

## 📊 계정 분리 전략

### 봇별 독립 계정

| Bot | Wallet | Budget | Purpose |
|-----|--------|--------|---------|
| **News Scalping** | Wallet A | $100 | 뉴스 스캘핑 (고위험) |
| **Pure Arbitrage** | Wallet B | $500 | 순수 차익거래 (저위험) |
| **Stat Arbitrage** | Wallet C | $300 | 통계적 차익거래 (중위험) |

**장점**:
- ✅ 리스크 격리 (한 봇 실패해도 다른 봇 안전)
- ✅ 성능 분석 명확 (각 봇 ROI 측정)
- ✅ 예산 관리 쉬움
- ✅ 감사(Audit) 용이

---

## 🛠️ 설정 방법

### Step 1: 지갑 생성

각 봇마다 별도 MetaMask 지갑 생성:

```bash
# News Bot Wallet
1. MetaMask 열기
2. "Create new account" 클릭
3. 이름: "News Scalping Bot"
4. Private Key 복사 (Settings > Security > Export Private Key)

# Pure Arb Bot Wallet
1. "Create new account" 클릭
2. 이름: "Pure Arbitrage Bot"
3. Private Key 복사

# Stat Arb Bot Wallet
1. "Create new account" 클릭
2. 이름: "Stat Arb Bot"
3. Private Key 복사
```

---

### Step 2: 각 지갑에 자금 입금

```bash
# Polygon(MATIC) 네트워크 사용
# Bridge: https://wallet.polygon.technology/

News Bot Wallet: $100 USDC (테스트용)
Pure Arb Wallet: $500 USDC (안정적)
Stat Arb Wallet: $300 USDC (중간)
```

⚠️ **주의**: 각 지갑에 소량의 MATIC도 필요 (가스비용)
- 각 지갑에 ~1 MATIC 정도 보내기

---

### Step 3: .env 파일 설정

**현재 구조**:
```
.env              # 기본 설정 (Pure Arb용)
.env.news         # News Bot 전용
.env.stat_arb     # Stat Arb Bot 전용 (선택사항)
```

#### .env.news 설정

```bash
# 1. .env.news 파일 열기
nano .env.news

# 2. Private Key 교체
PRIVATE_KEY="0x[News_Bot_Wallet_Private_Key]"
FUNDER_ADDRESS="0x[News_Bot_Wallet_Address]"

# 3. 예산 설정
NEWS_BOT_BUDGET="100.0"
NEWS_BOT_MAX_POSITION="10.0"
NEWS_BOT_MAX_POSITIONS="5"

# 4. 저장 (Ctrl+O, Enter, Ctrl+X)
```

#### .env (Pure Arb용)

```bash
# 기본 .env는 Pure Arb Bot용으로 유지
PRIVATE_KEY="0x[Pure_Arb_Wallet_Private_Key]"
FUNDER_ADDRESS="0x[Pure_Arb_Wallet_Address]"
```

---

### Step 4: 봇 실행

**News Bot (자동으로 .env.news 로드)**:
```bash
python3 run_news_scalper_optimized.py --keywords bitcoin crypto --live
```

**Pure Arb Bot (.env 사용)**:
```bash
python3 run_pure_arbitrage.py --threshold 0.99 --size 50
```

**Stat Arb Bot (.env 사용 또는 .env.stat_arb)**:
```bash
python3 run_stat_arb_live_v2.py --category crypto --max-pairs 3
```

---

## 📊 계정별 모니터링

### 실시간 잔액 확인

```bash
# News Bot 잔액
curl "https://clob.polymarket.com/balances/0x[News_Bot_Address]"

# Pure Arb Bot 잔액
curl "https://clob.polymarket.com/balances/0x[Pure_Arb_Address]"

# Stat Arb Bot 잔액
curl "https://clob.polymarket.com/balances/0x[Stat_Arb_Address]"
```

### 로그 파일 분리

각 봇은 자동으로 별도 로그 파일 생성:

```
logs/
├── news_scalper_optimized_20260103_200000.log
├── pure_arbitrage_20260103_200000.log
└── stat_arb_20260103_200000.log
```

---

## 🎯 단계별 테스트 전략

### Phase 1: 소액 테스트 (Week 1)

| Bot | Budget | Trade Size | Expected ROI |
|-----|--------|------------|--------------|
| News | $50 | $5 | 10-30% |
| Pure Arb | $100 | $20 | 5-15% |
| Stat Arb | $100 | $15 | 8-20% |

**목표**: 각 봇이 정상 작동하는지 확인

---

### Phase 2: 중간 테스트 (Week 2-3)

| Bot | Budget | Trade Size | Expected ROI |
|-----|--------|------------|--------------|
| News | $100 | $10 | 15-40% |
| Pure Arb | $300 | $50 | 5-15% |
| Stat Arb | $200 | $30 | 10-25% |

**목표**: ROI 측정 및 최적화

---

### Phase 3: 프로덕션 (Week 4+)

| Bot | Budget | Trade Size | Expected ROI |
|-----|--------|------------|--------------|
| News | $500 | $20 | 20-50% |
| Pure Arb | $1000 | $100 | 5-15% |
| Stat Arb | $500 | $50 | 10-30% |

**목표**: 안정적 수익 창출

---

## 🔒 보안 체크리스트

### 필수 보안 조치

- [ ] 각 지갑의 Private Key를 별도 안전한 곳에 백업
- [ ] .env 파일들을 `.gitignore`에 추가 (이미 완료)
- [ ] 각 지갑에 최소한의 자금만 보관
- [ ] 정기적으로 수익을 메인 지갑으로 출금
- [ ] 2FA 활성화 (MetaMask)
- [ ] 의심스러운 활동 모니터링

---

## 📝 예산 할당 예시

### Conservative (보수적)

```
총 자본: $1000

News Bot:    $200 (20%)  - 고위험 고수익
Pure Arb:    $500 (50%)  - 저위험 안정수익
Stat Arb:    $300 (30%)  - 중위험 중수익
```

### Balanced (균형)

```
총 자본: $1500

News Bot:    $500 (33%)
Pure Arb:    $500 (33%)
Stat Arb:    $500 (33%)
```

### Aggressive (공격적)

```
총 자본: $2000

News Bot:    $1000 (50%)  - 최대 수익 추구
Pure Arb:    $500 (25%)   - 안정성 보조
Stat Arb:    $500 (25%)   - 분산투자
```

---

## 🚨 긴급 상황 대응

### 한 봇이 손실을 볼 때

```bash
# 1. 즉시 봇 중지
Ctrl+C

# 2. 로그 확인
tail -100 logs/[bot_name]_*.log

# 3. 포지션 수동 정리
# MetaMask에서 Polymarket 접속
# 열린 포지션 확인 및 수동 청산

# 4. 문제 분석
# 로그 파일 검토
# 손실 원인 파악

# 5. 수정 후 재시작
python3 run_[bot_name].py --dry-run  # 먼저 Dry-run
```

---

## 📊 성과 추적

### 일일 리포트

```bash
# 각 봇의 일일 성과 확인
echo "=== Daily Performance Report ==="
echo ""
echo "News Bot:"
grep "Total P&L" logs/news_scalper_*.log | tail -1
echo ""
echo "Pure Arb Bot:"
grep "Total P&L" logs/pure_arbitrage_*.log | tail -1
echo ""
echo "Stat Arb Bot:"
grep "Total P&L" logs/stat_arb_*.log | tail -1
```

### 주간 리뷰

| Metric | News Bot | Pure Arb | Stat Arb |
|--------|----------|----------|----------|
| Starting Balance | $100 | $500 | $300 |
| Ending Balance | ? | ? | ? |
| P&L | ? | ? | ? |
| ROI % | ? | ? | ? |
| Win Rate | ? | ? | ? |
| Trades | ? | ? | ? |

---

## ✅ 권장 워크플로우

### 매일

1. 각 봇 상태 확인 (로그)
2. 잔액 확인
3. 비정상 활동 체크

### 매주

1. 성과 리포트 작성
2. 수익 출금 (메인 지갑으로)
3. 봇 설정 최적화

### 매월

1. 전체 ROI 계산
2. 예산 재조정
3. 전략 검토 및 개선

---

## 🎓 FAQ

**Q: 꼭 계정을 분리해야 하나요?**
A: 필수는 아니지만 **강력히 권장**합니다. 리스크 격리와 성능 분석이 훨씬 쉽습니다.

**Q: 하나의 계정으로 여러 봇을 동시에 돌리면?**
A: 가능하지만 **Budget Manager가 필요**합니다. 봇들이 서로 자금을 뺏어가는 문제 발생 가능.

**Q: News Bot만 별도 계정으로 하면?**
A: 좋은 시작입니다! News Bot이 가장 위험하므로 우선 분리하는 게 현명합니다.

**Q: 테스트는 어느 정도 자금으로?**
A: News Bot: $50-100, Pure Arb: $100-200, Stat Arb: $100-200 정도 추천.

**Q: 수익은 언제 출금?**
A: 주 1회 정도 메인 지갑으로 출금 권장. 봇 지갑엔 최소한만 보관.

---

**Status**: ✅ Setup Complete
**Next**: Test each bot with small capital
**Guide**: Follow Phase 1 → Phase 2 → Phase 3

**Last Updated**: 2026-01-03
