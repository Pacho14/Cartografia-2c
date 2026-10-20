"""
Spatial Rhythm Observer — Frame Processor
Main computer vision pipeline: YOLO11 detection + ByteTrack tracking.
Persists spatial coordinates and session metrics to SQLite.
"""

import time
import math
import json
import cv2
import numpy as np
from ultralytics import YOLO

from config import (
    YOLO_MODEL,
    YOLO_CONFIDENCE,
    YOLO_IMGSZ,
    DETECT_CLASSES,
    TRACKER_CONFIG,
    STOP_SPEED_THRESHOLD,
    TRACK_DISAPPEAR_FRAMES,
)
from storage.db import db


def point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """
    Ray casting algorithm to test if normalized point (x, y) is inside polygon.
    polygon: list of dicts with 'x' and 'y' (e.g. [{'x': 0.1, 'y': 0.2}, ...])
    """
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    p1 = polygon[0]
    p1x = p1['x'] if isinstance(p1, dict) else p1[0]
    p1y = p1['y'] if isinstance(p1, dict) else p1[1]

    for i in range(1, n + 1):
        p2 = polygon[i % n]
        p2x = p2['x'] if isinstance(p2, dict) else p2[0]
        p2y = p2['y'] if isinstance(p2, dict) else p2[1]

        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1, p1x, p1y = p2, p2x, p2y

    return inside


