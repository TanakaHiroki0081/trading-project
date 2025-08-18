"""
ws_bridge.py
Bridge: Backend WebSocket -> local HTTP long-poll
Run: pip install websockets aiohttp
Then: python ws_bridge.py
"""

import asyncio
import json
from aiohttp import web, ClientSession, ClientConnectorError
import websockets

# Config
BACKEND_WS = "ws://127.0.0.1:8000/ws/slave"   # backend websocket endpoint
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 9000
LONGPOLL_TIMEOUT = 30  # seconds: how long GET will wait for an event

# In-memory single-producer queue for events
event_queue = asyncio.Queue()

async def backend_ws_loop():
    """
    Connects to backend WS and pushes incoming messages into event_queue.
    Reconnects on failure with exponential backoff.
    """
    backoff = 1
    while True:
        try:
            print("Connecting to backend WS:", BACKEND_WS)
            async with websockets.connect(BACKEND_WS) as ws:
                print("Connected to backend WS")
                backoff = 1
                async for message in ws:
                    # message should be JSON string from your backend
                    try:
                        data = json.loads(message)
                    except Exception:
                        # try to pass through raw string
                        data = {"raw": message}
                    print("[BRIDGE RECEIVED]", data)  # <-- Print to main screen
                    # Put the event into the queue (non-blocking if queue is large)
                    await event_queue.put(data)
        except (ConnectionRefusedError, ClientConnectorError, OSError) as e:
            print("WS connection failed:", e)
        except Exception as e:
            print("WS receive loop error:", e)

        print(f"Reconnecting in {backoff}s...")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


async def handle_get_events(request):
    """
    Long-poll GET handler.
    If there is an event in the queue, returns immediately.
    Otherwise waits up to LONGPOLL_TIMEOUT seconds for an event.
    """
    try:
        # Try immediate get first (non-blocking)
        event = None
        try:
            event = event_queue.get_nowait()
        except asyncio.QueueEmpty:
            # wait for up to LONGPOLL_TIMEOUT
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=LONGPOLL_TIMEOUT)
            except asyncio.TimeoutError:
                return web.json_response({"ok": True, "events": []})  # no new events
        # Wrap as list for future-proofing
        return web.json_response({"ok": True, "events": [event]})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_health(request):
    return web.json_response({"ok": True, "status": "bridge up"})


async def start_servers():
    # Start aiohttp server
    app = web.Application()
    app.add_routes([
        web.get('/events', handle_get_events),   # Slave EA will poll this
        web.get('/health', handle_health),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()
    print(f"HTTP bridge listening at http://{HTTP_HOST}:{HTTP_PORT}")

    # Start the WS client loop
    await backend_ws_loop()

if __name__ == "__main__":
    try:
        asyncio.run(start_servers())
    except KeyboardInterrupt:
        print("Bridge stopped by user")
