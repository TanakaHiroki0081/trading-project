# main.py
from collections import deque
from datetime import datetime, timezone
from typing import Deque, List, Literal, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
import asyncio
import uvicorn
import json


# ----------------------------
# Models
# ----------------------------
Action = Literal["OPEN", "MODIFY", "CLOSE"]

class PositionEventIn(BaseModel):
    ticket: int
    symbol: str
    volume: float
    sl: float
    tp: float
    type: int               # MT5: 0=BUY, 1=SELL
    magic: int
    comment: str
    action: Action

class PositionEventOut(PositionEventIn):
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ----------------------------
# App & Middleware
# ----------------------------
app = FastAPI(title="CopyTrade Backend", version="1.0")

# Allow your dashboard to fetch /recent and connect to /ws from a browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# In-memory store & hub
# ----------------------------
RECENT_MAX = 2000
recent_events: Deque[PositionEventOut] = deque(maxlen=RECENT_MAX)

class Hub:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: WebSocket):
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast_json(self, data: dict):
        # Send to all; drop dead connections
        message = json.dumps(data, default=str)
        dead: List[WebSocket] = []
        async with self._lock:
            for ws in list(self._clients):
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.append(ws)
            for d in dead:
                self._clients.discard(d)

hub = Hub()

# ----------------------------
# Error logging for bad JSON
# ----------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    raw = None
    try:
        raw = (await request.body()).decode(errors="replace")
        print("[DEBUG] Raw request body:", raw)
    except Exception as e:
        print("[DEBUG] Could not read body:", e)
    print("[DEBUG] Validation error:", exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": raw},
    )

# ----------------------------
# REST: Receive events from EA
# ----------------------------
@app.post("/events")
async def receive_event(evt: PositionEventIn, request: Request):
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

# ----------------------------
# REST: Fetch recent events (for initial page load)
# ----------------------------
@app.get("/recent")
async def get_recent(limit: Optional[int] = 500):
    lim = max(1, min(limit or 500, RECENT_MAX))
    data = list(recent_events)[-lim:]
    # serialize datetimes
    return JSONResponse(
        content=[{**e.model_dump(), "ts": e.ts.isoformat()} for e in data]
    )

# ----------------------------
# WebSocket: Live stream
# ----------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.connect(ws)
    try:
        # simple read loop to keep connection alive; clients can ignore sending
        while True:
            # If you want to support client pings/commands, handle here
            await ws.receive_text()
    except WebSocketDisconnect:
        await hub.remove(ws)
    except Exception:
        await hub.remove(ws)

# ----------------------------
# Health
# ----------------------------
@app.get("/health")
def health():
    return {"status": "ok", "clients": len(getattr(hub, "_clients", [])), "events_buffered": len(recent_events)}

# ----------------------------
# Run
# ----------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
