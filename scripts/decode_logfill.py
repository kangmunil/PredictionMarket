import os
import json
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
LOG_FILL_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

def decode_sample():
    print(f"Connecting to {RPC_URL}...")
    current_block = w3.eth.block_number
    
    logs = w3.eth.get_logs({
        "address": CTF_EXCHANGE,
        "fromBlock": current_block - 50,
        "toBlock": current_block,
        "topics": [LOG_FILL_TOPIC]
    })
    
    if not logs:
        print("No LogFill found in last 50 blocks")
        return

    log = logs[0]
    print(f"Decoding Log from Tx: {log['transactionHash'].hex()}")
    
    # Topics: [Sig, orderHash, maker, taker]
    maker = "0x" + log['topics'][2].hex()[-40:]
    taker = "0x" + log['topics'][3].hex()[-40:]
    
    # Data: [tokenId (32), makerAmount (32), takerAmount (32)]
    data = log['data'].hex()
    if data.startswith("0x"): data = data[2:]
    
    token_id = int(data[0:64], 16)
    maker_amount = int(data[64:128], 16)
    taker_amount = int(data[128:192], 16)
    
    print(f"Maker: {maker}")
    print(f"Taker: {taker}")
    print(f"TokenID: {token_id}")
    print(f"MakerAmount: {maker_amount}")
    print(f"TakerAmount: {taker_amount}")

if __name__ == "__main__":
    decode_sample()
