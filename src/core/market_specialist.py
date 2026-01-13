import csv
import logging
import os
from collections import defaultdict
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class MarketSpecialist:
    """
    Market Specialist - "Know Thy Self"
    ===================================
    Analyzes past trade performance to identify winning market categories.
    Provides multipliers to prioritize markets where the bot performs best.
    """

    def __init__(self, history_file: str = "data/trades_log.csv"):
        self.history_file = history_file
        self.category_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
        self.tag_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
        
        # Default multipliers
        self.default_multiplier = 1.0
        self.min_multiplier = 0.5
        self.max_multiplier = 2.0
        
        # Load history on init
        self.analyze_history()
        self.analyze_backtests()

    def analyze_history(self):
        """Re-scan trade history to update stats."""
        if not os.path.exists(self.history_file):
            logger.info("New specialist: No trade history found yet.")
            return

        try:
            with open(self.history_file, 'r') as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    # Check if trade matches known completion status
                    # In universal log, existence of row often means completion, but check 'pnl' validity
                    if not row.get("pnl"):
                        continue
                        
                    pnl = float(row.get("pnl", 0.0))
                    
                    market_name = row.get("market_question") or row.get("pair_name") or ""
                    market_name = market_name.lower()
                    
                    # 1. Try explicit tags
                    tags = []
                    raw_tags = row.get("tags")
                    if raw_tags:
                        # Handle list string or simple comma sep
                        clean = raw_tags.replace("[", "").replace("]", "").replace("'", "")
                        tags = [t.strip().lower() for t in clean.split(",") if t.strip()]
                    
                    # 2. Infer if missing
                    if not tags:
                        tags = self._infer_tags(market_name)
                    
                    is_win = pnl > 0
                    
                    for tag in tags:
                        stats = self.tag_stats[tag]
                        stats["pnl"] += pnl
                        if is_win:
                            stats["wins"] += 1
                        else:
                            stats["losses"] += 1
                    
                    count += 1
                
            logger.info(f"🎓 Specialist analyzed {count} closed trades.")
            
            self._log_top_performers()

        except Exception as e:
            logger.error(f"❌ Specialist analysis failed: {e}")

    def analyze_backtests(self, backtest_dir="data/backtest_results"):
        """Ingest backtest results to refine category scoring."""
        import json
        import glob
        
        if not os.path.exists(backtest_dir):
            return

        files = glob.glob(f"{backtest_dir}/*.json")
        count = 0
        
        for filepath in files:
            try:
                with open(filepath, 'r') as f:
                    result = json.load(f)
                    
                # Extract metrics
                token_id = result.get("token_id", "")
                pnl = result.get("total_pnl", 0.0)
                win_rate = result.get("win_rate", 0.0)
                
                # Infer tags from Token ID or lookups
                # Since report doesn't have market question, we need a way to look it up or infer.
                # Use a generic 'backtest' tag or try to fetch details if possible?
                # For now, simplistic approach: trust the PnL impacts 'general' confidence 
                # OR we try to fetch details. But fetching is async/slow.
                # Let's attach the category/tags TO the backtest result in engine.py first!
                
                # Assuming engine adds tags in future. For now, we skip tag update 
                # unless tags are in result.
                tags = result.get("tags", [])
                
                # If no tags, we can't really attribute to a category easily 
                # without an ID lookup. 
                # Let's optimistically assume generic backtest boosting if positive.
                if not tags:
                    continue
                    
                for tag in tags:
                    stats = self.tag_stats[tag]
                    stats["pnl"] += pnl
                    # Weighted impact
                    if pnl > 0: stats["wins"] += (result.get("trades_count", 0) * (win_rate/100))
                    else: stats["losses"] += (result.get("trades_count", 0) * ((100-win_rate)/100))
                
                count += 1
            except Exception as e:
                logger.debug(f"Skipping bad backtest file {filepath}: {e}")
                
        if count > 0:
            logger.info(f"🔮 Specialist absorbed wisdom from {count} simulations.")

    def get_market_score(self, market: Dict) -> float:
        """
        Calculate a multiplier (0.5x to 2.0x) for this market based on history.
        """
        question = market.get("question", "").lower()
        tags = self._infer_tags(question)
        
        # If explicit tags available in market dict, use them too
        if "tags" in market:
            if isinstance(market["tags"], list):
                tags.extend([str(t).lower() for t in market["tags"]])
        
        if not tags:
            return self.default_multiplier
            
        # Average the multipliers of all matching tags
        multipliers = []
        for tag in set(tags):
            multipliers.append(self._get_tag_multiplier(tag))
            
        if not multipliers:
            return self.default_multiplier
            
        avg_mult = sum(multipliers) / len(multipliers)
        return avg_mult

    def _get_tag_multiplier(self, tag: str) -> float:
        stats = self.tag_stats.get(tag)
        if not stats:
            return self.default_multiplier
            
        total_trades = stats["wins"] + stats["losses"]
        if total_trades < 3: # Not enough data
            return self.default_multiplier
            
        win_rate = stats["wins"] / total_trades
        
        # Simple Logic:
        # > 60% WR -> Boost
        # < 40% WR -> Penalty
        
        if win_rate >= 0.75:
            return 1.5
        elif win_rate >= 0.60:
            return 1.2
        elif win_rate <= 0.30:
            return 0.6
        elif win_rate <= 0.40:
            return 0.8
            
        return 1.0

    def _infer_tags(self, text: str) -> List[str]:
        """Simple keyword extraction for categorization"""
        tags = []
        text = text.lower()
        
        mapping = {
            "crypto": ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto"],
            "politics": ["trump", "biden", "election", "poll", "president", "senate"],
            "economy": ["fed", "rate", "inflation", "cpi", "gdp", "recession"],
            "sports": ["nba", "nfl", "soccer", "league", "game"],
            "tech": ["openai", "gpt", "google", "apple", "nvidia", "stock"]
        }
        
        for category, keywords in mapping.items():
            for kw in keywords:
                if kw in text:
                    tags.append(category)
                    break # One tag per category group is enough
        
        return tags

    def _log_top_performers(self):
        sorted_tags = sorted(
            self.tag_stats.items(), 
            key=lambda item: item[1]['pnl'], 
            reverse=True
        )
        if sorted_tags:
            top = sorted_tags[0]
            logger.info(f"🏆 Best Category: {top[0].upper()} (PnL: ${top[1]['pnl']:.2f})")
