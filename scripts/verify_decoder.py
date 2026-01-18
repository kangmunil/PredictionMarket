import asyncio
import sys
import os
import json
from decimal import Decimal
from web3 import Web3

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.core.wallet_watcher_v2 import EnhancedWalletWatcher
from src.core.config import Config
from src.core.clob_client import PolyClient

async def run_verification():
    print("🔬 Starting WalletWatcher Decoder Verification...")
    
    # 1. Initialize Watcher (Mock Client)
    client = PolyClient(strategy_name="tester")
    watcher = EnhancedWalletWatcher(client)
    
    if not watcher.ctf_contract:
        print("❌ Failed to load CTF Contract. Check ABI file.")
        return

    print("✅ Watcher initialized. ABI loaded.")

    # 2. Test Case A: Maker Sells (Side=1), Whale Buys
    print("\n--- Test Case A: Whale BUYS (Maker Sells) ---")
    maker_amount = 1000000 # 1 Token
    taker_amount = 600000  # 0.6 USDC
    
    # Structure of Order tuple from ABI: 
    # (nonce, maker, taker, tokenId, makerAmount, takerAmount, side, feeRateBps, nonce, expiration, signature)
    # Side 1 = SELL
    mock_order = (
        0, # nonce
        "0x0000000000000000000000000000000000000001", # maker
        "0x0000000000000000000000000000000000000002", # taker
        123456789, # tokenId
        maker_amount, # makerAmount (Tokens)
        taker_amount, # takerAmount (USDC)
        1, # side (SELL)
        0, 0, 0, b'' # fees, etc
    )
    
    try:
        # Encode 'fillOrder' call
        tx_input = watcher.ctf_contract.encode_abi(
            "fillOrder",
            args=[mock_order, taker_amount]
        )
        
        mock_tx = {
            'hash': b'\x00'*32,
            'input': tx_input
        }
        
        result = await watcher._decode_trade_transaction(mock_tx)
        
        print(f"📥 Input: Maker Side=SELL(1), MakerAmt={maker_amount}, TakerAmt={taker_amount}")
        print(f"out -> {result}")
        
        if result and result['side'] == 'BUY' and result['token_id'] == '123456789':
            print("✅ PASS: Correctly identified Whale BUY")
            if abs(result['price'] - 0.6) < 0.001:
                print("✅ PASS: Price calculated correctly (0.6)")
            else:
                print(f"❌ FAIL: Price mismatch. Got {result['price']}, expected 0.6")
        else:
            print("❌ FAIL: Logic error in Case A")

    except Exception as e:
        print(f"❌ FAIL: Exception in Case A: {e}")

    # 3. Test Case B: Maker Buys (Side=0), Whale Sells
    print("\n--- Test Case B: Whale SELLS (Maker Buys) ---")
    maker_amount_b = 600000  # Maker offers 0.6 USDC
    taker_amount_b = 1000000 # Maker wants 1 Token
    
    # Side 0 = BUY
    mock_order_b = (
        0, 
        "0x0000000000000000000000000000000000000001",
        "0x0000000000000000000000000000000000000002", 
        987654321, 
        maker_amount_b, # makerAmount (USDC)
        taker_amount_b, # takerAmount (Tokens)
        0, # side (BUY)
        0, 0, 0, b''
    )
    
    try:
        tx_input_b = watcher.ctf_contract.encode_abi(
            "fillOrder",
            args=[mock_order_b, taker_amount_b]
        )
        
        mock_tx_b = {
            'hash': b'\x00'*32,
            'input': tx_input_b
        }
        
        result_b = await watcher._decode_trade_transaction(mock_tx_b)
        
        print(f"📥 Input: Maker Side=BUY(0), MakerAmt={maker_amount_b}, TakerAmt={taker_amount_b}")
        print(f"out -> {result_b}")
        
        if result_b and result_b['side'] == 'SELL' and result_b['token_id'] == '987654321':
            print("✅ PASS: Correctly identified Whale SELL")
            if abs(result_b['price'] - 0.6) < 0.001:
                print("✅ PASS: Price calculated correctly (0.6)")
            else:
                print(f"❌ FAIL: Price mismatch. Got {result_b['price']}, expected 0.6")
        else:
            print("❌ FAIL: Logic error in Case B")

    except Exception as e:
        print(f"❌ FAIL: Exception in Case B: {e}")

    print("\n🏁 Verification Complete.")

if __name__ == "__main__":
    asyncio.run(run_verification())
