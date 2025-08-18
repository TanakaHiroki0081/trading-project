from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List
from models import PositionData
import asyncio
import json

app = FastAPI(title="Copy Trading Backend")

# === Slave Connection Management ===
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"Slave connected. Total slaves: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print(f"Slave disconnected. Total slaves: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_text(message)
            except:
                disconnected.append(conn)
        for dc in disconnected:
            self.disconnect(dc)

manager = ConnectionManager()

# === WebSocket endpoint for Slaves ===
@app.websocket("/ws/slave")
async def websocket_slave(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Optionally receive messages from slaves
            msg = await websocket.receive_text()
            print(f"Received from slave: {msg}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# === HTTP endpoint for Master EA ===
@app.post("/events")
async def receive_trade(trade: PositionData):
    trade_json = trade.json()
    print(f"Received trade from Master EA: {trade_json}")
    # Broadcast to all connected slaves
    await manager.broadcast(trade_json)
    return {"status": "success", "message": "Trade broadcasted to slaves"}
