import os
import sys
import asyncio
import logging
from decimal import Decimal

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.clob_client import PolyClient

from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ApproveAllowance")

def main():
    logger.info("Initializing PolyClient...")
    client = PolyClient()
    
    if not client.rest_client:
        logger.error("❌ REST client not initialized (Check Private Key)")
        return

    try:
        logger.info(f"🔑 Funder: {client.config.FUNDER_ADDRESS}")
        
        # 1. Check Allowance
        logger.info("🔍 Checking Collateral Allowance...")
        
        # Create params
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        
        # get_balance_allowance returns a dictionary like {'allowance': '0'} or just the value?
        # Let's inspect the return.
        resp = client.rest_client.get_balance_allowance(params)
        logger.info(f"📋 Raw Response: {resp}")
        
        allowance_val = 0.0
        if isinstance(resp, dict):
            allowance_val = float(resp.get('allowance', 0))
        else:
            allowance_val = float(resp)

        logger.info(f"✅ Current Allowance: ${allowance_val}")
        
        # 3. Approve if needed
        required = 1000.0
        if allowance_val < required:
            logger.info(f"⚠️ Allowance < {required}. Approving...")
            
            # Update allowance
            # update_balance_allowance(params)
            # Typically sets to max if not specified, or checks usage.
            # Wait, update_balance_allowance might take amount?
            # Checking library usage patterns: update_balance_allowance usually signs a permit or tx.
            # It takes params.
            
            tx_hash = client.rest_client.update_balance_allowance(params)
            logger.info(f"🚀 Approval Transaction/Signature Sent! Hash: {tx_hash}")
        else:
            logger.info("✅ Allowance is sufficient.")
            
    except Exception as e:
        logger.error(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
