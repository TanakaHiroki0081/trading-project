# slave_bridge.py
import asyncio
import websockets
import aiohttp
import json
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BACKEND_WS = "ws://127.0.0.1:8000/ws/slave"
SLAVE_EA_LOCAL = "http://127.0.0.1:5000"  # MT5 listens here

async def listen():
    async with aiohttp.ClientSession() as session:
        backoff = 1
        while True:
            try:
                async with websockets.connect(BACKEND_WS) as ws:
                    logger.info("Connected to backend WebSocket")
                    backoff = 1  # Reset backoff on successful connection
                    
                    while True:
                        msg = await ws.recv()
                        logger.info(f"Received trade: {msg}")
                        
                        # Forward to local Slave EA via HTTP POST (async)
                        try:
                            async with session.post(
                                SLAVE_EA_LOCAL,
                                json={"trade": msg},
                                timeout=aiohttp.ClientTimeout(total=1)
                            ) as response:
                                if response.status == 200:
                                    logger.debug(f"Successfully forwarded to Slave EA")
                                else:
                                    logger.warning(f"Slave EA returned status {response.status}")
                        except asyncio.TimeoutError:
                            logger.warning("Timeout sending to Slave EA")
                        except aiohttp.ClientError as e:
                            logger.error(f"Error sending to Slave EA: {e}")
                        except Exception as e:
                            logger.error(f"Unexpected error forwarding to Slave EA: {e}", exc_info=True)
                            
            except (ConnectionRefusedError, OSError) as e:
                logger.warning(f"Connection failed: {e}. Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)  # Exponential backoff, max 30s
            except Exception as e:
                logger.error(f"Unexpected error in listen loop: {e}", exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

if __name__ == "__main__":
    try:
        asyncio.run(listen())
    except KeyboardInterrupt:
        logger.info("Slave bridge stopped by user")
