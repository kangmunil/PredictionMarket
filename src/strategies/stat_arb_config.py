"""
Statistical Arbitrage Pair Configuration
=========================================

Defines logical pairs for cointegration testing.

Pair Selection Criteria:
1. **Logical Correlation**: Markets should be economically/logically related
2. **Sufficient Liquidity**: Both markets need active trading
3. **Similar Time Horizons**: Markets should close around the same time
4. **Clear Causality**: Understand WHY they might be cointegrated

Examples:
- Crypto majors (BTC/ETH correlation)
- Political party dynamics (Presidential/Senate races)
- Sports team performance (League winner correlations)
- Economic indicators (GDP/Unemployment)

Author: ArbHunter V2.0
Created: 2026-01-02
"""

# Candidate Pairs for Statistical Arbitrage
# Format: {name, token_a, token_b, category, reason}

CANDIDATE_PAIRS = [
    # ========== CRYPTO MARKETS ==========
    {
        "name": "BTC_ETH_Weekly_Correlation",
        "description": "Bitcoin Proxy (MSTR) vs Ethereum Proxy",
        "token_a": {
            "condition_id": "0x19ee98e348c0ccb341d1b9566fa14521566e9b2ea7aed34dc407a0ec56be36a2",
            "search_query": "Bitcoin"
        },
        "token_b": {
            "condition_id": "0xe6508d867d153a268bdab732aa8abc8cc57e652d28a23aa042da40895bf031b2",
            "search_query": "Ethereum"
        },
        "category": "crypto",
        "reason": "Strong correlation between major crypto assets",
        "expected_correlation": 0.85,
        "priority": "high"
    },

    {
        "name": "BTC_SOL_Correlation",
        "description": "Bitcoin vs Solana price movement",
        "token_a": {
            "condition_id": "",  # Will be dynamically searched
            "search_query": "Bitcoin 100k"
        },
        "token_b": {
            "condition_id": "",
            "search_query": "Solana 500"
        },
        "category": "crypto",
        "reason": "BTC and SOL highly correlated altcoin",
        "expected_correlation": 0.80,
        "priority": "high"
    },

    {
        "name": "ETH_SOL_Altcoin_Pair",
        "description": "Ethereum vs Solana major altcoins",
        "token_a": {
            "condition_id": "",
            "search_query": "Ethereum 10k"
        },
        "token_b": {
            "condition_id": "",
            "search_query": "Solana price"
        },
        "category": "crypto",
        "reason": "Leading smart contract platforms",
        "expected_correlation": 0.75,
        "priority": "medium"
    },

    # ========== POLITICAL MARKETS ==========
    {
        "name": "Presidential_Senate_Correlation",
        "description": "Presidential winner vs Senate control",
        "token_a": {
            "condition_id": "",
            "search_query": "Trump win 2024"
        },
        "token_b": {
            "condition_id": "",
            "search_query": "Republican Senate 2024"
        },
        "category": "politics",
        "reason": "Presidential coattails effect",
        "expected_correlation": 0.75,
        "priority": "medium"
    },

    {
        "name": "GOP_Control_Both_Chambers",
        "description": "GOP Senate vs House control",
        "token_a": {
            "condition_id": "",
            "search_query": "Republican Senate majority"
        },
        "token_b": {
            "condition_id": "",
            "search_query": "Republican House majority"
        },
        "category": "politics",
        "reason": "Unified government correlation",
        "expected_correlation": 0.70,
        "priority": "medium"
    },

    # ========== CRYPTO REGULATION PAIRS ==========
    {
        "name": "Crypto_ETF_SEC_Policy",
        "description": "ETF approval vs SEC crypto policy",
        "token_a": {
            "condition_id": "",
            "search_query": "Bitcoin ETF approval"
        },
        "token_b": {
            "condition_id": "",
            "search_query": "SEC crypto regulation"
        },
        "category": "crypto",
        "reason": "Regulatory environment correlation",
        "expected_correlation": 0.65,
        "priority": "low"
    },

    # ========== TECH MARKET PAIRS ==========
    {
        "name": "AI_Stocks_Tech_Index",
        "description": "AI stock performance vs tech index",
        "token_a": {
            "condition_id": "",
            "search_query": "Nvidia stock price"
        },
        "token_b": {
            "condition_id": "",
            "search_query": "QQQ tech index"
        },
        "category": "tech",
        "reason": "AI sector drives tech index",
        "expected_correlation": 0.70,
        "priority": "low"
    },

    # ========== MACRO ECONOMIC PAIRS ==========
    {
        "name": "Fed_Rate_Inflation_Link",
        "description": "Fed rate decisions vs inflation targets",
        "token_a": {
            "condition_id": "",
            "search_query": "Fed rate cut 2025"
        },
        "token_b": {
            "condition_id": "",
            "search_query": "Inflation below 2%"
        },
        "category": "economics",
        "reason": "Direct monetary policy relationship",
        "expected_correlation": -0.60,  # Negative correlation
        "priority": "medium"
    },

    # ========== SPORTS BETTING PAIRS ==========
    {
        "name": "NBA_Championship_Conference",
        "description": "NBA Champion vs Conference winner",
        "token_a": {
            "condition_id": "",
            "search_query": "Lakers NBA Champion"
        },
        "token_b": {
            "condition_id": "",
            "search_query": "Western Conference winner"
        },
        "category": "sports",
        "reason": "Must win conference to win championship",
        "expected_correlation": 0.90,
        "priority": "low"
    },

    # ========== ADDITIONAL CRYPTO PAIRS ==========
    {
        "name": "XRP_SEC_Lawsuit_Outcome",
        "description": "XRP price vs SEC lawsuit resolution",
        "token_a": {
            "condition_id": "",
            "search_query": "XRP price 2025"
        },
        "token_b": {
            "condition_id": "",
            "search_query": "Ripple SEC lawsuit win"
        },
        "category": "crypto",
        "reason": "Direct legal impact on XRP valuation",
        "expected_correlation": 0.85,
        "priority": "medium"
    }
]


