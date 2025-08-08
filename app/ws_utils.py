# app/ws_utils.py

import logging
import asyncio
from typing import Dict
from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[WebSocket, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = None

    def disconnect(self, websocket: WebSocket):
        task = self.active_connections.pop(websocket, None)
        if task and not task.done():
            task.cancel()
            logger.info("Animation task cancelled due to WebSocket disconnect.")

    async def send_json(self, websocket: WebSocket, data: dict):
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_json(data)
            except RuntimeError as e:
                logger.info(f"Failed to send to WebSocket (likely closed): {e}")
            except Exception as e:
                logger.warning(f"Could not send to websocket despite CONNECTED state: {e}")
        else:
            logger.info(f"WebSocket not connected (state: {websocket.client_state}); skipping send.")

    def assign_task(self, websocket: WebSocket, task: asyncio.Task):
        self.active_connections[websocket] = task

manager = ConnectionManager()

async def send_progress(websocket: WebSocket, stage: str, message: str, status: str = "progress", **kwargs):
    """Helper to send a progress update over a WebSocket."""
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_json({
            "status": status,
            "stage": stage,
            "message": message,
            **kwargs
        })

async def send_error(websocket: WebSocket, message: str):
    """Helper to send an error message over a WebSocket."""
    await send_progress(websocket, "Error", message, status="error")
