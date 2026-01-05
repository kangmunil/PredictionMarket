"""
Statistical Arbitrage Pair Configuration V2
===========================================

🔄 MAJOR UPDATE: 장기 시장 → 단기 변동성 시장으로 전환

변경 이유:
- 2026/2028 장기 시장: 가격 변동 거의 없음 (표준편차 ~0)
- Cointegration 계산 불가능 (Invalid input, x is constant)
- Statistical Arbitrage는 변동성이 필요!

새 전략:
- 단기 crypto 시장 (1일~1주)
- 뉴스 이벤트 기반 시장 (48시간~1주)
- 실제 변동성이 있는 시장만 선택

Author: ArbHunter V2.1
Updated: 2026-01-03 (Short-term Markets)
"""

# ============================================================
# 전략 1: 단기 Crypto Correlation (실제 변동성 있음)
# ============================================================

CANDIDATE_PAIRS = [
    # ========== Bitcoin vs Ethereum (동일 트렌드) ==========
    {
        "name": "BTC_ETH_Weekly_Correlation",
        "description": "Bitcoin vs Ethereum 주간 가격 움직임 상관관계",
        "token_a": {
            # Simplified keywords - just core terms
            "search_query": "Bitcoin",
            "dynamic": True,
            "keywords": ["bitcoin", "btc"]  # Simplified
        },
        "token_b": {
            "search_query": "Ethereum",
            "dynamic": True,
            "keywords": ["ethereum", "eth"]  # Simplified
        },
        "category": "crypto",
        "reason": "BTC와 ETH는 높은 상관관계 (0.8+). 단기적으로 함께 움직임",
        "expected_correlation": 0.85,
        "priority": "high",
        "strategy_type": "convergence",
        "timeframe": "1week"
    },

    # ========== Fed Rate Decision Markets (이벤트 기반) ==========
    {
        "name": "Fed_NextMeeting_Rate",
        "description": "다음 FOMC 회의 금리 결정 (이벤트 48시간 전)",
        "token_a": {
            "search_query": "Fed rate cut next meeting",
            "dynamic": True,
            "keywords": ["fed", "rate cut", "fomc", "next"]
        },
        "token_b": {
            "search_query": "Fed rate hike next meeting",
            "dynamic": True,
            "keywords": ["fed", "rate hike", "fomc", "next"]
        },
        "category": "economics",
        "reason": "금리 인상/인하는 역상관. 이벤트 전 48시간 변동성 최고",
        "expected_correlation": -0.90,
        "priority": "high",
        "strategy_type": "inverse",
        "timeframe": "48hours"
    },

    # ========== Crypto Fear & Greed (심리 지표) ==========
    {
        "name": "BTC_Sentiment_Daily",
        "description": "Bitcoin 일일 심리 지표 (공포 vs 탐욕)",
        "token_a": {
            "search_query": "Bitcoin",
            "dynamic": True,
            "keywords": ["bitcoin", "btc"]  # Simplified
        },
        "token_b": {
            "search_query": "Bitcoin",
            "dynamic": True,
            "keywords": ["bitcoin", "btc"]  # Simplified (same market, different outcomes)
        },
        "category": "crypto",
        "reason": "일일 심리 변화는 가격과 상관관계 높음",
        "expected_correlation": 0.70,
        "priority": "medium",
        "strategy_type": "convergence",
        "timeframe": "1day"
    },

    # ========== Major News Events (뉴스 기반) ==========
    {
        "name": "Crypto_Regulation_News",
        "description": "암호화폐 규제 뉴스 영향 (긍정 vs 부정)",
        "token_a": {
            "search_query": "Crypto",
            "dynamic": True,
            "keywords": ["crypto", "cryptocurrency"]  # Simplified
        },
        "token_b": {
            "search_query": "Crypto",
            "dynamic": True,
            "keywords": ["crypto", "cryptocurrency"]  # Simplified
        },
        "category": "crypto",
        "reason": "규제 뉴스는 즉각적인 가격 반응 유발",
        "expected_correlation": -0.80,
        "priority": "high",
        "strategy_type": "inverse",
        "timeframe": "3days"
    },

    # ========== Altcoin Correlation (동일 섹터) ==========
    {
        "name": "Layer2_Tokens_Correlation",
        "description": "Layer 2 토큰들 간 상관관계 (Arbitrum, Optimism 등)",
        "token_a": {
            "search_query": "Arbitrum",
            "dynamic": True,
            "keywords": ["arbitrum", "arb"]  # Simplified
        },
        "token_b": {
            "search_query": "Optimism",
            "dynamic": True,
            "keywords": ["optimism", "op"]  # Simplified
        },
        "category": "crypto",
        "reason": "같은 섹터 토큰은 함께 움직임",
        "expected_correlation": 0.75,
        "priority": "medium",
        "strategy_type": "convergence",
        "timeframe": "1week"
    },
]

