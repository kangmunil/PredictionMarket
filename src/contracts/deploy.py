import json
import os
import logging
from web3 import Web3
from solcx import compile_standard, install_solc
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Deployer")

load_dotenv()

# Configuration
CHAIN_ID = 137  # Polygon Mainnet (Use 80002 for Amoy)
RPC_URL = "https://polygon-rpc.com"
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
MY_ADDRESS = os.getenv("FUNDER_ADDRESS")

# Addresses (Polygon Mainnet)
USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

def deploy():
    if not PRIVATE_KEY:
        logger.error("Missing PRIVATE_KEY in .env")
        return

    logger.info("🔧 Installing Solidity Compiler...")
    install_solc("0.8.18")

    # 1. Compile
    logger.info("Compiling ArbExecutor.sol...")
    with open("src/contracts/ArbExecutor.sol", "r") as f:
        source = f.read()

    compiled_sol = compile_standard(
        {
            "language": "Solidity",
            "sources": {"ArbExecutor.sol": {"content": source}},
            "settings": {
                "outputSelection": {
                    "*": {"*": ["abi", "metadata", "evm.bytecode", "evm.sourceMap"]}
                }
            },
        },
        solc_version="0.8.18",
    )

    bytecode = compiled_sol["contracts"]["ArbExecutor.sol"]["ArbExecutor"]["evm"]["bytecode"]["object"]
    abi = json.loads(compiled_sol["contracts"]["ArbExecutor.sol"]["ArbExecutor"]["metadata"])["output"]["abi"]

    # 2. Connect to Blockchain
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        logger.error("Failed to connect to RPC")
        return

    logger.info(f"Connected to {RPC_URL}. Deploying from {MY_ADDRESS}...")

    # 3. Build Transaction
    ArbExecutor = w3.eth.contract(abi=abi, bytecode=bytecode)
    
    # Get nonce
    nonce = w3.eth.get_transaction_count(MY_ADDRESS)

    # Build constructor transaction
    transaction = ArbExecutor.constructor(USDC_ADDRESS, CTF_EXCHANGE).build_transaction({
        "chainId": CHAIN_ID,
        "from": MY_ADDRESS,
        "nonce": nonce,
        "gasPrice": w3.eth.gas_price
    })

    # 4. Sign & Send
    signed_txn = w3.eth.account.sign_transaction(transaction, private_key=PRIVATE_KEY)
    logger.info("Sending transaction...")
    tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
    
    logger.info(f"🚀 Transaction Sent: {tx_hash.hex()}")
    logger.info("Waiting for receipt...")
    
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    logger.info(f"✅ Contract Deployed at: {tx_receipt.contractAddress}")
    
    # Save ABI and Address
    with open("src/contracts/ArbExecutor_ABI.json", "w") as f:
        json.dump(abi, f)
    
    with open("src/contracts/address.txt", "w") as f:
        f.write(tx_receipt.contractAddress)

if __name__ == "__main__":
    deploy()
