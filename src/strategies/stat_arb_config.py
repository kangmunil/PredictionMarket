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
            # "MicroStrategy sells any Bitcoin in 2025?"
            # This is a very active market correlated with BTC price
            "condition_id": "0x19ee98e348c0ccb341d1b9566fa14521566e9b2ea7aed34dc407a0ec56be36a2", 
            "search_query": "Bitcoin"
        },
        "token_b": {
            # "Will Ethereum hit $10k in 2025?"
            # Using a known active ETH market ID
            "condition_id": "0xe6508d867d153a268bdab732aa8abc8cc57e652d28a23aa042da40895bf031b2",
            "search_query": "Ethereum"
        },
        "category": "crypto",
        "reason": "Strong correlation between major crypto assets",
        "expected_correlation": 0.85,
        "priority": "high"
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
