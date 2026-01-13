import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
from src.core.budget_manager import BudgetManager
from src.backtest.data_loader import DataLoader

logger = logging.getLogger(__name__)

class MockClient:
    """
    Simulates PolyClient behavior using historical data.
    """
    def __init__(self, price_feed: Dict[str, float]):
        self.price_feed = price_feed # Ref to current prices in engine
        self.orders = []
        self.config = type('Config', (), {'DRY_RUN': False, 'TAKER_FEE': 0.0, 'SLIPPAGE_BUFFER': 0.0})()
        
    def get_best_ask_price(self, token_id: str) -> float:
        return self.price_feed.get(token_id, 0.5)

    def get_best_bid_price(self, token_id: str) -> float:
        # Simulate spread
        return self.price_feed.get(token_id, 0.5) * 0.99

    async def place_limit_order(self, token_id: str, side: str, price: float, size: float) -> Optional[str]:
        # Assume fill if price matches (optimistic execution)
        current = self.price_feed.get(token_id)
        if current is None:
            return None
            
        filled = False
        if side.upper() == "BUY" and current <= price:
            filled = True
        elif side.upper() == "SELL" and current >= price:
            filled = True
            
        if filled:
            oid = f"mock_{len(self.orders)}_{int(datetime.now().timestamp())}"
            self.orders.append({
                "orderID": oid, "token_id": token_id, "side": side, 
                "price": price, "size": size, "filled": size, 
                "timestamp": datetime.now()
            })
            logger.info(f"✅ [MOCK FILL] {side} {token_id} @ {price:.3f} (Size: {size}) -> PnL Simulation")
            return oid
        
        return None

    async def get_usdc_balance(self) -> float:
        return 10000.0 # Mock balance

    async def get_order_status(self, order_id: str) -> str:
        return "FILLED" # Optimistic

class BacktestEngine:
    def __init__(self):
        self.data_loader = DataLoader()
        self.current_prices = {}
        self.client = MockClient(self.current_prices)
        self.budget_manager = BudgetManager(total_capital=1000.0)
        self.pnl = 0.0

    async def run(self, strategy_class, token_id: str, days: int = 7, tags: List[str] = None):
        logger.info(f"🚀 Starting Backtest for {token_id}...")
        
        # 1. Load Data
        csv_path = await self.data_loader.download_history(token_id, days)
        if not csv_path:
            logger.error("No data available.")
            return None

        history = self.data_loader.load_data(token_id)
        if not history:
            return None

        # 2. Initialize Strategy with Mock Client
        strategy = strategy_class(client=self.client, budget_manager=self.budget_manager)
        
        # 3. Replay Loop
        start_equity = 1000.0 # From Mock Balance
        
        for point in history:
            ts = point['timestamp']
            price = point['price']
            
            # Update Simulated Market
            self.current_prices[token_id] = price
            
            # Tick Strategy (Simulation Hook)
            if hasattr(strategy, "on_tick"):
                 await strategy.on_tick(token_id, price, ts)
        
        # 4. Calculate Results
        # Mark to market all open positions at last price
        last_price = history[-1]['price']
        total_pnl = 0.0
        
        # Simple aggregated PnL from closed trades (if we tracked them) + open positions
        # For now, we rely on MockClient orders
        trades = self.client.orders
        wins = 0
        volume = 0.0
        
        for order in trades:
            # Simplified PnL: updates assumes purely directional long/short relative to exit at end
            # In reality, need matching engine for entries/exits. 
            # This is a basic estimation: Entry vs Last Price
            entry = order['price']
            size = order['size']
            side = order['side']
            volume += (entry * size)
            
            trade_pnl = 0.0
            if side == "BUY":
                trade_pnl = (last_price - entry) * size
            else:
                trade_pnl = (entry - last_price) * size
            
            total_pnl += trade_pnl
            if trade_pnl > 0: wins += 1
            
        win_rate = (wins / len(trades)) * 100 if trades else 0.0
        roi = (total_pnl / start_equity) * 100
        
        if tags is None:
            tags = ["backtest"]
            
        results = {
            "token_id": token_id,
            "days": days,
            "trades_count": len(trades),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "total_volume": volume,
            "roi_percent": roi,
            "final_equity": start_equity + total_pnl,
            "tags": tags
        }
        
        self.generate_report(results)
        self.export_for_specialist(results)
        return results

    def generate_report(self, results):
        report = f"""
        ========================================
        📊 BACKTEST REPORT: {results['token_id'][:10]}...
        ========================================
        Duration:     {results['days']} days
        Trades:       {results['trades_count']}
        Win Rate:     {results['win_rate']:.1f}%
        Total PnL:    ${results['total_pnl']:.2f}
        ROI:          {results['roi_percent']:.2f}%
        Final Equity: ${results['final_equity']:.2f}
        ========================================
        """
        print(report)
        logger.info(report)

    def export_for_specialist(self, results):
        """Save results for MarketSpecialist (or other agents) to consume."""
        import json
        output_dir = "data/backtest_results"
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/result_{results['token_id']}.json"
        
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"💾 Results exported to {filename}")