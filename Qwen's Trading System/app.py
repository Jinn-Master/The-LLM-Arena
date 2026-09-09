from fastapi import FastAPI, WebSocket
import json
import asyncio
from typing import Dict

app = FastAPI(title="Qwen Prop Firm Dashboard")

# In-memory state (synced from Go via Redis/ZMQ in production)
system_state = {
    "trading_enabled": False,
    "current_equity": 100000.0,
    "daily_dd_pct": 0.0,
    "max_dd_pct": 0.0,
    "consecutive_losses": 0,
    "pending_signals": []
}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Push real-time state to frontend
            await websocket.send_text(json.dumps(system_state))
            await asyncio.sleep(1.0) # 1-second heartbeat
    except Exception:
        pass

@app.post("/api/approve")
async def approve_signal(signal_id: str):
    """Human-in-the-loop 1-click approval"""
    # In production: This triggers the Go Risk Engine to re-evaluate and emit DECISION
    system_state["trading_enabled"] = True
    return {"status": "approved", "signal_id": signal_id}

@app.post("/api/kill_switch")
async def trigger_kill_switch():
    """Emergency manual override"""
    system_state["trading_enabled"] = False
    # In production: Send ZMQ message to Go to Disable("MANUAL_KILL") and flatten MT5
    return {"status": "KILL_SWITCH_ACTIVATED"}