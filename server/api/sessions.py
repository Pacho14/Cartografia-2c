"""
Spatial Rhythm Observer — Sessions REST API
Endpoints to query, create, finalize, and delete observation sessions.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import time

from storage.db import db
from config import VIDEOS_DIR

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class SessionCreateRequest(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = "Observación Espacial"
    started_at: Optional[float] = None
    weather_condition: Optional[str] = "unspecified" # 'soleado', 'nublado', 'lluvioso', 'templado'
    time_slot: Optional[str] = "unspecified"        # 'manana', 'mediodia', 'tarde', 'noche'
    ambient_noise_level: Optional[str] = "moderate"  # 'bajo', 'moderado', 'alto'


class SessionCompleteRequest(BaseModel):
    ended_at: Optional[float] = None
    duration_seconds: float = 0
    total_persons: int = 0
    max_concurrent: int = 0
    total_frames: int = 0
    avg_fps: float = 0


@router.get("")
async def list_sessions(limit: int = 50):
    """List all recorded sessions."""
    sessions = db.list_sessions(limit=limit)
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get session details along with person summaries."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    
    summaries = db.get_session_person_summaries(session_id)
    return {
        "session": session,
        "person_summaries": summaries
    }


@router.get("/{session_id}/points")
async def get_session_points(
    session_id: str,
    person_id: Optional[int] = None,
    limit: int = 10000
):
    """Retrieve recorded spatial points for a session."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    
    points = db.get_session_points(session_id, person_id=person_id, limit=limit)
    return {
        "session_id": session_id,
        "count": len(points),
        "points": points
    }


@router.post("")
async def create_session(payload: SessionCreateRequest):
    """Create a new session record."""
    session_id = payload.id or f"session_{int(time.time())}"
    started_at = payload.started_at or time.time()
    session = db.create_session(
        session_id=session_id,
        name=payload.name,
        started_at=started_at,
        weather_condition=payload.weather_condition or "unspecified",
        time_slot=payload.time_slot or "unspecified",
        ambient_noise_level=payload.ambient_noise_level or "moderate"
    )
    return {"status": "created", "session": session}


@router.post("/{session_id}/complete")
async def complete_session(session_id: str, payload: SessionCompleteRequest):
    """Finalize an observation session."""
    session = db.complete_session(
        session_id=session_id,
        ended_at=payload.ended_at or time.time(),
        duration_seconds=payload.duration_seconds,
        total_persons=payload.total_persons,
        max_concurrent=payload.max_concurrent,
        total_frames=payload.total_frames,
        avg_fps=payload.avg_fps
    )
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return {"status": "completed", "session": session}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and all its recorded points."""
    deleted = db.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return {"status": "deleted", "session_id": session_id}


@router.post("/{session_id}/video")
async def upload_session_video(session_id: str, request: Request):
    """Upload and save the video recording for a session."""
    session = db.get_session(session_id)
    if not session:
        # Auto-create session record if WebSocket control was queued or delayed
        db.create_session(session_id, "Observación Espacial", time.time())

    form = await request.form()
    file_obj = form.get("video") or form.get("file")
    if not file_obj or not hasattr(file_obj, "read"):
        raise HTTPException(status_code=400, detail="Archivo de video no encontrado en el formulario")

    # Detect proper extension: iOS Safari sends mp4, Chrome/Firefox send webm
    filename_attr = getattr(file_obj, "filename", "") or ""
    content_type_attr = getattr(file_obj, "content_type", "") or ""
    is_mp4 = "mp4" in filename_attr.lower() or "mp4" in content_type_attr.lower()
    ext = "mp4" if is_mp4 else "webm"

    video_filename = f"{session_id}.{ext}"
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    video_path = VIDEOS_DIR / video_filename

    content = await file_obj.read()
    with open(video_path, "wb") as f:
        f.write(content)

    db.set_session_video(session_id, video_filename)
    print(f"[API] Video saved for session {session_id}: {video_filename} ({len(content)} bytes)")

    return {
        "status": "saved",
        "session_id": session_id,
        "video_filename": video_filename,
        "size_bytes": len(content)
    }


@router.get("/{session_id}/video")
async def get_session_video(session_id: str):
    """Stream recorded session video for interactive timeline playback."""
    session = db.get_session(session_id)
    video_filename = session.get("video_path") if session else None

    # Check candidates
    possible_paths = []
    if video_filename:
        possible_paths.append(VIDEOS_DIR / video_filename)
    possible_paths.append(VIDEOS_DIR / f"{session_id}.mp4")
    possible_paths.append(VIDEOS_DIR / f"{session_id}.webm")

    target_path = None
    for p in possible_paths:
        if p.exists() and p.stat().st_size > 0:
            target_path = p
            break

    if not target_path:
        raise HTTPException(status_code=404, detail="Video no disponible para esta sesión")

    media_type = "video/mp4" if target_path.suffix.lower() == ".mp4" else "video/webm"

    return FileResponse(
        path=str(target_path),
        media_type=media_type,
        filename=target_path.name
    )

