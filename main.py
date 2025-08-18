# backend.py
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import asyncio
import json
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import status
from pydantic import BaseModel
from datetime import datetime, timezone
from pydantic import Field

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_slaves: List[WebSocket] = []

class PositionEventIn(BaseModel):
    ticket: int
    symbol: str
    volume: float
    sl: float
    tp: float
    type: int
    magic: int
    comment: str
    action: str  # or Literal["OPEN", "MODIFY", "CLOSE"]

class PositionEventOut(PositionEventIn):
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

recent_events: List[PositionEventOut] = []

class Hub:
    def __init__(self):
        self._clients = set()
    async def broadcast_json(self, data):
        # Placeholder: In production, send data to all connected WebSocket clients
        print("[DEBUG] Broadcasting to clients:", data)

hub = Hub()

@app.websocket("/ws/slave")
async def slave_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_slaves.append(websocket)
    print("✅ Slave connected. Total:", len(connected_slaves))
    try:
        while True:
            data = await websocket.receive_json()
            print(f"ACK from slave: {data}")
    except WebSocketDisconnect:
        connected_slaves.remove(websocket)
        print("❌ Slave disconnected. Remaining:", len(connected_slaves))

async def broadcast_trade(trade: dict):
    disconnected = []
    for slave in connected_slaves:
        try:
            await slave.send_json(trade)
        except:
            disconnected.append(slave)
    for s in disconnected:
        connected_slaves.remove(s)

@app.post("/events")
async def receive_event(evt: PositionEventIn, request: Request):
    try:
        raw = (await request.body()).decode(errors="replace")
        print("[DEBUG] /events raw request body:", raw)
    except Exception as e:
        print("[DEBUG] Could not read body in /events:", e)
    out = PositionEventOut(**evt.model_dump())
    recent_events.append(out)
    # Log compact line
    print(
        f"[{out.ts.isoformat()}] {out.action} {out.symbol} "
        f"lot={out.volume} ticket={out.ticket} magic={out.magic} comment='{out.comment}'"
    )
    # Fan out to live clients
    await hub.broadcast_json(out.model_dump())
    return {"ok": True}

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    raw = None
    try:
        raw = (await request.body()).decode(errors="replace")
        print("[DEBUG] Raw request body:", raw)
    except Exception as e:
        print("[DEBUG] Could not read body:", e)
    print("[DEBUG] Validation error details:", exc.errors())
    print("[DEBUG] Validation error body:", exc.body)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": raw},
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
