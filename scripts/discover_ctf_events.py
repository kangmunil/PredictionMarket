import os
import json
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

def discover_events():
    print(f"Connecting to {RPC_URL}...")
    if not w3.is_connected():
        print("Failed to connect")
        return

    current_block = w3.eth.block_number
    print(f"Current Block: {current_block}")
    
    # Check last 100 blocks for ANY event to CTF_EXCHANGE
    print(f"Scanning last 100 blocks for events from {CTF_EXCHANGE}...")
    logs = w3.eth.get_logs({
        "address": CTF_EXCHANGE,
        "fromBlock": current_block - 100,
        "toBlock": current_block
    })
    
    print(f"Found {len(logs)} logs")
    
    topic_counts = {}
    for log in logs:
        topic0 = log['topics'][0].hex()
        topic_counts[topic0] = topic_counts.get(topic0, 0) + 1
        
    for topic, count in topic_counts.items():
        print(f"Topic0: {topic} (Count: {count})")
        # Try to find a log with many topics (likely LogFill)
        sample_log = next(l for l in logs if l['topics'][0].hex() == topic)
        print(f"  Number of topics: {len(sample_log['topics'])}")

if __name__ == "__main__":
    discover_events()
