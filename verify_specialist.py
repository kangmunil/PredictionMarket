from src.core.market_specialist import MarketSpecialist
import logging

logging.basicConfig(level=logging.INFO)

def verify():
    print("🧠 Initializing Market Specialist...")
    specialist = MarketSpecialist()
    
    print("\n📊 Checking Internal Stats:")
    found_stats = False
    for tag, stats in specialist.tag_stats.items():
        print(f"   - Tag: {tag.upper()} | Wins: {stats['wins']:.1f} | Losses: {stats['losses']:.1f} | PnL: ${stats['pnl']:.2f}")
        found_stats = True
        
    if found_stats:
        print("\n✅ Verification SUCCESS: Specialist has learned from backtests.")
    else:
        print("\n❌ Verification FAILED: No stats found.")

if __name__ == "__main__":
    verify()