# Category-specific thresholds
CATEGORY_THRESHOLDS = {
    "crypto": {
        "min_correlation": 0.75,
        "max_cointegration_pvalue": 0.05,
        "min_data_points": 100,
        "entry_z_threshold": 2.0
    },
    "politics": {
        "min_correlation": 0.60,
        "max_cointegration_pvalue": 0.05,
        "min_data_points": 50,
        "entry_z_threshold": 1.8
    },
    "sports": {
        "min_correlation": 0.40,
        "max_cointegration_pvalue": 0.10,  # More lenient
        "min_data_points": 30,
        "entry_z_threshold": 2.5  # More conservative
    },
    "economics": {
        "min_correlation": 0.70,
        "max_cointegration_pvalue": 0.05,
        "min_data_points": 60,
        "entry_z_threshold": 1.5  # More aggressive (macroeconomic data is reliable)
    },
    "finance": {
        "min_correlation": 0.80,
        "max_cointegration_pvalue": 0.05,
        "min_data_points": 100,
        "entry_z_threshold": 2.0
    },
    "tech": {
        "min_correlation": 0.60,
        "max_cointegration_pvalue": 0.05,
        "min_data_points": 40,
        "entry_z_threshold": 2.0
    },
    "weather": {
        "min_correlation": 0.50,
        "max_cointegration_pvalue": 0.10,
        "min_data_points": 30,
        "entry_z_threshold": 2.5
    }
}


def get_pairs_by_priority(priority: str = "high") -> list:
    """Get pairs filtered by priority level"""
    return [p for p in CANDIDATE_PAIRS if p.get('priority') == priority]


def get_pairs_by_category(category: str) -> list:
    """Get pairs filtered by category"""
    return [p for p in CANDIDATE_PAIRS if p.get('category') == category]


def get_thresholds(category: str) -> dict:
    """Get trading thresholds for a category"""
    return CATEGORY_THRESHOLDS.get(category, CATEGORY_THRESHOLDS['crypto'])
