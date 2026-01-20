
import unittest
import asyncio
from decimal import Decimal
from src.core.budget_manager import BudgetManager

class TestBudgetManager(unittest.IsolatedAsyncioTestCase):
    
    async def test_initialization(self):
        """Test proper initialization of the Unified Pool"""
        bm = BudgetManager(total_capital=100.0)
        self.assertEqual(bm.total_capital, Decimal("100.0"))
        self.assertEqual(bm.locked_funds, Decimal("0"))
        self.assertEqual(len(bm.allocations), 0)

    async def test_request_allocation_success(self):
        """Test successful fund allocation"""
        bm = BudgetManager(total_capital=100.0)
        
        # Request $50
        allocation_id = await bm.request_allocation("strategy_a", Decimal("50.0"))
        
        self.assertIsNotNone(allocation_id)
        self.assertEqual(bm.locked_funds, Decimal("50.0"))
        # Check stored tuple
        self.assertEqual(bm.allocations[allocation_id], (Decimal("50.0"), "strategy_a"))
        
        status = await bm.get_status()
        self.assertEqual(status['available'], 50.0)
        self.assertEqual(status['locked'], 50.0)

    async def test_request_allocation_insufficient_funds(self):
        """Test allocation denial when funds are low"""
        bm = BudgetManager(total_capital=10.0)
        
        # Request $50 (Available $10)
        allocation_id = await bm.request_allocation("strategy_a", Decimal("50.0"))
        
        self.assertIsNone(allocation_id)
        self.assertEqual(bm.locked_funds, Decimal("0"))
        self.assertEqual(len(bm.allocations), 0)

    async def test_consecutive_allocations(self):
        """Test multiple sequential allocations"""
        bm = BudgetManager(total_capital=100.0)
        
        id1 = await bm.request_allocation("strat_a", Decimal("40.0"))
        self.assertIsNotNone(id1)
        
        # Available = 60
        id2 = await bm.request_allocation("strat_b", Decimal("50.0"))
        self.assertIsNotNone(id2)
        
        # Available = 10
        id3 = await bm.request_allocation("strat_c", Decimal("20.0")) # Should fail
        self.assertIsNone(id3)
        
        self.assertEqual(bm.locked_funds, Decimal("90.0"))

    async def test_release_allocation_success(self):
        """Test successful release of funds"""
        bm = BudgetManager(total_capital=100.0)
        
        alloc_id = await bm.request_allocation("strategy_a", Decimal("50.0"))
        self.assertEqual(bm.locked_funds, Decimal("50.0"))
        
        await bm.release_allocation("strategy_a", alloc_id, actual_spent=Decimal("10.0"))
        
        self.assertEqual(bm.locked_funds, Decimal("0")) # Released reservation
        self.assertEqual(len(bm.allocations), 0)

    async def test_release_allocation_wrong_strategy(self):
        """Test security check: prevent Strategy B from releasing Strategy A's funds"""
        bm = BudgetManager(total_capital=100.0)
        
        alloc_id = await bm.request_allocation("strategy_a", Decimal("50.0"))
        
        # Attempt malicious release
        await bm.release_allocation("strategy_b", alloc_id, actual_spent=Decimal("0"))
        
        # Should still be locked
        self.assertEqual(bm.locked_funds, Decimal("50.0"))
        self.assertIn(alloc_id, bm.allocations)

    async def test_update_total_capital(self):
        """Test external balance sync"""
        bm = BudgetManager(total_capital=100.0)
        
        # Allocate 50
        await bm.request_allocation("strat_a", Decimal("50.0"))
        
        # Balance drops externally
        bm.update_total_capital(60.0)
        
        # Available should be 60 - 50 = 10
        status = await bm.get_status()
        self.assertEqual(status['total_capital'], 60.0)
        self.assertEqual(status['available'], 10.0)

if __name__ == "__main__":
    unittest.main()
