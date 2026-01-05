# 📖 ArbHunter Bot System - Master User Guide

이 가이드는 ArbHunter 시스템에 포함된 3가지 트레이딩 봇의 운영 방법을 통합하여 설명합니다.

---

## 📋 공통 준비 사항

모든 봇을 실행하기 전에 다음 인프라가 준비되어 있어야 합니다.

1.  **Redis 서버**: 자금 관리와 API 제한을 위해 필수입니다. (`brew services start redis`)
2.  **환경 변수**: `.env` 파일에 `PRIVATE_KEY`, `TREE_NEWS_API_KEY` 등이 설정되어야 합니다.
3.  **가상 환경**: `./.venv/bin/python3`를 사용하여 실행하는 것을 권장합니다.

---

## 1️⃣ News Scalper (뉴스 스캘퍼)

실시간 뉴스를 AI가 읽고 시장의 방향성을 예측하여 초고속으로 매매합니다.

### 실행 명령어
```bash
# 기본 실행 (가상 매매 모드)
./.venv/bin/python3 run_news_scalper_optimized.py --keywords "bitcoin" "crypto"

# 상세 로그와 함께 실행
./.venv/bin/python3 run_news_scalper_optimized.py --keywords "bitcoin" "fed" --verbose

# 실제 거래 실행 (주의!)
./.venv/bin/python3 run_news_scalper_optimized.py --live --size 10
```

### 주요 설정 옵션
*   `--keywords`: 추적할 뉴스 키워드 (공백으로 구분)
*   `--size`: 거래당 투입 금액 (USD)
*   `--min-confidence`: AI 확신도 임계치 (기본 0.80)

---

## 2️⃣ Pure Arbitrage (순수 차익거래)

YES + NO 가격의 합이 $1 미만인 시장을 찾아 무위험 수익을 챙깁니다.

### 실행 명령어
```bash
# 가상 매매 모드 (권장)
./.venv/bin/python3 run_pure_arbitrage.py --dry-run

# 실제 거래 실행
./.venv/bin/python3 run_pure_arbitrage.py --threshold 0.99 --size 50
```

### 주요 설정 옵션
*   `--threshold`: 진입 기준 (YES+NO 합계가 이 값보다 작을 때)
*   `--size`: 각 포지션별 투입 금액
*   `--min-profit`: 주당 최소 기대 수익 ($0.01 권장)

---

## 3️⃣ Statistical Arbitrage V2 (통계적 차익거래)

상관관계가 높은 두 시장의 가격 괴리가 커졌을 때 진입하여 회귀 수익을 얻습니다.

### 실행 명령어
```bash
# 가상 매매 모드
./.venv/bin/python3 run_stat_arb_live_v2.py --dry-run --category crypto

# 특정 카테고리 실전 매매
./.venv/bin/python3 run_stat_arb_live_v2.py --category economics --max-pairs 3
```

### 주요 설정 옵션
*   `--category`: 거래 카테고리 (crypto, economics, politics, all)
*   `--max-pairs`: 동시에 운영할 최대 페어 수
*   `--interval`: 시장 체크 주기 (초 단위, 기본 300)

---

## 📊 모니터링 및 관리

### 로그 확인
각 봇의 로그는 `logs/` 디렉토리에 실시간으로 저장됩니다.
```bash
# 뉴스 스캘퍼 로그 확인
tail -f logs/news_scalper_optimized_*.log

# 차익거래 기회 포착 확인
tail -f logs/pure_arbitrage.log | grep "OPPORTUNITY"
```

### Redis 자금 상태 확인
```bash
# 현재 각 봇에 할당된 예산 확인
redis-cli HGETALL budget:allocations
```

---

## 🚨 위험 관리 (Risk Management)

1.  **작게 시작하세요**: 처음에는 모든 봇을 `--dry-run`으로 최소 24시간 가동하십시오.
2.  **예산 제한**: `src/core/config.py`에서 `DAILY_BUDGET_USD`를 설정하여 최대 손실을 제한하십시오.
3.  **긴급 정지**: 문제가 발생하면 `pkill -f run_` 명령어로 모든 봇을 즉시 종료할 수 있습니다.

---
**Happy Trading!** 🚀
