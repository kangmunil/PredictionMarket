import asyncio
import logging
from web3 import Web3
from src.core.config import Config
from src.core.clob_client import PolyClient

logger = logging.getLogger(__name__)

# Polymarket CTF Exchange Address
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

class WalletWatcher:
    """
    EliteMimic Engine: Copy trades from whale wallets in real-time.
    """
    def __init__(self, client: PolyClient, agent=None, ai_brain=None, signal_bus=None):
        self.client = client
        self.config = Config()
        self.agent = agent
        self.ai_brain = ai_brain
        self.signal_bus = signal_bus
        self.on_trade_callback = None # Added for run_elitemimic.py support
        
        # Using a reliable RPC is critical for copy trading speed
        self.w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
        
        # CTF Exchange ABI (Simplified for the most important methods)
        self.ctf_abi = [
            {
                "name": "buy",
                "type": "function",
                "inputs": [
                    {"name": "conditionId", "type": "bytes32"},
                    {"name": "outcomeIndex", "type": "uint256"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "minOutcomeTokens", "type": "uint256"}
                ]
            }
        ]
        self.ctf_contract = self.w3.eth.contract(address=CTF_EXCHANGE, abi=self.ctf_abi)

        # Fix for Polygon POA (Proof of Authority) chain
        try:
            from web3.middleware import GethPoAMiddleware
            self.w3.middleware_onion.inject(GethPoAMiddleware, layer=0)
        except: pass

        self.targets = [addr.lower() for addr in self.config.TARGET_WALLETS]
        self.last_block = self.w3.eth.block_number

    async def run(self):
        logger.info(f"🐋 EliteMimic active. Watching {len(self.targets)} whales...")
        while True:
            try:
                current_block = self.w3.eth.block_number
                if current_block > self.last_block:
                    # Scan blocks
                    for bn in range(self.last_block + 1, current_block + 1):
                        await self.process_block(bn)
                    self.last_block = current_block
                await asyncio.sleep(1) # Faster polling
            except Exception as e:
                logger.error(f"mimic_error: {e}")
                await asyncio.sleep(2)

    async def process_block(self, block_num):
        block = self.w3.eth.get_block(block_num, full_transactions=True)
        for tx in block.transactions:
            if tx['from'] and tx['from'].lower() in self.targets:
                await self.handle_whale_tx(tx)

    async def handle_whale_tx(self, tx):
        """Decode and replicate whale moves"""
        to_address = tx['to'].lower() if tx['to'] else ""
        
        if to_address == CTF_EXCHANGE.lower():
            try:
                # 1. Decode Function Input
                func_obj, func_params = self.ctf_contract.decode_function_input(tx['input'])
                
                if func_obj.fn_name == "buy":
                    market_id = func_params['conditionId'].hex()
                    outcome_idx = func_params['outcomeIndex']
                    amount_wei = func_params['amount']
                    amount_usd = float(self.w3.from_hex(hex(amount_wei)) if isinstance(amount_wei, str) else amount_wei) / 1e6 # Usually USDC

                    logger.info(f"🚨 WHALE BUY DETECTED: {tx['from'][:10]}... bought index {outcome_idx} on market {market_id[:10]}...")

                    event_data = {
                        'wallet': tx['from'],
                        'market_id': market_id,
                        'outcome_index': outcome_idx,
                        'side': 'BUY' if outcome_idx == 0 else 'SELL', # Simplified YES/NO
                        'price': 0.5, # Price needs separate lookup
                        'size': amount_usd,
                        'raw_tx': tx
                    }

                    # 2. Trigger Callback (for run_elitemimic.py)
                    if self.on_trade_callback:
                        if asyncio.iscoroutinefunction(self.on_trade_callback):
                            await self.on_trade_callback(event_data)
                        else:
                            self.on_trade_callback(event_data)

                    # 3. Hive Mind Update
                    if self.signal_bus:
                        await self.signal_bus.update_signal(
                            token_id=market_id,
                            source='WHALE',
                            score=0.95,
                            side="BUY"
                        )
            except Exception as e:
                logger.error(f"Decoding failed: {e}")

if __name__ == "__main__":
    # Test watcher
    client = PolyClient(strategy_name="mimic_test")
    watcher = WalletWatcher(client)
    asyncio.run(watcher.run())