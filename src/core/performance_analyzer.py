
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

STATE_FILE = "data/dashboard_state.json"

class PerformanceAnalyzer:
    def __init__(self, state_file=STATE_FILE):
        self.state_file = state_file

    def generate_report(self) -> str:
        """Generates a text-based performance report."""
        try:
            if not os.path.exists(self.state_file):
                return "⚠️ No state file found."

            with open(self.state_file, 'r') as f:
                state = json.load(f)
                
            positions = state.get('active_positions', [])
            balance = state.get('balance_usdc', 0)
            
            unrealized_pnl = 0
            winning_positions = 0
            losing_positions = 0
            total_invested = 0
            
            # Sort by PnL desc
            positions.sort(key=lambda x: x.get('pnl', 0), reverse=True)
            
            top_winners = []
            
            for p in positions:
                # Calculate simple unrealized PnL
                entry = p.get('entry', 0)
                current = p.get('current', entry)
                size = p.get('size', 0)
                
                # Sanity check for data anomalies (e.g. entry=0.001, cur=0.99)
                if entry < 0.01 and current > 0.9: 
                    # Skip anomalies in stats
                    continue
                    
                pnl_val = (current - entry) * size
                unrealized_pnl += pnl_val
                total_invested += (entry * size)
                
                if pnl_val > 0.01:
                    winning_positions += 1
                    if len(top_winners) < 3:
                        top_winners.append(f"🏆 {p.get('symbol', 'Unknown')[:20]}.. (+${pnl_val:.2f})")
                elif pnl_val < -0.01:
                    losing_positions += 1
                    
            total_positions = winning_positions + losing_positions
            win_rate = (winning_positions / total_positions * 100) if total_positions > 0 else 0
            
            report = (
                f"📊 **Swarm Performance Update**\n"
                f"🕒 {datetime.now().strftime('%H:%M %p')}\n\n"
                f"💰 **Balance:** ${balance:,.2f}\n"
                f"📈 **Active Positions:** {len(positions)}\n"
                f"💵 **Total Invested:** ${total_invested:,.2f}\n"
                f"📉 **Unrealized PnL:** ${unrealized_pnl:,.2f}\n"
                f"🎯 **Win Rate:** {win_rate:.1f}% ({winning_positions}W / {losing_positions}L)\n\n"
            )
            
            if top_winners:
                report += "**Top Winners:**\n" + "\n".join(top_winners)
            
            return report

        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            return f"❌ Error generating report: {e}"