# ============================================================
# 동적 시장 탐색 전략
# ============================================================

DYNAMIC_SEARCH_STRATEGIES = {
    "crypto_weekly": {
        "keywords": ["bitcoin", "ethereum", "week", "price"],
        "timeframe": "1week",
        "min_volume": 10000,
        "required_tokens": 2  # Binary market
    },
    "event_based": {
        "keywords": ["fed", "fomc", "meeting", "rate"],
        "timeframe": "48hours",
        "min_volume": 5000,
        "required_tokens": 2
    },
    "daily_sentiment": {
        "keywords": ["bullish", "bearish", "today"],
        "timeframe": "1day",
        "min_volume": 3000,
        "required_tokens": 2
    }
}

# ============================================================
# 전략별 권장 파라미터 (동일)
# ============================================================

STRATEGY_PARAMS = {
    "convergence": {
        "entry_z_threshold": 1.5,
        "exit_z_threshold": 0.5,
        "position_size": 0.3
    },
    "spread": {
        "entry_z_threshold": 2.0,
        "exit_z_threshold": 0.8,
        "position_size": 0.25
    },
    "inverse": {
        "entry_z_threshold": 2.5,
        "exit_z_threshold": 1.0,
        "position_size": 0.20
    }
}

# ============================================================
# Category-specific thresholds (업데이트)
# ============================================================

CATEGORY_THRESHOLDS = {
    "crypto": {
        "min_correlation": 0.60,  # 낮춤 (단기 시장은 노이즈 많음)
        "max_cointegration_pvalue": 0.10,  # 완화
        "min_data_points": 50,  # 낮춤 (단기 데이터)
        "entry_z_threshold": 1.8
    },
    "politics": {
        "min_correlation": 0.50,
        "max_cointegration_pvalue": 0.10,
        "min_data_points": 30,
        "entry_z_threshold": 1.5
    },
    "economics": {
        "min_correlation": 0.65,
        "max_cointegration_pvalue": 0.10,
        "min_data_points": 40,
        "entry_z_threshold": 1.5
    },
    "sports": {
        "min_correlation": 0.40,
        "max_cointegration_pvalue": 0.15,
        "min_data_points": 20,
        "entry_z_threshold": 2.0
    }
}

# ============================================================
# 동적 시장 탐색 헬퍼
# ============================================================

def should_use_dynamic_search(pair: dict) -> bool:
    """Check if pair requires dynamic market search"""
    return pair.get("token_a", {}).get("dynamic", False) or \
           pair.get("token_b", {}).get("dynamic", False)


def get_search_strategy(pair: dict) -> dict:
    """Get dynamic search strategy for pair"""
    timeframe = pair.get("timeframe", "1week")

    # Match timeframe to strategy
    if timeframe == "48hours":
        return DYNAMIC_SEARCH_STRATEGIES["event_based"]
    elif timeframe == "1day":
        return DYNAMIC_SEARCH_STRATEGIES["daily_sentiment"]
    else:
        return DYNAMIC_SEARCH_STRATEGIES["crypto_weekly"]


def get_pairs_by_priority(priority: str = "high") -> list:
    """Get pairs filtered by priority level"""
    return [p for p in CANDIDATE_PAIRS if p['priority'] == priority]


def get_pairs_by_category(category: str) -> list:
    """Get pairs filtered by category"""
    return [p for p in CANDIDATE_PAIRS if p['category'] == category]


def get_thresholds(category: str) -> dict:
    """Get trading thresholds for a category"""
    return CATEGORY_THRESHOLDS.get(category, CATEGORY_THRESHOLDS['crypto'])


def get_dynamic_pairs() -> list:
    """Get only pairs that require dynamic search"""
    return [p for p in CANDIDATE_PAIRS if should_use_dynamic_search(p)]


def get_static_pairs() -> list:
    """Get only pairs with fixed condition_ids"""
    return [p for p in CANDIDATE_PAIRS if not should_use_dynamic_search(p)]


# ============================================================
# Migration Notes
# ============================================================

"""
변경 사항:
1. 모든 장기 시장 제거 (2026, 2028)
2. 단기 시장으로 교체 (1day ~ 1week)
3. Dynamic search 도입 (실시간 시장 탐색)

사용 방법:
1. 정적 시장 (condition_id 있음):
   - 기존 방식 그대로 사용

2. 동적 시장 (dynamic=True):
   - Gamma API로 실시간 탐색
   - Keywords 기반 필터링
   - Timeframe 내 시장만 선택

예시:
    pair = CANDIDATE_PAIRS[0]
    if should_use_dynamic_search(pair):
        strategy = get_search_strategy(pair)
        # Gamma API 호출하여 matching markets 찾기
        markets = search_markets(
            keywords=strategy["keywords"],
            timeframe=strategy["timeframe"]
        )
"""
