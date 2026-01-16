import asyncio
import os
import argparse
import sys
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from supabase import create_client, Client
import logging

# Configure basic logging for script
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("Backtester")

# Load Env
load_dotenv()

class Backtester:
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        
        if not self.supabase_url or not self.supabase_key:
            print("❌ Error: SUPABASE_URL and SUPABASE_KEY must be set in .env")
            sys.exit(1)
            
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
        self.db_data = []

    async def fetch_data(self, use_mock: bool = False):
        """
        Fetch all necessary data for backtesting.
        """
        if use_mock:
            print("⚠️ USING MOCK DATA for Simulation Verification")
            import random
            random.seed(42)
            self.db_data = []
            for i in range(50):
                pnl = random.uniform(-50, 50)
                ev = random.uniform(-0.1, 0.3)
                conf = random.uniform(0.5, 0.95)
                # Correlate EV with PnL slightly for realistic mock
                if ev > 0.1: pnl += 10
                
                self.db_data.append({
                    "trade_id": f"mock_{i}",
                    "market_question": f"Mock Market {i}",
                    "outcome_pnl": pnl,
                    "ai_ev": ev,
                    "ai_conf": conf,
                    "validator_verified": random.choice([True, False])
                })
            print(f"✅ Generated {len(self.db_data)} mock records.")
            return

        print("📥 Fetching historical data from Supabase...")
        
        # 1. Fetch executed trades (Outcomes)
        try:
            response = self.supabase.table('trading_feedback').select("*").execute()
            feedback_rows = response.data
            
            if not feedback_rows:
                print("⚠️ No trading history found in 'trading_feedback'. Cannot backtest.")
                return

            print(f"✅ Loaded {len(feedback_rows)} trade records.")
            
            # 2. Fetch Analysis Context (The 'Why')
            resp_analysis = self.supabase.table('market_analysis').select("*").execute()
            analysis_rows = resp_analysis.data
            
            # Map event_id or question to analysis
            analysis_map = {row['event_id']: row for row in analysis_rows if row.get('event_id')}
            
            self.db_data = []
            
            for trade in feedback_rows:
                event_id = trade.get("event_id")
                analysis = analysis_map.get(event_id, {})
                
                record = {
                    "trade_id": trade.get("id"),
                    "market_question": trade.get("market_question"),
                    "outcome_pnl": float(trade.get("pnl", 0.0)),
                    "exit_reason": trade.get("exit_reason"),
                    "timestamp": trade.get("timestamp"),
                    "ai_ev": float(analysis.get("expected_value", 0.0)),
                    "ai_conf": float(analysis.get("confidence", 0.0)),
                    "validator_verified": analysis.get("validator_verified", False)
                }
                self.db_data.append(record)
                
            print(f"🔗 Linked {len(self.db_data)} trades with Analysis data.")
            
        except Exception as e:
            print(f"❌ Database Error: {e}")

    def run_simulation(self, min_ev: float, min_conf: float, require_verified: bool):
        """
        Re-play trades with new filters.
        """
        print(f"\n🚀 Running Simulation | Min EV: {min_ev} | Min Conf: {min_conf} | Verified Only: {require_verified}")
        
        stats = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "avoided_losses": 0.0,
            "missed_gains": 0.0,
            "filtered_count": 0
        }
        
        full_pnl = sum(r['outcome_pnl'] for r in self.db_data)
        
        for record in self.db_data:
            # Apply Filters
            passed = True
            
            # Filter 1: EV
            if record['ai_ev'] < min_ev:
                passed = False
                
            # Filter 2: Confidence
            if record['ai_conf'] < min_conf:
                passed = False
                
            # Filter 3: Validator (If data exists)
            # if require_verified and not record['validator_verified']:
            #    passed = False
            
            pnl = record['outcome_pnl']
            
            if passed:
                stats["total_trades"] += 1
                stats["total_pnl"] += pnl
                if pnl > 0: stats["wins"] += 1
                else: stats["losses"] += 1
            else:
                stats["filtered_count"] += 1
                if pnl < 0:
                    stats["avoided_losses"] += abs(pnl)
                elif pnl > 0:
                    stats["missed_gains"] += pnl

        # Report
        print("\n📊 --- Backtest Results ---")
        print(f"Original PnL:   ${full_pnl:+.2f} ({len(self.db_data)} trades)")
        print(f"Simulated PnL:  ${stats['total_pnl']:+.2f} ({stats['total_trades']} trades)")
        print(f"---------------------------")
        print(f"Win Rate:       {stats['wins']}/{stats['total_trades']} ({(stats['wins']/stats['total_trades']*100 if stats['total_trades'] else 0):.1f}%)")
        print(f"Filtered Out:   {stats['filtered_count']} trades")
        print(f"  - Avoided Loss: ${stats['avoided_losses']:.2f} (Good)")
        print(f"  - Missed Gains: ${stats['missed_gains']:.2f} (Bad)")
        
        diff = stats['total_pnl'] - full_pnl
        if diff > 0:
            print(f"\n✅ IMPROVEMENT: +${diff:.2f}")
        else:
            print(f"\n🔻 REGRESSION: ${diff:.2f}")

async def main():
    parser = argparse.ArgumentParser(description="Beehive Backtester")
    parser.add_argument("--min-ev", type=float, default=0.05, help="Minimum Expected Value to accept trade")
    parser.add_argument("--min-conf", type=float, default=0.7, help="Minimum Confidence Score (0.0-1.0)")
    parser.add_argument("--verified", action="store_true", help="Require Ensemble Verification (Future feature)")
    parser.add_argument("--mock", action="store_true", help="Use mock data for verification")
    
    args = parser.parse_args()
    
    backtester = Backtester()
    await backtester.fetch_data(use_mock=args.mock)
    backtester.run_simulation(args.min_ev, args.min_conf, args.verified)

if __name__ == "__main__":
    asyncio.run(main())
