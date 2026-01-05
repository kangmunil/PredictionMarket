# 🐝 Hive Mind: ArbHunter Swarm Intelligence V2.5

Polymarket Elite Trading Swarm에 오신 것을 환영합니다. 이 프로젝트는 개별적으로 동작하던 봇들을 하나의 **'군집 지능(Swarm Intelligence)'**으로 통합하여, 뉴스와 시장 데이터가 모든 전략에 유기적으로 전파되는 최첨단 트레이딩 시스템입니다.

## 🧠 핵심 아키텍처: Project Hive Mind

본 시스템은 **`SignalBus` (중추신경계)**를 중심으로 모든 에이전트가 지능을 공유합니다.

*   **News Scalper (Eyes)**: 뉴스를 감지하고 AI(RAG) 분석을 통해 시장 영향력을 평가합니다.
*   **SignalBus (Synapse)**: 실시간 호재/악재 및 고래 활동 신호를 모든 봇에게 방송합니다.
*   **StatArb / PureArb (Hands)**: 공유된 신호를 바탕으로 진입 장벽을 낮추거나 거래를 일시 정지하는 등 동적으로 전략을 수정합니다.
*   **BudgetManager (Heart)**: 모든 봇의 자금 요청을 중앙 통제하여 파산을 방지하고 자본 효율성을 극대화합니다.

---

## 🚀 주요 기능 및 실행

### 1. 통합 실행 (Swarm Mode)
이제 여러 터미널을 띄울 필요 없이 하나의 명령어로 모든 봇을 실행합니다.
```bash
python3 run_swarm.py --ui
```

### 2. TUI 대시보드 📊
터미널에서 실시간으로 자금 현황, 요원 상태, 시장 신호를 감시할 수 있습니다.
*   `💰 Capital Allocation`: 전략별 실시간 잔액 표시
*   `🧠 Hive Mind Signals`: 현재 감지된 타겟 종목 및 감성 점수
*   `🤖 Agent Status`: 각 봇의 가동 상태 (ONLINE/OFFLINE)

### 3. 텔레그램 커맨드 센터 📱
밖에서도 스마트폰 하나로 봇을 완벽하게 제어합니다.
*   `/status`: 현재 자산 현황 및 활성 신호 요약
*   `/history`: 최근 매매 내역 및 P&L 조회
*   `/top`: 현재 가장 수익 가능성이 높은 종목 랭킹
*   `/stop` & `/resume`: 원격 매매 중지 및 재개

---

## 🛠️ 전략 시스템 개요

| 에이전트 | 핵심 전략 | 특징 |
| :--- | :--- | :--- |
| **News Scalper** | AI RAG 분석 | Gemini/Claude를 이용한 정밀한 문맥 파악 및 선점 매매 |
| **Pure Arbitrage** | 수학적 오류 사냥 | Yes/No 가격 합계 불균형을 이용한 무위험 수익 확정 |
| **Stat Arb** | 통계적 회귀 | 상관관계 시장 간의 가격 괴리를 노리는 지능형 스윙 |
| **Elite Mimic** | 고래 추적 | 상위 트레이더의 지갑을 24시간 실시간 카피 트레이딩 |

---

## ⚠️ 주의 사항 및 환경 설정
1.  **가상 매매**: 실전 투입 전 반드시 `--dry-run` 모드로 충분히 검증하십시오.
2.  **보안**: `.env` 파일의 지갑 개인키와 API 토큰 관리에 유의하십시오. (`.gitignore` 적용 완료)
3.  **환경 변수**: `.env.example`을 복사하여 `.env`를 생성하고 필수 키를 입력하십시오.

---
**Last Updated**: 2026-01-06 (Swarm Integration Complete)
**Contact**: Hive Mind Development Swarm
