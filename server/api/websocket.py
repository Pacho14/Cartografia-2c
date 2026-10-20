"""
Spatial Rhythm Observer — WebSocket Handler
Handles real-time frame streaming, detection results, and session lifecycle.
"""

import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from cv.frame_processor import FrameProcessor

router = APIRouter()

# Global frame processor
processor = FrameProcessor()


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WS] Client disconnected. Total: {len(self.active_connections)}")

    async def send_json(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            self.disconnect(websocket)


manager = ConnectionManager()


@router.websocket("/ws/vision")
async def vision_websocket(websocket: WebSocket):
    """
    Main vision processing WebSocket endpoint.
    
    Protocol:
    - Client sends: binary JPEG frame bytes
    - Server sends: JSON string with detection results and session status
    - Client sends JSON control messages:
      {"action": "session_start", "session_id": "...", "name": "..."}
      {"action": "session_pause"}
      {"action": "session_resume"}
      {"action": "session_stop"}
      {"action": "reset"}
      {"action": "config", "confidence": 0.3}
    """
    await manager.connect(websocket)

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))

            if "bytes" in message and message["bytes"]:
                # Binary data = video frame
                frame_bytes = message["bytes"]

                # Process frame in a thread to keep the asyncio event loop responsive
                result = await asyncio.to_thread(
                    processor.process_frame, frame_bytes
                )

                await manager.send_json(websocket, result)

            elif "text" in message and message["text"]:
                try:
                    control = json.loads(message["text"])
                    action = control.get("action", "")

                    if action == "session_start":
                        session_id = control.get("session_id") or f"session_{int(time.time())}"
                        name = control.get("name", "Observación Espacial")
                        weather = control.get("weather_condition", "unspecified")
                        time_slot = control.get("time_slot", "unspecified")
                        noise = control.get("ambient_noise_level", "moderate")
                        session_meta = processor.start_session(
                            session_id,
                            name,
                            weather_condition=weather,
                            time_slot=time_slot,
                            ambient_noise_level=noise
                        )
                        await manager.send_json(websocket, {
                            "control": "session_started",
                            "session": session_meta
                        })

                    elif action == "session_pause":
                        processor.pause_session()
                        await manager.send_json(websocket, {
                            "control": "session_paused"
                        })

                    elif action == "session_resume":
                        processor.resume_session()
                        await manager.send_json(websocket, {
                            "control": "session_resumed"
                        })

                    elif action == "session_stop":
                        summary = processor.stop_session()
                        await manager.send_json(websocket, {
                            "control": "session_stopped",
                            "summary": summary
                        })

                    elif action == "reset":
                        processor.reset_tracking()
                        await manager.send_json(websocket, {
                            "control": "reset_ok",
                            "message": "Tracking state reset"
                        })

                    elif action == "config":
                        if "confidence" in control:
                            processor.confidence = float(control["confidence"])
                        await manager.send_json(websocket, {
                            "control": "config_ok",
                            "message": "Configuration updated"
                        })

                    elif action == "update_zones":
                        zones = control.get("zones", [])
                        processor.set_zones(zones)
                        await manager.send_json(websocket, {
                            "control": "zones_updated",
                            "count": len(processor.zones)
                        })

                    elif action == "get_zones":
                        await manager.send_json(websocket, {
                            "control": "zones_list",
                            "zones": processor.zones
                        })

                    elif action == "ping":
                        await manager.send_json(websocket, {
                            "control": "pong",
                            "timestamp": time.time()
                        })

                except json.JSONDecodeError:
                    pass

    except WebSocketDisconnect:
        processor.flush_points_buffer()
        manager.disconnect(websocket)
    except Exception as e:
        print(f"[WS] Error: {e}")
        processor.flush_points_buffer()
        manager.disconnect(websocket)
