"""
Spatial Rhythm Observer — Escucha a Gandhi Research & Field Notes API
Endpoints for:
- Field notes (observations and testimonials)
- Tripartite Synthesis Engine under the 4 spatial criteria:
    1. Escala y estética arquitectónica
    2. Riqueza del paisaje
    3. Disponibilidad de instalaciones para permanecer
    4. Compatibilidad entre instalaciones y actividades
- Safeguards: 100% empirical grounding, zero emotional inferences.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import time
import json
import math

from storage.db import db

router = APIRouter(prefix="/api/research", tags=["research"])


class FieldNotePayload(BaseModel):
    id: Optional[str] = None
    session_id: Optional[str] = None
    note_type: str  # 'observation' or 'testimonial'
    criterion: str  # '1_architecture', '2_landscape', '3_stay_facilities', '4_compatibility'
    content: str
    author_role: Optional[str] = "student"
    x: Optional[float] = None
    y: Optional[float] = None
    zone_id: Optional[str] = None
    tags: Optional[List[str]] = []


@router.get("/notes")
async def list_notes(
    session_id: Optional[str] = Query(None),
    criterion: Optional[str] = Query(None),
    note_type: Optional[str] = Query(None)
):
    """List field notes and student testimonials."""
    notes = db.list_field_notes(session_id=session_id, criterion=criterion, note_type=note_type)
    for n in notes:
        try:
            n["tags"] = json.loads(n.get("tags_json") or "[]")
        except Exception:
            n["tags"] = []
    return {"notes": notes, "count": len(notes)}


@router.post("/notes")
async def create_note(payload: FieldNotePayload):
    """Save an empirical observation or student testimonial."""
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="El contenido de la nota no puede estar vacío.")

    valid_types = {"observation", "testimonial"}
    if payload.note_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"note_type debe ser uno de: {valid_types}")

    valid_criteria = {"1_architecture", "2_landscape", "3_stay_facilities", "4_compatibility"}
    if payload.criterion not in valid_criteria:
        raise HTTPException(status_code=400, detail=f"criterion debe ser uno de: {valid_criteria}")

    note_id = payload.id or f"note_{int(time.time() * 1000)}"
    tags_json = json.dumps(payload.tags or [])

    saved = db.add_field_note(
        note_id=note_id,
        note_type=payload.note_type,
        criterion=payload.criterion,
        content=payload.content.strip(),
        session_id=payload.session_id,
        author_role=payload.author_role or "student",
        x=payload.x,
        y=payload.y,
        zone_id=payload.zone_id,
        tags_json=tags_json
    )
    return {"status": "created", "note": saved}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str):
    """Delete a field note."""
    deleted = db.delete_field_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Nota de campo no encontrada")
    return {"status": "deleted", "id": note_id}


@router.get("/sessions/{session_id}/synthesis")
async def generate_tripartite_synthesis(session_id: str):
    """
    Generate the Tripartite Synthesis for Escucha a Gandhi under the 4 Criteria.
    Strictly differentiates:
    1. [HECHOS OBSERVADOS]: Quantifiable metrics from camera / tracker (heatmap density, dwell times, perimeter vs center, zone occupancy).
    2. [TESTIMONIOS REGISTRADOS]: Direct student field quotes/testimonies.
    3. [TENSIONES Y PATRONES DETECTADOS]: Spatial-behavioral relations backed by empirical evidence tags.
    PROHIBITS: emotional attributions ('felices', 'estresados', 'relajados').
    FORCES: behavioral & spatial taxonomy.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    # Fetch empirical data
    points = db.get_session_points(session_id, limit=30000)
    summaries = db.get_session_person_summaries(session_id)
    zones = db.list_zones()
    notes = db.list_field_notes(session_id=session_id)

    total_persons = session.get("total_persons") or len(summaries)
    duration_min = round((session.get("duration_seconds") or 0) / 60.0, 1)

    # 1. Metric calculations
    stopped_count = sum(1 for p in points if p.get("state") == "stopped")
    moving_count = sum(1 for p in points if p.get("state") == "moving")
    total_pts = max(1, len(points))
    dwell_ratio = round((stopped_count / total_pts) * 100, 1)
    flow_ratio = round((moving_count / total_pts) * 100, 1)

    # Perimeter vs Center calculation (Perimeter: distance to edges < 0.25)
    perim_pts = sum(1 for p in points if (p["x"] < 0.25 or p["x"] > 0.75 or p["y"] < 0.25 or p["y"] > 0.75))
    perim_ratio = round((perim_pts / total_pts) * 100, 1)
    center_ratio = round(100.0 - perim_ratio, 1)

    # Dwell time averages
    avg_dwell_sec = 0.0
    if summaries:
        avg_dwell_sec = round(sum(s.get("dwell_time_seconds", 0) for s in summaries) / len(summaries), 1)

    # Zone distribution
    zone_occupancy: Dict[str, int] = {}
    for p in points:
        z = p.get("zone")
        if z:
            zone_occupancy[z] = zone_occupancy.get(z, 0) + 1

    # Classify notes by criterion
    notes_by_criterion = {
        "1_architecture": [],
        "2_landscape": [],
        "3_stay_facilities": [],
        "4_compatibility": []
    }
    for n in notes:
        crit = n.get("criterion", "4_compatibility")
        if crit in notes_by_criterion:
            notes_by_criterion[crit].append(n)

    # Build the 4 Criteria Analysis Matrix
    criteria_matrix = []

    # ─── Criterio 1: Escala y Estética Arquitectónica ───
    c1_observations = (
        f"Se registraron {total_persons} personas en {duration_min} minutos. "
        f"La ocupación perimetral (efecto borde) representó el {perim_ratio}% del tiempo de presencia, "
        f"mientras que el área central concentró el {center_ratio}% de los registros."
    )
    c1_quotes = [n["content"] for n in notes_by_criterion["1_architecture"] if n["note_type"] == "testimonial"]
    c1_tension = (
        f"Patrón de concentración en bordes arquitectónicos (Edge Effect): "
        f"{'Predominio significativo de permanencia en los límites perimetrales' if perim_ratio > 55 else 'Distribución dispersa entre bordes y claros centrales'}. "
        f"[Evidencia: {perim_ratio}% en bordes vs {center_ratio}% en centro; Ref. Sesión {session_id[:8]}]."
    )
    criteria_matrix.append({
        "id": "1_architecture",
        "title": "1. Escala y Estética Arquitectónica",
        "hechos_observados": c1_observations,
        "testimonios_registrados": c1_quotes if c1_quotes else ["Sin testimonios directos ingresados para este criterio."],
        "tensiones_y_patrones": c1_tension
    })

    # ─── Criterio 2: Riqueza del Paisaje ───
    shade_zones = [z["name"] for z in zones if z.get("shade_level") in ("full_shade", "partial")]
    shade_pts = sum(zone_occupancy.get(zn, 0) for zn in shade_zones)
    shade_pct = round((shade_pts / total_pts) * 100, 1) if shade_zones else 0.0

    c2_observations = (
        f"Condición ambiental de la sesión: Clima '{session.get('weather_condition', 'no especificado')}', "
        f"Franja horaria '{session.get('time_slot', 'no especificado')}'. "
        f"Las zonas bajo cobertura vegetal/sombra concentraron el {shade_pct}% de la actividad registrada."
    )
    c2_quotes = [n["content"] for n in notes_by_criterion["2_landscape"] if n["note_type"] == "testimonial"]
    c2_tension = (
        f"Resguardo bioclimático: {'Alta atracción hacia zonas de sombra y vegetación durante la franja horaria observada' if shade_pct > 40 else 'Baja diferenciación en permanencia por sombra en las condiciones ambientales registradas'}. "
        f"[Evidencia: {shade_pct}% ocupación en zonas verdes/sombra; Clima: {session.get('weather_condition', 'general')}]."
    )
    criteria_matrix.append({
        "id": "2_landscape",
        "title": "2. Riqueza del Paisaje",
        "hechos_observados": c2_observations,
        "testimonios_registrados": c2_quotes if c2_quotes else ["Sin testimonios directos ingresados para este criterio."],
        "tensiones_y_patrones": c2_tension
    })

    # ─── Criterio 3: Disponibilidad de Instalaciones para Descansar y Permanecer ───
    stay_zones = [z["name"] for z in zones if z.get("zone_type") == "stay"]
    stay_pts = sum(zone_occupancy.get(zn, 0) for zn in stay_zones)
    stay_pct = round((stay_pts / total_pts) * 100, 1) if stay_zones else 0.0

    c3_observations = (
        f"Permanencia estática global: {dwell_ratio}% de los puntos correspondieron a personas detenidas "
        f"(tiempo medio de permanencia individual: {avg_dwell_sec} seg). "
        f"El mobiliario o superficies habilitadas albergaron el {stay_pct}% de dicha permanencia."
    )
    c3_quotes = [n["content"] for n in notes_by_criterion["3_stay_facilities"] if n["note_type"] == "testimonial"]
    c3_tension = (
        f"Demanda y saturación de infraestructura: {'Ocupación intensiva de superficies de apoyo existentes' if dwell_ratio > 40 else 'Espacio utilizado predominantemente como conector de tránsito'}. "
        f"[Evidencia: dwell_ratio={dwell_ratio}%, permanencia promedio={avg_dwell_sec}s]."
    )
    criteria_matrix.append({
        "id": "3_stay_facilities",
        "title": "3. Disponibilidad de Instalaciones para Descansar y Permanecer",
        "hechos_observados": c3_observations,
        "testimonios_registrados": c3_quotes if c3_quotes else ["Sin testimonios directos ingresados para este criterio."],
        "tensiones_y_patrones": c3_tension
    })

    # ─── Criterio 4: Compatibilidad de Instalaciones vs Actividades Reales ───
    c4_observations = (
        f"Relación dinámica: {flow_ratio}% de desplazamientos en tránsito frente a {dwell_ratio}% de permanencia estática. "
        f"Nivel sonoro ambiental estimado: '{session.get('ambient_noise_level', 'moderado')}'. "
        f"Total zonas espaciales configuradas: {len(zones)}."
    )
    c4_quotes = [n["content"] for n in notes_by_criterion["4_compatibility"] if n["note_type"] == "testimonial"]
    c4_tension = (
        f"Compatibilidad de usos: {'Coexistencia equilibrada entre recorridos peatonales y puntos de permanencia estática' if abs(flow_ratio - dwell_ratio) < 25 else ('Predominio de flujo de paso que limita la permanencia continua' if flow_ratio > dwell_ratio else 'Alta permanencia concentrada sin interrupción crítica de paso')}. "
        f"[Evidencia: Ratio Flujo {flow_ratio}% vs Permanencia {dwell_ratio}%; Ruido: {session.get('ambient_noise_level', 'moderado')}]."
    )
    criteria_matrix.append({
        "id": "4_compatibility",
        "title": "4. Compatibilidad entre Instalaciones y Actividades Reales",
        "hechos_observados": c4_observations,
        "testimonios_registrados": c4_quotes if c4_quotes else ["Sin testimonios directos ingresados para este criterio."],
        "tensiones_y_patrones": c4_tension
    })

    return {
        "project": "Escucha a Gandhi — Jardín Gandhi (Utadeo)",
        "session": {
            "id": session["id"],
            "name": session["name"],
            "duration_minutes": duration_min,
            "total_persons": total_persons,
            "weather_condition": session.get("weather_condition", "unspecified"),
            "time_slot": session.get("time_slot", "unspecified"),
            "ambient_noise_level": session.get("ambient_noise_level", "moderate")
        },
        "metrics_summary": {
            "dwell_ratio_percent": dwell_ratio,
            "flow_ratio_percent": flow_ratio,
            "perimeter_ratio_percent": perim_ratio,
            "center_ratio_percent": center_ratio,
            "avg_dwell_seconds": avg_dwell_sec
        },
        "criteria_matrix": criteria_matrix,
        "safeguards_applied": [
            "Diferenciación estricta entre Hechos Observables y Testimonios",
            "Cero inferencias de estados emocionales o suposiciones anímicas",
            "Anclaje de cada conclusión a evidencia empírica cuantitativa de sesión"
        ]
    }
