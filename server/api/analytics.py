"""
Spatial Rhythm Observer — Analytics & Heatmaps REST API (Phase 4)
Endpoints to query cumulative heatmaps, trajectory reconstructions, and spatial motion summaries.
"""

from fastapi import APIRouter, HTTPException, Query, Response
from typing import Optional, List
from pydantic import BaseModel

from storage.db import db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/sessions/{session_id}/heatmap")
async def get_session_heatmap(
    session_id: str,
    type: str = Query("presence", description="presence | dwell | flow"),
    person_id: Optional[int] = Query(None, description="Filtrar por ID de persona anónima"),
    time_from: Optional[float] = Query(None, description="Timestamp mínimo"),
    time_to: Optional[float] = Query(None, description="Timestamp máximo"),
    limit: int = Query(50000, description="Límite máximo de puntos")
):
    """
    Retrieve spatial coordinate points for cumulative heatmap rendering.
    - presence: All detected coordinates (cumulative density)
    - dwell: Stationary coordinates where state == 'stopped'
    - flow: Movement coordinates where state == 'moving'
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    points = db.get_session_heatmap_points(
        session_id=session_id,
        heatmap_type=type.lower(),
        person_id=person_id,
        time_from=time_from,
        time_to=time_to,
        limit=limit
    )

    return {
        "session_id": session_id,
        "type": type,
        "count": len(points),
        "points": points
    }


@router.get("/sessions/{session_id}/trajectories")
async def get_session_trajectories(
    session_id: str,
    person_id: Optional[int] = Query(None, description="Filtrar por ID de persona anónima"),
    time_from: Optional[float] = Query(None, description="Timestamp mínimo"),
    time_to: Optional[float] = Query(None, description="Timestamp máximo"),
    limit: int = Query(50000, description="Límite máximo de puntos")
):
    """
    Retrieve reconstructed continuous movement trajectories for each detected individual.
    Includes ordered waypoints, start/end nodes, duration, and calculated Euclidean distance.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    data = db.get_session_trajectories(
        session_id=session_id,
        person_id=person_id,
        time_from=time_from,
        time_to=time_to,
        limit=limit
    )
    return data


@router.get("/sessions/{session_id}/summary")
async def get_session_summary(session_id: str):
    """
    Get aggregated spatial movement metrics (dwell vs moving ratio, zone occupancies).
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    summary = db.get_session_analytics_summary(session_id)
    return {
        "session": session,
        "analytics": summary
    }


@router.get("/sessions/{session_id}/zones")
async def get_session_zone_metrics(session_id: str):
    """
    Phase 5: Get detailed dwell times, occupancy rates, peak counts,
    and inter-zone transition flows for a session.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    metrics = db.get_session_zone_metrics(session_id)
    return {
        "session": session,
        "metrics": metrics
    }


@router.get("/sessions/{session_id}/rhythms")
async def get_session_rhythms(
    session_id: str,
    bucket_seconds: int = Query(5, ge=1, le=60, description="Ventana de tiempo en segundos para agrupar mediciones (1 a 60)")
):
    """
    Phase 6: Detección de ritmos y patrones temporales recurrentes.
    Calcula cadencia de oleadas de afluencia, picos locales, valles de quietud,
    clasificación de ritmo espacial y sincronización de picos por zona.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    rhythms = db.get_session_rhythms(session_id, bucket_seconds=bucket_seconds)
    return {
        "session": session,
        "rhythms": rhythms
    }


# ─── Phase 7: Aglomeraciones y Alertas Espaciales ─────────
@router.get("/sessions/{session_id}/crowd-events")
async def get_session_crowd_events(
    session_id: str,
    cluster_radius: float = Query(0.16, ge=0.04, le=0.50, description="Radio de proximidad euclidiana para clustering espacial (0.04 a 0.50)"),
    min_cluster_size: int = Query(3, ge=2, le=20, description="Número mínimo de personas para constituir aglomeración")
):
    """
    Phase 7: Detección de aglomeraciones, cuellos de botella y picos locales de congestión.
    Devuelve eventos continuos de acumulación, niveles de severidad y coordenadas de centroides.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    crowd_data = db.get_session_crowd_events(
        session_id=session_id,
        cluster_radius=cluster_radius,
        min_cluster_size=min_cluster_size
    )
    return {
        "session": session,
        "crowd_analytics": crowd_data
    }


# ─── Phase 8: Comparativa entre Franjas Horarias y Sesiones ───
class CompareSessionsRequest(BaseModel):
    session_ids: List[str]


