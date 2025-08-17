# backend.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import asyncio

app = FastAPI()

# Allow MT5 terminals to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track connected slaves
connected_slaves: List[WebSocket] = []

@app.websocket("/ws/slave")
async def slave_endpoint(websocket: WebSocket):
    """Each slave EA connects here via WebSocket"""
    await websocket.accept()
    connected_slaves.append(websocket)
    print("✅ Slave connected. Total:", len(connected_slaves))
    try:
        while True:
            data = await websocket.receive_json()
            print(f"ACK from slave: {data}")  # log acknowledgements
    except WebSocketDisconnect:
        connected_slaves.remove(websocket)
        print("❌ Slave disconnected. Remaining:", len(connected_slaves))

async def broadcast_trade(trade: dict):
    """Send trade JSON to all connected slaves"""
    disconnected = []
    for slave in connected_slaves:
        try:
            await slave.send_json(trade)
        except:
            disconnected.append(slave)
    # Remove broken connections
    for s in disconnected:
        connected_slaves.remove(s)

@app.post("/events")
async def receive_trade(trade: dict):
    """Receive JSON trade from Master EA"""
    print(f"📥 Received trade: {trade}")
    await broadcast_trade(trade)
    return {"status": "broadcasted", "slaves": len(connected_slaves)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
