# slave_bridge.py
import asyncio
import websockets
import requests
import json

BACKEND_WS = "ws://127.0.0.1:8000/ws/slave"
SLAVE_EA_LOCAL = "http://127.0.0.1:5000"  # MT5 listens here

async def listen():
    async with websockets.connect(BACKEND_WS) as ws:
        print("Connected to backend WebSocket")
        while True:
            msg = await ws.recv()
            print(f"Received trade: {msg}")
            # Forward to local Slave EA via HTTP POST
            try:
                requests.post(SLAVE_EA_LOCAL, json={"trade": msg}, timeout=1)
            except Exception as e:
                print("Error sending to Slave EA:", e)

asyncio.get_event_loop().run_until_complete(listen())