@router.post("/compare")
async def compare_sessions_post(req: CompareSessionsRequest):
    """
    Phase 8: Comparativa analítica entre múltiples sesiones seleccionadas (JSON POST).
    """
    if not req.session_ids:
        raise HTTPException(status_code=400, detail="Debe especificar al menos una sesión para comparar")
    comparison = db.compare_sessions(req.session_ids)
    return comparison


@router.get("/compare")
async def compare_sessions_get(session_ids: str = Query(..., description="IDs de sesión separados por coma")):
    """
    Phase 8: Comparativa analítica entre múltiples sesiones seleccionadas (GET comma-separated).
    """
    ids = [sid.strip() for sid in session_ids.split(",") if sid.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Debe especificar al menos una sesión para comparar")
    comparison = db.compare_sessions(ids)
    return comparison


@router.get("/time-slots")
async def get_historical_time_slots():
    """
    Phase 8: Agrupación histórica agregada por franjas horarias y días de la semana
    de todas las observaciones completadas.
    """
    slots_data = db.get_time_slots_analytics()
    return slots_data


# ─── Phase 9: Interacciones y Proximidad Social ────────────
@router.get("/sessions/{session_id}/interactions")
async def get_session_interactions(
    session_id: str,
    distance_threshold: float = Query(0.12, ge=0.04, le=0.40, description="Distancia euclidiana máxima de proximidad (0.04 a 0.40)"),
    min_seconds: float = Query(3.0, ge=1.0, le=60.0, description="Segundos mínimos de proximidad continuada para validar interacción")
):
    """
    Phase 9: Detección de interacciones interpersonales y proximidad social.
    Identifica pares de individuos en interacción continuada, clasificación cualitativa
    (conversación estacionaria vs caminata conjunta) y ratio social del espacio.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    interactions_data = db.get_session_interactions(
        session_id=session_id,
        distance_threshold=distance_threshold,
        min_interaction_seconds=min_seconds
    )
    return {
        "session": session,
        "interactions": interactions_data
    }


import unicodedata
import re


def _sanitize_ascii_filename(name: str) -> str:
    nfkd = unicodedata.normalize('NFKD', str(name or 'sesion'))
    ascii_str = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', ascii_str).strip('_')
    return clean or "sesion"


# ─── Reporte y Exportación de Datos Tabulares (CSV/Excel) ──
@router.get("/sessions/{session_id}/report")
async def get_session_report_data(session_id: str):
    """
    Obtener datos procesados estructurados del informe de observación y recorridos.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    report = db.get_simple_session_report(session_id)
    return report


@router.get("/sessions/{session_id}/export/csv")
async def export_session_csv(
    session_id: str,
    sections: Optional[str] = Query(None, description="Secciones a incluir separadas por comas"),
    delimiter: str = Query(",", description="Delimitador de columnas (',' o ';')"),
    mode: str = Query("simple", description="'simple' | 'full'")
):
    """
    Exportación de informe de la sesión en formato CSV compatible con Microsoft Excel (UTF-8 con BOM).
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    if mode == "full" or sections:
        sec_list = [s.strip().lower() for s in (sections or "summary,zones,rhythms,crowds,interactions,peaks").split(",") if s.strip()]
        csv_content = db.export_session_tabular_data(session_id, sections=sec_list, delimiter=delimiter)
    else:
        csv_content = db.export_simple_session_csv(session_id, delimiter=delimiter)

    safe_name = _sanitize_ascii_filename(session.get("name", "sesion"))
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_{session_id}.csv"'
        }
    )


@router.get("/sessions/{session_id}/export/excel")
async def export_session_excel_endpoint(
    session_id: str,
    sections: Optional[str] = Query(None, description="Secciones a incluir separadas por comas"),
    mode: str = Query("simple", description="'simple' | 'full'")
):
    """
    Exportación ejecutiva a Microsoft Excel (.xlsx) nativo con formato corporativo.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    if mode == "full" or sections:
        sec_list = [s.strip().lower() for s in (sections or "summary,zones,rhythms,crowds,interactions,peaks").split(",") if s.strip()]
        excel_bytes = db.export_session_excel(session_id, sections=sec_list)
    else:
        excel_bytes = db.export_simple_session_excel(session_id)

    safe_name = _sanitize_ascii_filename(session.get("name", "sesion"))
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_{session_id}.xlsx"'
        }
    )



