# app.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel
from typing import Literal, List
from datetime import datetime
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi import status
import json

app = FastAPI(title="CopyTrade Backend")

class PositionEvent(BaseModel):
    ticket: int
    symbol: str
    volume: float
    sl: float
    tp: float
    type: int
    magic: int
    comment: str
    action: Literal["OPEN","MODIFY","CLOSE"]

# Simple in-memory WebSocket hub (optional)
class Hub:
    def __init__(self):
        self.clients: List[WebSocket] = []
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.append(ws)
    def remove(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)
    async def broadcast(self, message: str):
        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for d in dead: self.remove(d)

hub = Hub()

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Log the raw body for debugging
    try:
        body = await request.body()
        print("[DEBUG] Raw request body:", body.decode())
    except Exception as e:
        print("[DEBUG] Could not read body:", e)
    print("[DEBUG] Validation error:", exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": body.decode() if 'body' in locals() else None},
    )

@app.post("/events")
async def receive_event(evt: PositionEvent, request: Request):
    raw_body = await request.body()
    print("[DEBUG] Raw JSON from Capture EA:", raw_body.decode(errors='replace'))
    print("[DEBUG] Parsed event:", evt)
    return {"ok": True}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            # You can receive pings/commands from clients if needed
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.remove(ws)