class FrameProcessor:
    """
    Processes video frames through YOLO11 + ByteTrack pipeline and stores spatial data.
    """

    def __init__(self, model_name: str = None, confidence: float = None):
        self.model_name = model_name or YOLO_MODEL
        self.confidence = confidence or YOLO_CONFIDENCE
        self.model = None  # Lazy-loaded
        self.frame_count = 0
        self.total_persons_detected = set()  # All unique IDs seen
        self.prev_positions = {}  # {track_id: (x, y, timestamp)}
        self.active_tracks = {}  # {track_id: frames_since_last_seen}
        self._processing_times = []  # Last N processing times for avg
        self._max_time_history = 30
        self._next_fallback_id = 1000

        # Session tracking state
        self.current_session_id = None
        self.session_name = "Observación Espacial"
        self.session_active = False
        self.session_paused = False
        self.session_start_time = None
        self.session_frames = 0
        self.session_max_concurrent = 0
        self.person_stats = {}  # {tid: {first_seen, last_seen, points_count, distance, speed_sum}}
        self._points_buffer = []  # Batch buffer for DB inserts
        self._buffer_flush_size = 20

        # Spatial Zones (Phase 3)
        self.zones = []
        self._load_saved_zones()

    def _load_saved_zones(self):
        """Load persistent zones from SQLite on startup."""
        try:
            raw_zones = db.list_zones()
            loaded = []
            for r in raw_zones:
                try:
                    poly = json.loads(r["polygon_json"])
                    loaded.append({
                        "id": r["id"],
                        "name": r["name"],
                        "color": r["color"],
                        "polygon": poly,
                    })
                except Exception:
                    pass
            self.zones = loaded
            print(f"[CV] Loaded {len(self.zones)} saved spatial zones from database")
        except Exception as e:
            print(f"[CV] Warning loading zones: {e}")

    def set_zones(self, zones: list):
        """Update active spatial zones from client or API."""
        self.zones = zones or []
        print(f"[CV] Active spatial zones set to: {[z.get('name') for z in self.zones]}")

    def _ensure_model_loaded(self):
        """Lazy-load the YOLO model on first use."""
        if self.model is None:
            print(f"[CV] Loading model: {self.model_name}...")
            start = time.time()
            self.model = YOLO(self.model_name)
            elapsed = time.time() - start
            print(f"[CV] Model loaded in {elapsed:.2f}s")

    def reset_tracking(self):
        """Reset tracking state for a new session."""
        self.flush_points_buffer()
        self.frame_count = 0
        self.total_persons_detected.clear()
        self.prev_positions.clear()
        self.active_tracks.clear()
        self._processing_times.clear()
        if self.model is not None:
            self.model.predictor = None

    def start_session(
        self,
        session_id: str,
        name: str = None,
        weather_condition: str = "unspecified",
        time_slot: str = "unspecified",
        ambient_noise_level: str = "moderate"
    ) -> dict:
        """Initialize and persist a new observation session."""
        self.reset_tracking()
        self.current_session_id = session_id
        self.session_name = name or f"Observación {time.strftime('%Y-%m-%d %H:%M')}"
        self.session_active = True
        self.session_paused = False
        self.session_start_time = time.time()
        self.session_frames = 0
        self.session_max_concurrent = 0
        self.person_stats.clear()
        self._points_buffer.clear()

        # Save to DB
        return db.create_session(
            self.current_session_id,
            self.session_name,
            self.session_start_time,
            weather_condition=weather_condition,
            time_slot=time_slot,
            ambient_noise_level=ambient_noise_level
        )

    def pause_session(self):
        """Pause data recording."""
        self.session_paused = True
        self.flush_points_buffer()
        if self.current_session_id:
            db.update_session_status(self.current_session_id, "paused")

    def resume_session(self):
        """Resume data recording."""
        self.session_paused = False
        if self.current_session_id:
            db.update_session_status(self.current_session_id, "active")

    def stop_session(self) -> dict:
        """Finalize session, flush remaining points, and save person summaries."""
        if not self.current_session_id:
            return {}

        self.flush_points_buffer()
        now = time.time()
        duration = max(0.0, now - (self.session_start_time or now))
        avg_fps = (self.session_frames / duration) if duration > 0 else 0.0

        # Build person summaries
        summaries = []
        for tid, p in self.person_stats.items():
            pts = p.get("points_count", 0)
            avg_speed = (p["speed_sum"] / pts) if pts > 0 else 0.0
            dwell = max(0.0, p["last_seen"] - p["first_seen"])
            summaries.append({
                "session_id": self.current_session_id,
                "person_id": tid,
                "label": f"P{tid:02d}",
                "first_seen": p["first_seen"],
                "last_seen": p["last_seen"],
                "dwell_time_seconds": round(dwell, 1),
                "avg_speed": round(avg_speed, 4),
                "distance_traveled": round(p.get("distance", 0.0), 4),
                "points_count": pts,
            })

        db.save_person_summaries(summaries)
        completed = db.complete_session(
            session_id=self.current_session_id,
            ended_at=now,
            duration_seconds=round(duration, 1),
            total_persons=len(self.total_persons_detected),
            max_concurrent=self.session_max_concurrent,
            total_frames=self.session_frames,
            avg_fps=round(avg_fps, 1),
        )

        session_summary = {
            "session_id": self.current_session_id,
            "name": self.session_name,
            "duration": round(duration, 1),
            "total_persons": len(self.total_persons_detected),
            "max_concurrent": self.session_max_concurrent,
            "total_frames": self.session_frames,
            "person_summaries_count": len(summaries),
            "completed": completed
        }

        # Clear active session state
        self.current_session_id = None
        self.session_active = False
        self.session_paused = False
        return session_summary

    def flush_points_buffer(self):
        """Write queued points to database in one batch transaction."""
        if self._points_buffer:
            try:
                db.insert_spatial_points_batch(self._points_buffer)
            except Exception as e:
                print(f"[DB ERROR] Failed to flush spatial points: {e}")
            finally:
                self._points_buffer.clear()

    def process_frame(self, frame_bytes: bytes) -> dict:
        """
        Process a single JPEG frame through the detection + tracking pipeline.
        """
        self._ensure_model_loaded()
        t_start = time.time()

        # ─── Decode frame ────────────────────────────────
        nparr = np.frombuffer(frame_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return {
                "persons": [],
                "frame_stats": {
                    "visible_count": 0,
                    "total_detected": len(self.total_persons_detected),
                    "frame_number": self.frame_count,
                    "processing_time_ms": 0,
                    "avg_processing_time_ms": 0,
                    "frame_width": 0,
                    "frame_height": 0,
                    "error": "Failed to decode frame",
                },
            }

        h, w = frame.shape[:2]

        # ─── Run YOLO11 + ByteTrack ──────────────────────
        results = self.model.track(
            frame,
            persist=True,
            tracker=TRACKER_CONFIG,
            classes=DETECT_CLASSES,
            conf=self.confidence,
            verbose=False,
            imgsz=YOLO_IMGSZ,
        )

        # ─── Extract detections ──────────────────────────
        persons = []
        current_track_ids = set()
        now = time.time()

        for result in results:
            boxes = result.boxes
            if boxes is not None and len(boxes) > 0:
                bboxes = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()

                if boxes.id is not None:
                    track_ids = boxes.id.cpu().numpy().astype(int)
                else:
                    # Spatial nearest-neighbor tracker fallback
                    # Matches previous tracks immediately so persons are tracked from frame 1
                    track_ids = []
                    for bbox in bboxes:
                        bx = (bbox[0] + bbox[2]) / 2.0 / w
                        by = bbox[3] / h
                        best_tid = None
                        best_dist = 0.18
                        for prev_id, (px, py, _) in self.prev_positions.items():
                            if prev_id not in track_ids:
                                d = math.hypot(bx - px, by - py)
                                if d < best_dist:
                                    best_dist = d
                                    best_tid = prev_id
                        if best_tid is not None:
                            track_ids.append(best_tid)
                        else:
                            self._next_fallback_id += 1
                            track_ids.append(self._next_fallback_id)

                for tid, bbox, conf in zip(track_ids, bboxes, confs):
                    tid = int(tid)
                    current_track_ids.add(tid)
                    self.total_persons_detected.add(tid)

                    x1, y1, x2, y2 = bbox
                    
                    # Center-bottom position (feet coordinate)
                    cx = (x1 + x2) / 2.0 / w
                    cy = y2 / h
                    
                    # Bounding box center
                    bcx = (x1 + x2) / 2.0 / w
                    bcy = (y1 + y2) / 2.0 / h

                    # Calculate speed and direction
                    speed = 0.0
                    direction = 0.0
                    state = "stopped"
                    dist_step = 0.0

                    if tid in self.prev_positions:
                        px, py, pt = self.prev_positions[tid]
                        dx = cx - px
                        dy = cy - py
                        dt = max(0.001, now - pt)
                        dist_step = math.sqrt(dx * dx + dy * dy)
                        speed = dist_step / dt
                        direction = math.degrees(math.atan2(-dy, dx)) % 360

                        if dist_step >= STOP_SPEED_THRESHOLD:
                            state = "moving"

                    self.prev_positions[tid] = (cx, cy, now)
                    self.active_tracks[tid] = 0

                    # ─── Spatial Zone Check (Phase 3) ───────────────
                    person_zone = None
                    person_zone_color = None
                    person_zone_id = None
                    for z in self.zones:
                        poly = z.get("polygon", [])
                        if poly and point_in_polygon(cx, cy, poly):
                            person_zone = z.get("name")
                            person_zone_color = z.get("color")
                            person_zone_id = z.get("id")
                            break

                    # Record spatial stats for active session
                    if self.current_session_id and not self.session_paused:
                        self._points_buffer.append((
                            self.current_session_id,
                            tid,
                            round(now, 3),
                            round(float(cx), 4),
                            round(float(cy), 4),
                            round(float(speed), 4),
                            round(float(direction), 1),
                            state,
                            person_zone
                        ))

                        if tid not in self.person_stats:
                            self.person_stats[tid] = {
                                "first_seen": now,
                                "last_seen": now,
                                "points_count": 1,
                                "distance": 0.0,
                                "speed_sum": speed,
                            }
                        else:
                            st = self.person_stats[tid]
                            st["last_seen"] = now
                            st["points_count"] += 1
                            st["distance"] += dist_step
                            st["speed_sum"] += speed

                    persons.append({
                        "id": tid,
                        "label": f"P{tid:02d}",
                        "x": round(float(cx), 4),
                        "y": round(float(cy), 4),
                        "center_x": round(float(bcx), 4),
                        "center_y": round(float(bcy), 4),
                        "bbox": [
                            round(float(x1 / w), 4),
                            round(float(y1 / h), 4),
                            round(float(x2 / w), 4),
                            round(float(y2 / h), 4),
                        ],
                        "confidence": round(float(conf), 3),
                        "speed": round(float(speed), 4),
                        "direction": round(float(direction), 1),
                        "state": state,
                        "zone": person_zone,
                        "zone_id": person_zone_id,
                        "zone_color": person_zone_color,
                    })

        # Check buffer flush
        if len(self._points_buffer) >= self._buffer_flush_size:
            self.flush_points_buffer()

        # Update session frame counters
        if self.current_session_id and not self.session_paused:
            self.session_frames += 1
            if len(persons) > self.session_max_concurrent:
                self.session_max_concurrent = len(persons)

        # ─── Calculate Zone Occupancies ──────────────────
        zone_occupancy = {}
        for z in self.zones:
            name = z.get("name")
            if name:
                zone_occupancy[name] = 0
        for p in persons:
            z_name = p.get("zone")
            if z_name and z_name in zone_occupancy:
                zone_occupancy[z_name] += 1

        # ─── Track disappearances ────────────────────────
        disappeared = []
        for tid in list(self.active_tracks.keys()):
            if tid not in current_track_ids:
                self.active_tracks[tid] += 1
                if self.active_tracks[tid] > TRACK_DISAPPEAR_FRAMES:
                    disappeared.append(tid)
                    del self.active_tracks[tid]
                    if tid in self.prev_positions:
                        del self.prev_positions[tid]

        # ─── Processing stats ────────────────────────────
        self.frame_count += 1
        t_elapsed = (time.time() - t_start) * 1000  # ms

        self._processing_times.append(t_elapsed)
        if len(self._processing_times) > self._max_time_history:
            self._processing_times.pop(0)

        avg_time = sum(self._processing_times) / len(self._processing_times)

        return {
            "persons": persons,
            "disappeared": disappeared,
            "session": {
                "active": self.session_active,
                "paused": self.session_paused,
                "id": self.current_session_id,
                "frames": self.session_frames,
                "max_concurrent": self.session_max_concurrent,
            },
            "frame_stats": {
                "visible_count": len(persons),
                "total_detected": len(self.total_persons_detected),
                "frame_number": self.frame_count,
                "processing_time_ms": round(t_elapsed, 1),
                "avg_processing_time_ms": round(avg_time, 1),
                "effective_fps": round(1000.0 / avg_time, 1) if avg_time > 0 else 0,
                "frame_width": w,
                "frame_height": h,
                "zone_occupancy": zone_occupancy,
            },
        }
