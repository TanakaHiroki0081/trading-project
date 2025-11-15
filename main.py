from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from typing import List, Optional
from models import PositionData
import asyncio
import json
import logging
from datetime import datetime
from collections import deque

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Copy Trading Backend")

# Store recent events (in-memory, consider database for production)
recent_events = deque(maxlen=100)  # Keep last 100 events

# === Slave Connection Management ===
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Slave connected. Total slaves: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Slave disconnected. Total slaves: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_text(message)
            except (WebSocketDisconnect, ConnectionError, RuntimeError) as e:
                logger.warning(f"Error sending to slave: {e}")
                disconnected.append(conn)
            except Exception as e:
                logger.error(f"Unexpected error broadcasting to slave: {e}", exc_info=True)
                disconnected.append(conn)
        
        # Remove disconnected connections
        for dc in disconnected:
            self.disconnect(dc)

manager = ConnectionManager()

# === Health Check Endpoint ===
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "active_slaves": len(manager.active_connections)
    }

# === Recent Events Endpoint ===
@app.get("/recent")
async def get_recent_events(limit: int = 10):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")
    
    events_list = list(recent_events)
    return events_list[-limit:] if len(events_list) > limit else events_list

# === WebSocket endpoint for Slaves ===
@app.websocket("/ws/slave")
async def websocket_slave(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Optionally receive messages from slaves
            msg = await websocket.receive_text()
            logger.debug(f"Received from slave: {msg}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Error in websocket_slave: {e}", exc_info=True)
        manager.disconnect(websocket)

# === HTTP endpoint for Master EA ===
@app.post("/events")
async def receive_trade(trade: PositionData):
    try:
        # Get trade as dict for storage
        trade_dict = trade.dict()
        trade_dict["timestamp"] = datetime.utcnow().isoformat()
        
        # Get JSON string for broadcasting (without timestamp for compatibility)
        trade_json = trade.json()
        
        logger.info(f"Received trade from Master EA: {trade_json}")
        
        # Store in recent events (with timestamp)
        recent_events.append(trade_dict)
        
        # Broadcast to all connected slaves (original format without timestamp)
        await manager.broadcast(trade_json)
        
        return {"status": "success", "message": "Trade broadcasted to slaves"}
    except Exception as e:
        logger.error(f"Error processing trade event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing trade: {str(e)}")
