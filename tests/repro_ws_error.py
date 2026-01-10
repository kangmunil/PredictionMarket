import asyncio
import websockets
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ReproWS")

async def test_ws():
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    payload = {
        "assets_ids": ["105267568073659068217311993901927962476298440625043565106676088842803600775810"],
        "type": "market"
    }
    
    logger.info(f"Connecting to {uri}...")
    async with websockets.connect(uri) as websocket:
        logger.info("Connected!")
        
        # Send subscription
        msg = json.dumps(payload)
        logger.info(f"Sending: {msg}")
        await websocket.send(msg)
        
        # Listen for messages
        try:
            while True:
                response = await asyncio.wait_for(websocket.recv(), timeout=10)
                logger.info(f"Received: {response}")
                
        except asyncio.TimeoutError:
            logger.info("Timeout waiting for response")
        except Exception as e:
            logger.error(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
