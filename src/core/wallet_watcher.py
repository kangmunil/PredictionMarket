import asyncio
import logging
import json
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
        self.w3 = Web3(Web3.HTTPProvider(self.config.RPC_URL))
        
        # Load CTF Exchange ABI
        try:
            with open("src/contracts/ctf_exchange_abi.json", "r") as f:
                self.ctf_abi = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load full CTF ABI: {e}. Using fallback.")
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
        from web3.middleware import ExtraDataToPOAMiddleware
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        self.targets = [addr.lower() for addr in self.config.TARGET_WALLETS]
        self.last_block = self.w3.eth.block_number

    async def _retry_rpc_call(self, func, *args, retries=3, delay=1.0):
        """Retries an RPC call with exponential backoff"""
        for i in range(retries):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args)
                else:
                    return func(*args)
            except Exception as e:
                if i == retries - 1:
                    raise e
                wait_time = delay * (2 ** i)
                logger.warning(f"RPC Error: {e}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

    async def run(self):
        logger.info(f"🐋 EliteMimic active. Watching {len(self.targets)} whales...")
        logger.info(f"🔗 RPC Endpoint: {self.config.RPC_URL}")
        
        while True:
            try:
                # Retry fetching block number
                current_block = await self._retry_rpc_call(lambda: self.w3.eth.block_number)
                
                if current_block > self.last_block:
                    # Scan blocks
                    for bn in range(self.last_block + 1, current_block + 1):
                        await self.process_block(bn)
                    self.last_block = current_block
                
                await asyncio.sleep(1) # Faster polling
            except Exception as e:
                logger.error(f"mimic_error (RPC/Network): {e}")
                await asyncio.sleep(2)

    async def process_block(self, block_num):
        try:
            # Retry fetching full block
            block = await self._retry_rpc_call(lambda: self.w3.eth.get_block(block_num, full_transactions=True))
            
            for tx in block.transactions:
                if tx['from'] and tx['from'].lower() in self.targets:
                    await self.handle_whale_tx(tx)
        except Exception as e:
             logger.error(f"Failed to process block {block_num}: {e}")

    async def handle_whale_tx(self, tx):
        """Decode and replicate whale moves using full ABI"""
        to_address = tx['to'].lower() if tx['to'] else ""
        
        if to_address == CTF_EXCHANGE.lower():
            try:
                # Data Integrity Check before decoding
                if not tx.get('input') or len(tx['input']) < 10:
                    logger.debug(f"Skipping empty/invalid input tx from {tx['from']}")
                    return

                # 1. Decode Function Input (Handles fillOrder and buy)
                try:
                    func_obj, func_params = self.ctf_contract.decode_function_input(tx['input'])
                except ValueError as ve:
                    # JSON/Decoding error handling
                    logger.debug(f"⚠️ Transaction decoding failed: {ve}")
                    return

                token_id = None
                side = None
                amount_usd = 0.0

                # Case A: fillOrder (Modern Proxy/Limit orders)
                if func_obj.fn_name == "fillOrder":
                    order = func_params.get('order', {})
                    token_id = str(order.get('tokenId'))
                    # side: 0 = BUY, 1 = SELL (Polymarket OrderSide enum)
                    side_raw = order.get('side')
                    side = "BUY" if side_raw == 0 else "SELL"
                    amount_raw = func_params.get('takerAmount', 0)
                    amount_usd = float(amount_raw) / 1e6
                
                # Case B: buy (Legacy/Direct AMM orders)
                elif func_obj.fn_name == "buy":
                    token_id = func_params.get('conditionId').hex()
                    outcome_idx = func_params.get('outcomeIndex')
                    side = "BUY" if outcome_idx == 0 else "SELL" 
                    amount_raw = func_params.get('amount', 0)
                    amount_usd = float(amount_raw) / 1e6

                if token_id:
                    logger.info(f"🚨 WHALE {side} DETECTED: {tx['from'][:10]}... | Token: {token_id[:15]}... | Amt: ${amount_usd:.2f}")

                    event_data = {
                        'wallet': tx['from'],
                        'token_id': token_id,
                        'side': side,
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
                            token_id=token_id,
                            source='WHALE',
                            score=0.95,
                            label=side
                        )
            except Exception as e:
                logger.error(f"EliteMimic Decoding Error: {e}")

if __name__ == "__main__":
    # Test watcher
    client = PolyClient(strategy_name="mimic_test")
    watcher = WalletWatcher(client)
    asyncio.run(watcher.run())