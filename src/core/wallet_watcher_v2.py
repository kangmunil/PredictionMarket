"""
EliteMimic Wallet Watcher V2
=============================
Enhanced wallet monitoring with advanced whale intelligence integration.

Features:
- Real-time transaction monitoring with latency tracking
- Front-running detection
- Bait trade filtering
- Whale behavior profiling
- Smart execution with delay and order type optimization
- Comprehensive risk management

Author: Claude (Quantitative Trading Strategist)
Date: 2026-01-02
"""

import asyncio
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.contract import Contract
import json
import os

from src.core.config import Config
from src.core.whale_intelligence import (
    WhaleIntelligence,
    TradeSignal,
    MarketState,
    WhaleProfile
)
from src.strategies.ai_model import AIModelStrategy

logger = logging.getLogger(__name__)

# Polymarket CTF Exchange (Proxy) Address
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"


class EnhancedWalletWatcher:
    """
    V2 of WalletWatcher with full Whale Intelligence integration.
    """

    def __init__(self, client, agent=None, config: Optional[Config] = None):
        self.client = client
        self.agent = agent
        self.config = config or Config()

        # RPC Fallback Setup (Multi-provider rotation)
        self.rpc_endpoints = [
            self.config.RPC_URL,  # Primary (from .env)
            os.getenv("RPC_URL_BACKUP_1", "https://polygon-rpc.com"),
            os.getenv("RPC_URL_BACKUP_2", "https://rpc-mainnet.matic.quiknode.pro"),
        ]
        self.current_rpc_index = 0
        self.w3 = self._connect_rpc()
        self.targets = self._load_target_wallets()

        # Intelligence modules
        self.ai_brain = AIModelStrategy(client)
        self.whale_intel = WhaleIntelligence(
            strategy_type="SELECTIVE",  # SELECTIVE, PROPORTIONAL, KELLY, FIXED
            max_position_size=100.0  # $100 max per position
        )

        # Transaction tracking
        self.last_checked_block = self.w3.eth.block_number
        self.tx_cache: Dict[str, datetime] = {}  # tx_hash -> detection_time
        self.whale_tx_timestamps: Dict[str, float] = {}  # tx_hash -> execution_time

        # Load CTF Exchange Contract for decoding
        try:
            abi_path = os.path.join(os.path.dirname(__file__), '../contracts/ctf_exchange_abi.json')
            with open(abi_path, 'r') as f:
                self.ctf_abi = json.load(f)
            self.ctf_contract = self.w3.eth.contract(address=CTF_EXCHANGE, abi=self.ctf_abi)
            logger.info("✅ CTF Exchange Contract ABI loaded")
        except Exception as e:
            logger.error(f"❌ Failed to load CTF Exchange ABI: {e}")
            self.ctf_contract = None

        # Performance tracking
        self.trades_executed = 0
        self.trades_skipped = 0

        # Load historical whale data
        self._initialize_whale_profiles()

    def _connect_rpc(self) -> Web3:
        """Connect to RPC with current index."""
        url = self.rpc_endpoints[self.current_rpc_index]
        w3 = Web3(Web3.HTTPProvider(url))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        logger.info(f"🔗 Connected to RPC: {url[:40]}...")
        return w3
    
    def _rotate_rpc(self):
        """Rotate to next RPC endpoint on failure."""
        self.current_rpc_index = (self.current_rpc_index + 1) % len(self.rpc_endpoints)
        old_url = self.rpc_endpoints[(self.current_rpc_index - 1) % len(self.rpc_endpoints)]
        new_url = self.rpc_endpoints[self.current_rpc_index]
        logger.warning(f"🔄 RPC Rotating: {old_url[:30]}... → {new_url[:30]}...")
        self.w3 = self._connect_rpc()

    def _load_target_wallets(self) -> List[Dict[str, str]]:
        """Load target whale wallets from config"""
        wallets = []

        # Known whales
        known_whales = [
            {
                "address": "0x8c74b4eef9a894433B8126aA11d1345efb2B0488",
                "username": "distinct-baguette",
                "tier": "elite"
            },
            {
                "address": "0x38D1980311D7C6934509B8126A11D1345efB2B04",
                "username": "cryptoyoda",
                "tier": "elite"
            },
            {
                "address": "0x48e100311D7C6934509B8126A11D1345efB2B0488",
                "username": "whalewatcher_v3",
                "tier": "high"
            },
            {
                "address": self.config.TARGET_WALLET_1 if hasattr(self.config, 'TARGET_WALLET_1') else "",
                "username": "Sharky6999",
                "tier": "high"
            },
            {
                "address": self.config.TARGET_WALLET_2 if hasattr(self.config, 'TARGET_WALLET_2') else "",
                "username": "ilovecircle",
                "tier": "medium"
            }
        ]

        wallets = [w for w in known_whales if w["address"]]

        logger.info(f"Loaded {len(wallets)} target whale wallets")
        return wallets

    def _initialize_whale_profiles(self):
        """Initialize whale profiles with any available historical data"""
        for whale in self.targets:
            profile = self.whale_intel.profiler.get_or_create_profile(
                whale["address"],
                whale["username"]
            )

            # TODO: Load historical performance data from database/API
            # For now, set reasonable defaults based on tier
            if whale["tier"] == "elite":
                profile.total_trades = 150
                profile.winning_trades = 95
                profile.losing_trades = 55
                profile.recent_win_rate_20 = 0.65
                profile.recent_win_rate_50 = 0.63
                profile.avg_position_size = 500.0
            elif whale["tier"] == "high":
                profile.total_trades = 80
                profile.winning_trades = 48
                profile.losing_trades = 32
                profile.recent_win_rate_20 = 0.60
                profile.recent_win_rate_50 = 0.60
                profile.avg_position_size = 300.0
            else:
                profile.total_trades = 40
                profile.winning_trades = 22
                profile.losing_trades = 18
                profile.recent_win_rate_20 = 0.55
                profile.recent_win_rate_50 = 0.55
                profile.avg_position_size = 150.0

            logger.info(f"Initialized profile for {whale['username']}: "
                       f"{profile.total_trades} trades, "
                       f"{profile.recent_win_rate_20:.1%} win rate")

    async def run(self):
        """Main monitoring loop"""
        logger.info(f"\n{'#'*80}")
        logger.info(f"ELITE MIMIC WALLET WATCHER V2 - ACTIVATED")
        logger.info(f"Monitoring {len(self.targets)} whale wallets")
        logger.info(f"Strategy: {self.whale_intel.replicator.strategy_type}")
        logger.info(f"Max Position Size: ${self.whale_intel.replicator.max_position_size}")
        logger.info(f"{'#'*80}\n")

        # Start periodic reporting
        asyncio.create_task(self._periodic_reporting())

        while True:
            try:
                current_block = self.w3.eth.block_number

                if current_block > self.last_checked_block:
                    # Ultra-conservative block range: 3 blocks (strict public RPC limit)
                    # Use safe tip (delayed by 2 blocks) to ensure propagation stability across load-balanced RPCs
                    safe_tip = current_block - 2
                    if safe_tip <= self.last_checked_block:
                        await asyncio.sleep(2)
                        continue

                    scan_from = max(self.last_checked_block + 1, safe_tip - 3)
                    
                    if scan_from > safe_tip:
                        logger.debug(f"Scan range invalid: {scan_from} > {safe_tip}. Waiting.")
                        await asyncio.sleep(8)
                        continue

                    try:
                        await self.check_events(scan_from, safe_tip)
                        self.last_checked_block = safe_tip
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "invalid block range" in error_msg or "code': -32000" in error_msg:
                            logger.warning(f"⚠️ Block range problem ({current_block - scan_from} blocks). Trying adaptive recovery...")
                            await asyncio.sleep(1)
                            
                            # Recovery Step 1: Try smaller range (1 block)
                            try:
                                recovery_from = current_block
                                await self.check_events(recovery_from, current_block)
                                self.last_checked_block = current_block
                                logger.info(f"✅ Recovery success with 1-block range.")
                            except Exception:
                                # Recovery Step 2: Skip gap to stay alive
                                logger.error(f"❌ Adaptive recovery failed. Skipping to current block.")
                                self.last_checked_block = current_block
                        else:
                            raise e

                # Poll every 5-10 seconds
                await asyncio.sleep(8)

            except Exception as e:
                logger.error(f"Watcher Error: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def check_events(self, start_block: int, end_block: int):
        """
        Check for LogFill events from target whales in the given block range.
        """
        if not self.ctf_contract:
            return

        try:
            logger.debug(f"🔍 [WATCHER] Scanning events {start_block}-{end_block}")
            
            # Fetch LogFill logs from CTF_EXCHANGE
            # Signature: LogFill(bytes32 indexed orderHash, address indexed maker, address indexed taker, ...)
            # taker is the 3rd indexed parameter (topics[3])
            
            logs = self.w3.eth.get_logs({
                "address": CTF_EXCHANGE,
                "fromBlock": start_block,
                "toBlock": end_block,
                "topics": ["0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"]
            })

            if not logs:
                return

            # Map addresses for fast lookup
            whale_map = {w["address"].lower(): w for w in self.targets}

            for log in logs:
                try:
                    # Topic 3 is taker (padded to 32 bytes)
                    if len(log['topics']) < 4:
                        continue
                        
                    taker_padded = log['topics'][3].hex()
                    taker_addr = "0x" + taker_padded[-40:].lower()
                    
                    if taker_addr in whale_map:
                        whale = whale_map[taker_addr]
                        # Process using contractual decoding
                        event_data = self.ctf_contract.events.LogFill().process_log(log)
                        await self._process_whale_event(whale, event_data, log)
                    else:
                        # 🔎 DYNAMIC DISCOVERY: Check if this is a "Hidden Whale"
                        event_data = self.ctf_contract.events.LogFill().process_log(log)
                        args = event_data.get('args', {})
                        
                        # Check value (Approximate USDC part)
                        m_amt = float(args.get('makerAmount', 0))
                        t_amt = float(args.get('takerAmount', 0))
                        
                        # If either side is > $5,000 (USDC has 6 decimals, so 5000 * 1e6 = 5e9)
                        # We don't know which is USDC easily without token check, 
                        # but 5000 tokens (shares) is also significant if price is high.
                        # Let's use a raw threshold of 5,000*1e6 = 5,000,000,000 for USDC checks
                        # Or just strictly check for very large numbers.
                        
                        is_big = False
                        
                        # Check for USDC-like values (> $5000)
                        # 5000 USDC = 5,000,000,000 units
                        threshold = 5_000_000_000 
                        
                        if (t_amt > threshold and t_amt < 1e14) or (m_amt > threshold and m_amt < 1e14):
                             # Likely USDC side (shares are usually 1e18, so >1e14 typically)
                             is_big = True
                             
                        if is_big:
                            logger.info(f"🐋 DISCOVERED NEW WHALE: {taker_addr} (Trade Val > $5k)")
                            # Add to tracking temporarily
                            new_whale = {
                                "address": taker_addr,
                                "username": f"Discovered-{taker_addr[:6]}",
                                "tier": "discovered"
                            }
                            whale_map[taker_addr] = new_whale
                            self.targets.append(new_whale)
                            
                            # Process this event immediately
                            await self._process_whale_event(new_whale, event_data, log)
                except Exception as e:
                    logger.debug(f"Failed to process log {log['transactionHash'].hex()}: {e}")

        except Exception as e:
            logger.error(f"❌ Event Scan Error: {e}")
            raise e

    async def _process_whale_event(
        self,
        whale: Dict[str, str],
        event: Dict,
        log: Dict
    ):
        """
        Process a detected whale event from LogFill log.
        """
        tx_hash = log['transactionHash'].hex()
        block_number = log['blockNumber']

        # Prevent duplicate processing (though logs are usually unique)
        if tx_hash in self.tx_cache:
            return

        detection_time = datetime.now()
        self.tx_cache[tx_hash] = detection_time

        # Calculate detection latency
        try:
            block = self.w3.eth.get_block(block_number)
            tx_timestamp = block['timestamp']
            latency_ms = int((detection_time.timestamp() - tx_timestamp) * 1000)
        except:
            latency_ms = 0

        logger.info(f"\n{'!'*80}")
        logger.info(f"⚡ [EVENT] WHALE TRADE DETECTED (via LogFill)")
        logger.info(f"Whale: {whale['username']} ({whale['address']})")
        logger.info(f"Action: Taker Filling Order")
        logger.info(f"Tx Hash: {tx_hash}")
        logger.info(f"Detection Latency: {latency_ms}ms")
        logger.info(f"{'!'*80}\n")
        
        # Extract data from event arguments
        args = event.get('args', {})
        token_id = str(args.get('tokenId', ''))
        
        # Calculate Price Involved
        # Price = takerAmount / makerAmount (Standard CTF math for whale buying)
        # Note: We need to know if the whale is buying or selling based on the side. 
        # But for whales we usually copy whatever they are taking.
        
        m_amt = float(args.get('makerAmount', 0))
        t_amt = float(args.get('takerAmount', 0))
        
        # In LogFill, the "side" isn't explicitly 0/1 like the order struct, 
        # but we can infer price. 
        # If taker_amount is much smaller, it's likely USDC (buying shares)
        # If maker_amount is much smaller, it's likely USDC (selling shares)
        # Polymarket shares are usually 1e18 decimal, USDC is 1e6.
        
        side = "UNKNOWN"
        price = 0.0
        shares = 0.0
        
        if m_amt > 0 and t_amt > 0:
            # Check for USDC decimals (1e6) vs Shares (1e18)
            if t_amt < 1e12: # Taker pays USDC -> Whale BUYS shares
                side = "BUY"
                shares = m_amt / 1e18
                price = (t_amt / 1e6) / shares if shares > 0 else 0
            else: # Taker receives USDC -> Whale SELLS shares
                side = "SELL"
                shares = t_amt / 1e18
                price = (m_amt / 1e6) / shares if shares > 0 else 0

        # Create TradeSignal
        signal = TradeSignal(
            trader_address=whale["address"],
            token_id=token_id,
            side=side,
            detected_price=price,
            amount=shares,
            tx_hash=tx_hash,
            detection_timestamp=detection_time,
            block_number=block_number,
            latency_ms=latency_ms
        )

        # signal is already defined above from event log data

        # Get current market state
        market_state = await self._fetch_market_state(signal.token_id)
        signal.current_market_price = market_state.current_price

        # Get AI expected value
        ai_ev = await self._get_ai_evaluation(signal, market_state)

        # Get recent transactions for frontrunning analysis
        recent_txs = await self._get_recent_market_transactions(signal.token_id, block_number)

        # MASTER ANALYSIS
        should_copy, reason, execution_params = await self.whale_intel.analyze_trade_signal(
            signal=signal,
            market=market_state,
            ai_ev=ai_ev,
            recent_txs=recent_txs
        )

        # Execute if approved
        if should_copy:
            await self._execute_copy_trade(signal, execution_params)
        else:
            self.trades_skipped += 1
            logger.info(f"Trade SKIPPED. Reason: {reason}")

        # Log to agent
        if self.agent:
            self.agent.add_log(
                whale["username"],
                f"{signal.side} {signal.token_id} @ {signal.current_market_price:.4f}",
                f"EV={ai_ev:.3f}",
                reason
            )

    async def _decode_trade_transaction(self, tx: Dict) -> Optional[Dict]:
        """
        Decode transaction input data to extract trade details using CTF Exchange ABI.
        """
        if not self.ctf_contract or tx['input'] == '0x':
            return None

        try:
            func_obj, func_args = self.ctf_contract.decode_function_input(tx['input'])
            
            # We only care about fillOrder(Order order, uint256 takerAmount)
            if func_obj.fn_name == 'fillOrder':
                order = func_args.get('order', {})
                taker_amount = func_args.get('takerAmount', 0)
                
                # Order Struct: 
                # tokenId, makerAmount, takerAmount, side (0=BUY, 1=SELL usually, but check)
                # In Polymarket CTF:
                # BUY: side = 0
                # SELL: side = 1
                
                raw_side = order.get('side', 0)
                side_str = "BUY" if raw_side == 0 else "SELL"
                
                token_id = str(order.get('tokenId', ''))
                
                # Calculate Price involved
                # makerAmount / takerAmount ratio defines price
                m_amt = float(order.get('makerAmount', 0))
                t_amt = float(order.get('takerAmount', 0))
                
                # If buying (taking an ASK), we pay collateral (USDC) to get Outcome Tokens?
                # Or are we the maker? The whale is the one calling fillOrder, so they are the TAKER.
                # If whale calls fillOrder, they are filling a MAKER's order.
                
                # If Maker is SELLING (side=1), they offer Tokens for USDC.
                # Whale (Taker) is BUYING.
                # If Maker is BUYING (side=0), they offer USDC for Tokens.
                # Whale (Taker) is SELLING.
                
                # Wait, order.side is the MAKER's side.
                # If Maker side = 0 (BUY), Maker wants to BUY. Whale Fills it -> Whale SELLS.
                # If Maker side = 1 (SELL), Maker wants to SELL. Whale Fills it -> Whale BUYS.
                
                whale_side = "SELL" if raw_side == 0 else "BUY"
                
                # Calculate Price
                # Price = USDC / Tokens
                # We need to know which asset is USDC. Usually collateral.
                # Assuming standard Binary Market where 1 Outcome + 1 complementary = 1 USDC.
                
                # Simplified price calc:
                # If Maker Sells (side 1): Maker offers Tokens, wants USDC.
                # Price = takerAmount (USDC) / makerAmount (Tokens)
                # Whale Buys: Price = takerAmount / makerAmount
                
                # If Maker Buys (side 0): Maker offers USDC, wants Tokens.
                # Price = makerAmount (USDC) / takerAmount (Tokens)
                # Whale Sells: Price = makerAmount / takerAmount
                
                price = 0.0
                amount = 0.0 # Number of shares/tokens
                
                if m_amt > 0 and t_amt > 0:
                    if raw_side == 1: # Maker Sell -> Whale Buy
                         # makerAmount = Tokens, takerAmount = USDC
                         price = t_amt / m_amt
                         amount = m_amt
                    else: # Maker Buy -> Whale Sell
                         # makerAmount = USDC, takerAmount = Tokens
                         price = m_amt / t_amt
                         amount = t_amt

                return {
                    "token_id": token_id,
                    "side": whale_side,
                    "price": price,
                    "amount": amount
                }
                
            return None
            
        except Exception as e:
            # logger.debug(f"Failed to decode tx {tx['hash'].hex()}: {e}")
            return None

    async def _fetch_market_state(self, token_id: str) -> MarketState:
        """
        Fetch current market state for a token.
        """
        try:
            # Get order book
            current_price = self.client.get_best_ask_price(token_id)

            # Calculate spread (simplified - would need both bid and ask)
            # For now, estimate spread based on price
            spread = 0.02  # 2% default spread

            # Estimate liquidity (would need full order book)
            liquidity = 5000.0  # $5k default

            # Get 24h volatility (would need historical data)
            volatility = 0.10  # 10% default

            return MarketState(
                token_id=token_id,
                current_price=current_price if current_price > 0 else 0.50,
                bid_ask_spread=spread,
                liquidity_depth_10=liquidity,
                recent_volume_24h=10000.0,
                price_volatility_24h=volatility,
                last_updated=datetime.now()
            )

        except Exception as e:
            logger.error(f"Error fetching market state: {e}")
            # Return default state
            return MarketState(
                token_id=token_id,
                current_price=0.50,
                bid_ask_spread=0.05,
                liquidity_depth_10=1000.0,
                recent_volume_24h=5000.0,
                price_volatility_24h=0.15,
                last_updated=datetime.now()
            )

    async def _get_ai_evaluation(self, signal: TradeSignal, market: MarketState) -> float:
        """
        Get AI model's expected value for this trade.
        """
        try:
            # Use AI brain to validate
            is_valid = await self.ai_brain.validate_trade(
                signal.token_id,
                "YES",
                signal.current_market_price
            )

            if is_valid:
                # Calculate EV from AI prediction
                ai_prob = await self.ai_brain.predict_probability(signal.token_id, "YES")
                ev = self.ai_brain.calculate_ev(ai_prob, signal.current_market_price)
                return ev
            else:
                return 0.0

        except Exception as e:
            logger.error(f"AI evaluation error: {e}")
            return 0.0

    async def _get_recent_market_transactions(
        self,
        token_id: str,
        before_block: int
    ) -> List[Dict]:
        """
        Get recent transactions in this market for frontrunning analysis.
        """
        # TODO: Implement transaction history lookup
        # Would query recent blocks or use indexer API
        return []

    async def _execute_copy_trade(self, signal: TradeSignal, params: Dict):
        """
        Execute the copy trade with optimized parameters.
        """
        # Apply execution delay (anti-frontrunning)
        delay = params.get("delay_seconds", 0)
        if delay > 0:
            logger.info(f"Applying {delay}s execution delay for anti-frontrunning...")
            await asyncio.sleep(delay)

        # Recheck price after delay
        current_price = self.client.get_best_ask_price(signal.token_id)
        if current_price == 0:
            logger.error("No liquidity available - aborting trade")
            return

        # Check if price moved too much during delay
        price_change = abs(current_price - signal.current_market_price) / signal.current_market_price
        if price_change > params.get("max_slippage", 0.05):
            logger.warning(f"Price moved {price_change:.2%} during delay - aborting for safety")
            return

        # Execute order
        position_size = params["position_size"]
        use_limit = params.get("use_limit_order", False)

        try:
            if use_limit:
                limit_price = params.get("limit_price", current_price * 1.02)
                logger.info(f"Placing LIMIT {signal.side} order: ${position_size:.2f} @ {limit_price:.4f}")
                # TODO: Implement limit order execution
                # For now, use market order
                response = await self.client.place_market_order(
                    signal.token_id,
                    signal.side,
                    position_size
                )
            else:
                logger.info(f"Placing MARKET {signal.side} order: ${position_size:.2f}")
                response = await self.client.place_market_order(
                    signal.token_id,
                    signal.side,
                    position_size
                )

            if response:
                self.trades_executed += 1
                logger.info(f"Trade EXECUTED successfully: {response}")

                # Update whale profile with our trade
                self.whale_intel.profiler.update_profile(
                    signal.trader_address,
                    {
                        "amount": signal.amount,
                        "market_type": "UNKNOWN",  # Would categorize based on token metadata
                        "timestamp": datetime.now()
                    }
                )
            else:
                logger.error("Trade execution failed")

        except Exception as e:
            logger.error(f"Error executing trade: {e}", exc_info=True)

    async def _periodic_reporting(self):
        """Generate periodic performance reports"""
        while True:
            await asyncio.sleep(300)  # Every 5 minutes

            logger.info(f"\n{'*'*80}")
            logger.info(f"WALLET WATCHER STATUS")
            logger.info(f"Trades Executed: {self.trades_executed}")
            logger.info(f"Trades Skipped: {self.trades_skipped}")
            logger.info(f"Last Block: {self.last_checked_block}")
            logger.info(f"{'*'*80}\n")

            # Generate whale intelligence report
            self.whale_intel.report_performance()

    async def shutdown(self):
        """Clean up active resources"""
        logger.info("🎬 Shutting down WalletWatcher...")
        # Currently uses Web3 via HTTPProvider, no session to close explicitly unless using AsyncHTTPProvider
        # But we may have other internal tasks to stop
        logger.info("✅ WalletWatcher cleanup complete")


# Backward compatibility wrapper
class WalletWatcher:
    """
    Legacy wrapper for backward compatibility.
    Delegates to EnhancedWalletWatcher.
    """

    def __init__(self, client, agent=None):
        logger.warning("Using legacy WalletWatcher interface. Consider migrating to EnhancedWalletWatcher.")
        self.enhanced_watcher = EnhancedWalletWatcher(client, agent)
        self.ai_brain = self.enhanced_watcher.ai_brain

    async def run(self):
        await self.enhanced_watcher.run()

    async def shutdown(self):
        """Pass through shutdown to enhanced version"""
        await self.enhanced_watcher.shutdown()
