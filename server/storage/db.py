"""
Spatial Rhythm Observer — Database Layer (SQLite)
Handles persistence for sessions, spatial tracking points, and person summaries.
"""

import math
import sqlite3
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from config import STORAGE_DIR

DB_PATH = STORAGE_DIR / "spatial_data.db"


class Database:
    """SQLite Database manager for spatial observation data."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = str(db_path)
        self._init_tables()

    def get_connection(self) -> sqlite3.Connection:
        """Create a connection with row factory and foreign keys enabled."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")  # Fast concurrent read/write
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_tables(self):
        """Create tables and indexes if they do not exist."""
        with self.get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL,
                duration_seconds REAL DEFAULT 0,
                total_persons INTEGER DEFAULT 0,
                max_concurrent INTEGER DEFAULT 0,
                total_frames INTEGER DEFAULT 0,
                avg_fps REAL DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS spatial_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                person_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                speed REAL DEFAULT 0,
                direction REAL DEFAULT 0,
                state TEXT DEFAULT 'stopped',
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_spatial_session 
                ON spatial_points (session_id, timestamp);

            CREATE INDEX IF NOT EXISTS idx_spatial_person 
                ON spatial_points (session_id, person_id);

            CREATE TABLE IF NOT EXISTS person_summaries (
                session_id TEXT NOT NULL,
                person_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                dwell_time_seconds REAL DEFAULT 0,
                avg_speed REAL DEFAULT 0,
                distance_traveled REAL DEFAULT 0,
                points_count INTEGER DEFAULT 0,
                PRIMARY KEY (session_id, person_id),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS spatial_zones (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                color TEXT NOT NULL,
                polygon_json TEXT NOT NULL,
                zone_type TEXT DEFAULT 'general',
                surface_type TEXT DEFAULT 'paved',
                shade_level TEXT DEFAULT 'variable',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS field_notes (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                note_type TEXT NOT NULL, -- 'observation' or 'testimonial'
                criterion TEXT NOT NULL, -- '1_architecture', '2_landscape', '3_stay_facilities', '4_compatibility'
                content TEXT NOT NULL,
                author_role TEXT DEFAULT 'student',
                x REAL,
                y REAL,
                zone_id TEXT,
                tags_json TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
            );
            """)

            # Safe migration for existing DB
            migrations = [
                "ALTER TABLE spatial_points ADD COLUMN zone TEXT",
                "ALTER TABLE sessions ADD COLUMN video_path TEXT",
                "ALTER TABLE sessions ADD COLUMN weather_condition TEXT DEFAULT 'unspecified'",
                "ALTER TABLE sessions ADD COLUMN time_slot TEXT DEFAULT 'unspecified'",
                "ALTER TABLE sessions ADD COLUMN ambient_noise_level TEXT DEFAULT 'moderate'",
                "ALTER TABLE spatial_zones ADD COLUMN zone_type TEXT DEFAULT 'general'",
                "ALTER TABLE spatial_zones ADD COLUMN surface_type TEXT DEFAULT 'paved'",
                "ALTER TABLE spatial_zones ADD COLUMN shade_level TEXT DEFAULT 'variable'",
            ]
            for m in migrations:
                try:
                    conn.execute(m)
                except Exception:
                    pass

    # ─── SESSIONS ────────────────────────────────────────────

    def set_session_video(self, session_id: str, video_path: str):
        """Update session record with video path."""
        with self.get_connection() as conn:
            conn.execute("UPDATE sessions SET video_path = ? WHERE id = ?", (video_path, session_id))

    def create_session(
        self,
        session_id: str,
        name: str,
        started_at: Optional[float] = None,
        weather_condition: str = "unspecified",
        time_slot: str = "unspecified",
        ambient_noise_level: str = "moderate"
    ) -> Dict[str, Any]:
        """Create a new observation session with environmental context."""
        started_at = started_at or time.time()
        name = (name or "").strip() or f"Sesión {time.strftime('%Y-%m-%d %H:%M')}"
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, name, started_at, status, weather_condition, time_slot, ambient_noise_level)
                VALUES (?, ?, ?, 'active', ?, ?, ?)
                """,
                (session_id, name, started_at, weather_condition, time_slot, ambient_noise_level)
            )
        return self.get_session(session_id)

    def update_session_status(self, session_id: str, status: str):
        """Update session status (active, paused, completed)."""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET status = ? WHERE id = ?",
                (status, session_id)
            )

    def complete_session(
        self,
        session_id: str,
        ended_at: Optional[float] = None,
        duration_seconds: float = 0,
        total_persons: int = 0,
        max_concurrent: int = 0,
        total_frames: int = 0,
        avg_fps: float = 0
    ) -> Optional[Dict[str, Any]]:
        """Mark a session as completed with final summary metrics."""
        ended_at = ended_at or time.time()
        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE sessions 
                SET ended_at = ?, duration_seconds = ?, total_persons = ?,
                    max_concurrent = ?, total_frames = ?, avg_fps = ?, status = 'completed'
                WHERE id = ?
                """,
                (ended_at, duration_seconds, total_persons, max_concurrent, total_frames, avg_fps, session_id)
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata by ID."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all observation sessions sorted from newest to oldest."""
        with self.get_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM sessions 
                ORDER BY started_at DESC 
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its points and summaries (CASCADE)."""
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cur.rowcount > 0

    # ─── SPATIAL POINTS ──────────────────────────────────────

    def insert_spatial_points_batch(self, points: List[tuple]):
        """
        Batch insert tracking points for high performance.
        points: list of tuples:
        (session_id, person_id, timestamp, x, y, speed, direction, state) or
        (session_id, person_id, timestamp, x, y, speed, direction, state, zone)
        """
        if not points:
            return
        with self.get_connection() as conn:
            if len(points[0]) >= 9:
                conn.executemany(
                    """
                    INSERT INTO spatial_points 
                    (session_id, person_id, timestamp, x, y, speed, direction, state, zone)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    points
                )
            else:
                conn.executemany(
                    """
                    INSERT INTO spatial_points 
                    (session_id, person_id, timestamp, x, y, speed, direction, state)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    points
                )

    def get_session_points(
        self,
        session_id: str,
        person_id: Optional[int] = None,
        limit: int = 10000
    ) -> List[Dict[str, Any]]:
        """Retrieve recorded spatial coordinates for a session."""
        with self.get_connection() as conn:
            if person_id is not None:
                cur = conn.execute(
                    """
                    SELECT person_id, timestamp, x, y, speed, direction, state
                    FROM spatial_points
                    WHERE session_id = ? AND person_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                    """,
                    (session_id, person_id, limit)
                )
            else:
                cur = conn.execute(
                    """
                    SELECT person_id, timestamp, x, y, speed, direction, state
                    FROM spatial_points
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                    """,
                    (session_id, limit)
                )
            return [dict(row) for row in cur.fetchall()]

    # ─── PERSON SUMMARIES ────────────────────────────────────

    def save_person_summaries(self, summaries: List[Dict[str, Any]]):
        """Insert or replace person summaries for a session."""
        if not summaries:
            return
        rows = [
            (
                s["session_id"],
                s["person_id"],
                s.get("label", f"P{s['person_id']:02d}"),
                s["first_seen"],
                s["last_seen"],
                s.get("dwell_time_seconds", 0.0),
                s.get("avg_speed", 0.0),
                s.get("distance_traveled", 0.0),
                s.get("points_count", 0),
            )
            for s in summaries
        ]
        with self.get_connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO person_summaries
                (session_id, person_id, label, first_seen, last_seen,
                 dwell_time_seconds, avg_speed, distance_traveled, points_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows
            )

    def get_session_person_summaries(self, session_id: str) -> List[Dict[str, Any]]:
        """Retrieve person summaries for a session."""
        with self.get_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM person_summaries
                WHERE session_id = ?
                ORDER BY person_id ASC
                """,
                (session_id,)
            )
            return [dict(row) for row in cur.fetchall()]

    # ─── SPATIAL ZONES ───────────────────────────────────────

    def save_zone(
        self,
        zone_id: str,
        name: str,
        color: str,
        polygon_json: str,
        zone_type: str = "general",
        surface_type: str = "paved",
        shade_level: str = "variable"
    ) -> Dict[str, Any]:
        """Save or update a spatial polygon zone with sensory attributes."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO spatial_zones 
                (id, name, color, polygon_json, zone_type, surface_type, shade_level)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (zone_id, name, color, polygon_json, zone_type, surface_type, shade_level)
            )
        return self.get_zone(zone_id)

    def get_zone(self, zone_id: str) -> Optional[Dict[str, Any]]:
        """Get a single zone by ID."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT * FROM spatial_zones WHERE id = ?", (zone_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_zones(self) -> List[Dict[str, Any]]:
        """List all defined spatial zones."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT * FROM spatial_zones ORDER BY created_at ASC")
            return [dict(row) for row in cur.fetchall()]

    def delete_zone(self, zone_id: str) -> bool:
        """Delete a spatial zone."""
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM spatial_zones WHERE id = ?", (zone_id,))
            return cur.rowcount > 0

    # ─── FIELD NOTES & TESTIMONIALS (ESCUCHA A GANDHI) ────────

    def add_field_note(
        self,
        note_id: str,
        note_type: str,
        criterion: str,
        content: str,
        session_id: Optional[str] = None,
        author_role: str = "student",
        x: Optional[float] = None,
        y: Optional[float] = None,
        zone_id: Optional[str] = None,
        tags_json: str = "[]"
    ) -> Dict[str, Any]:
        """Add a field observation or student testimonial anchored to spatial criteria."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO field_notes (id, session_id, note_type, criterion, content, author_role, x, y, zone_id, tags_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (note_id, session_id, note_type, criterion, content, author_role, x, y, zone_id, tags_json)
            )
        return self.get_field_note(note_id)

    def get_field_note(self, note_id: str) -> Optional[Dict[str, Any]]:
        """Get a single field note by ID."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT * FROM field_notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_field_notes(
        self,
        session_id: Optional[str] = None,
        criterion: Optional[str] = None,
        note_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List field notes optionally filtered by session, criterion, or note_type."""
        query = "SELECT * FROM field_notes WHERE 1=1"
        params: List[Any] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if criterion:
            query += " AND criterion = ?"
            params.append(criterion)
        if note_type:
            query += " AND note_type = ?"
            params.append(note_type)
        query += " ORDER BY created_at DESC"
        with self.get_connection() as conn:
            cur = conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def delete_field_note(self, note_id: str) -> bool:
        """Delete a field note."""
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM field_notes WHERE id = ?", (note_id,))
            return cur.rowcount > 0

    # ─── HEATMAPS & TRAJECTORIES (PHASE 4) ────────────────────

    def get_session_heatmap_points(
        self,
        session_id: str,
        heatmap_type: str = "presence",
        person_id: Optional[int] = None,
        time_from: Optional[float] = None,
        time_to: Optional[float] = None,
        limit: int = 50000
    ) -> List[Dict[str, Any]]:
        """
        Retrieve filtered coordinates for cumulative heatmaps.
        heatmap_type:
            - 'presence': all coordinates
            - 'dwell': only stopped positions (state = 'stopped')
            - 'flow': only moving positions (state = 'moving')
        """
        query = "SELECT person_id, timestamp, x, y, speed, direction, state, zone FROM spatial_points WHERE session_id = ?"
        params: List[Any] = [session_id]

        if heatmap_type == "dwell":
            query += " AND state = 'stopped'"
        elif heatmap_type == "flow":
            query += " AND state = 'moving'"

        if person_id is not None:
            query += " AND person_id = ?"
            params.append(person_id)

        if time_from is not None:
            query += " AND timestamp >= ?"
            params.append(time_from)

        if time_to is not None:
            query += " AND timestamp <= ?"
            params.append(time_to)

        query += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)

        with self.get_connection() as conn:
            cur = conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def get_session_trajectories(
        self,
        session_id: str,
        person_id: Optional[int] = None,
        time_from: Optional[float] = None,
        time_to: Optional[float] = None,
        limit: int = 50000
    ) -> Dict[str, Any]:
        """
        Retrieve and reconstruct continuous trajectory paths for detected individuals.
        """
        import math
        query = "SELECT person_id, timestamp, x, y, speed, direction, state, zone FROM spatial_points WHERE session_id = ?"
        params: List[Any] = [session_id]

        if person_id is not None:
            query += " AND person_id = ?"
            params.append(person_id)

        if time_from is not None:
            query += " AND timestamp >= ?"
            params.append(time_from)

        if time_to is not None:
            query += " AND timestamp <= ?"
            params.append(time_to)

        query += " ORDER BY person_id ASC, timestamp ASC LIMIT ?"
        params.append(limit)

        with self.get_connection() as conn:
            cur = conn.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]

        # Group by person_id
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            pid = r["person_id"]
            if pid not in grouped:
                grouped[pid] = []
            grouped[pid].append(r)

        trajectories = []
        for pid, pts in grouped.items():
            if not pts:
                continue
            total_dist = 0.0
            for i in range(1, len(pts)):
                dx = pts[i]["x"] - pts[i-1]["x"]
                dy = pts[i]["y"] - pts[i-1]["y"]
                total_dist += math.sqrt(dx * dx + dy * dy)

            start_t = pts[0]["timestamp"]
            end_t = pts[-1]["timestamp"]
            trajectories.append({
                "person_id": pid,
                "label": f"P{pid:02d}",
                "start_time": start_t,
                "end_time": end_t,
                "duration_seconds": round(end_t - start_t, 2),
                "points_count": len(pts),
                "total_distance": round(total_dist, 4),
                "start_point": {"x": pts[0]["x"], "y": pts[0]["y"], "zone": pts[0].get("zone")},
                "end_point": {"x": pts[-1]["x"], "y": pts[-1]["y"], "zone": pts[-1].get("zone")},
                "points": [{"x": p["x"], "y": p["y"], "t": p["timestamp"], "speed": p["speed"], "state": p["state"], "zone": p.get("zone")} for p in pts]
            })

        return {
            "session_id": session_id,
            "trajectories_count": len(trajectories),
            "trajectories": trajectories
        }

    def get_session_analytics_summary(self, session_id: str) -> Dict[str, Any]:
        """Compute spatial aggregate analytics for a session."""
        with self.get_connection() as conn:
            session = self.get_session(session_id)
            if not session:
                return {}

            # Count moving vs stopped points
            cur = conn.execute(
                """
                SELECT state, COUNT(*) as cnt 
                FROM spatial_points 
                WHERE session_id = ? 
                GROUP BY state
                """,
                (session_id,)
            )
            states = {row["state"]: row["cnt"] for row in cur.fetchall()}

            # Zone distribution
            cur = conn.execute(
                """
                SELECT zone, COUNT(*) as cnt 
                FROM spatial_points 
                WHERE session_id = ? AND zone IS NOT NULL AND zone != ''
                GROUP BY zone 
                ORDER BY cnt DESC
                """,
                (session_id,)
            )
            zone_counts = {row["zone"]: row["cnt"] for row in cur.fetchall()}

            # Unique persons count
            cur = conn.execute(
                "SELECT COUNT(DISTINCT person_id) as total_p FROM spatial_points WHERE session_id = ?",
                (session_id,)
            )
            row_p = cur.fetchone()
            total_unique = row_p["total_p"] if row_p else 0

            return {
                "session_id": session_id,
                "total_points": sum(states.values()),
                "stopped_points": states.get("stopped", 0),
                "moving_points": states.get("moving", 0),
                "total_unique_persons": total_unique,
                "zone_distribution": zone_counts,
            }

    def get_session_zone_metrics(self, session_id: str) -> Dict[str, Any]:
        """
        Phase 5: Compute detailed dwell times, occupancy rates, peak headcounts,
        and inter-zone transition flows for a session.
        """
        with self.get_connection() as conn:
            session = self.get_session(session_id)
            if not session:
                return {}

            duration = session.get("duration_seconds") or 1.0

            # Fetch configured spatial zones so unvisited zones are also represented
            cur_z = conn.execute("SELECT name, color FROM spatial_zones")
            configured_zones = {row["name"]: row["color"] for row in cur_z.fetchall()}

            # Fetch all points with zones ordered by person_id, timestamp
            cur = conn.execute(
                """
                SELECT person_id, timestamp, zone 
                FROM spatial_points 
                WHERE session_id = ? 
                ORDER BY person_id ASC, timestamp ASC
                """,
                (session_id,)
            )
            rows = [dict(r) for r in cur.fetchall()]

        if rows:
            actual_span = rows[-1]["timestamp"] - rows[0]["timestamp"]
            duration = max(duration, actual_span, 1.0)

        # Group stays by person
        zone_stays: Dict[str, List[float]] = {}
        transitions: Dict[str, Dict[str, int]] = {}
        zone_unique_persons: Dict[str, set] = {}

        grouped_by_person: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            pid = r["person_id"]
            if pid not in grouped_by_person:
                grouped_by_person[pid] = []
            grouped_by_person[pid].append(r)

        for pid, pts in grouped_by_person.items():
            current_zone = None
            zone_start_t = None
            last_t = None

            for p in pts:
                z = p.get("zone")
                t = p["timestamp"]

                if z:
                    if z not in zone_unique_persons:
                        zone_unique_persons[z] = set()
                    zone_unique_persons[z].add(pid)

                is_gap = last_t is not None and (t - last_t) > 4.0

                if is_gap or z != current_zone:
                    if current_zone and zone_start_t is not None and last_t is not None:
                        dwell = max(1.0, last_t - zone_start_t)
                        if current_zone not in zone_stays:
                            zone_stays[current_zone] = []
                        zone_stays[current_zone].append(dwell)

                        if not is_gap and z and z != current_zone:
                            if current_zone not in transitions:
                                transitions[current_zone] = {}
                            transitions[current_zone][z] = transitions[current_zone].get(z, 0) + 1

                    current_zone = z
                    zone_start_t = t if z else None

                last_t = t

            if current_zone and zone_start_t is not None and last_t is not None:
                dwell = max(1.0, last_t - zone_start_t)
                if current_zone not in zone_stays:
                    zone_stays[current_zone] = []
                zone_stays[current_zone].append(dwell)

        zone_occupancy_seconds: Dict[str, float] = {}
        zone_peaks: Dict[str, int] = {}

        if rows:
            min_t = rows[0]["timestamp"]
            buckets: Dict[tuple, set] = {}
            for r in rows:
                z = r.get("zone")
                if not z:
                    continue
                sec = int(r["timestamp"] - min_t)
                key = (sec, z)
                if key not in buckets:
                    buckets[key] = set()
                buckets[key].add(r["person_id"])

            for (sec, z), pids in buckets.items():
                zone_occupancy_seconds[z] = zone_occupancy_seconds.get(z, 0.0) + 1.0
                if len(pids) > zone_peaks.get(z, 0):
                    zone_peaks[z] = len(pids)

        all_zones = sorted(list(set(list(zone_stays.keys()) + list(zone_occupancy_seconds.keys()) + list(configured_zones.keys()))))
        zone_metrics = []

        for z in all_zones:
            stays = zone_stays.get(z, [])
            total_dwell = sum(stays)
            visits = len(stays)
            avg_dwell = round(total_dwell / visits, 1) if visits > 0 else 0.0
            max_dwell = round(max(stays), 1) if stays else 0.0
            min_dwell = round(min(stays), 1) if stays else 0.0
            occ_sec = zone_occupancy_seconds.get(z, 0.0)
            occ_rate = round(min(100.0, (occ_sec / max(1.0, duration)) * 100), 1)
            peak = zone_peaks.get(z, 0)
            color = configured_zones.get(z, "#0a84ff")

            zone_metrics.append({
                "zone": z,
                "color": color,
                "visits_count": visits,
                "unique_persons_count": len(zone_unique_persons.get(z, set())),
                "total_dwell_seconds": round(total_dwell, 1),
                "avg_dwell_seconds": avg_dwell,
                "min_dwell_seconds": min_dwell,
                "max_dwell_seconds": max_dwell,
                "occupancy_seconds": round(occ_sec, 1),
                "occupancy_rate_percent": occ_rate,
                "peak_occupancy": peak,
            })

        return {
            "session_id": session_id,
            "duration_seconds": round(duration, 1),
            "zones": zone_metrics,
            "transitions": transitions,
        }

    def get_session_rhythms(self, session_id: str, bucket_seconds: int = 5) -> Dict[str, Any]:
        """
        Phase 6: Temporal Rhythms, Peak Cadence, Flow-vs-Stay Waves,
        and Inter-Zone Phase Synchronization Analysis.
        """
        bucket_seconds = max(1, min(60, int(bucket_seconds or 5)))

        with self.get_connection() as conn:
            session = self.get_session(session_id)
            if not session:
                return {}

            # Configured zones
            cur_z = conn.execute("SELECT name, color FROM spatial_zones")
            configured_zones = {row["name"]: row["color"] for row in cur_z.fetchall()}

            # Fetch all points ordered chronologically
            cur = conn.execute(
                """
                SELECT person_id, timestamp, x, y, speed, state, zone 
                FROM spatial_points 
                WHERE session_id = ? 
                ORDER BY timestamp ASC
                """,
                (session_id,)
            )
            rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            return {
                "session_id": session_id,
                "duration_seconds": 0,
                "bucket_seconds": bucket_seconds,
                "timeline": [],
                "peaks": [],
                "valleys": [],
                "rhythm_summary": {
                    "classification": "Sin Datos",
                    "description": "No se registraron coordenadas para esta sesión.",
                    "coefficient_of_variation": 0.0,
                    "avg_cadence_seconds": None,
                    "max_peak_count": 0,
                    "longest_lull_seconds": 0,
                    "movement_ratio_percent": 0,
                    "stopped_ratio_percent": 0,
                    "unique_persons_count": 0,
                },
                "zone_rhythms": {},
            }

        start_t = rows[0]["timestamp"]
        end_t = rows[-1]["timestamp"]
        total_span = max(1.0, end_t - start_t)
        total_buckets = max(1, math.ceil(total_span / bucket_seconds))

        timeline_buckets = []
        for b in range(total_buckets):
            t_offset = b * bucket_seconds
            timeline_buckets.append({
                "bucket_index": b,
                "t": t_offset,
                "time_label": f"{int(t_offset // 60):02d}:{int(t_offset % 60):02d}",
                "persons": set(),
                "moving": set(),
                "stopped": set(),
                "zones": {z: set() for z in configured_zones.keys()},
                "speeds": []
            })

        all_unique_persons = set()
        for r in rows:
            t = r["timestamp"]
            pid = r["person_id"]
            all_unique_persons.add(pid)
            b_idx = min(total_buckets - 1, max(0, int((t - start_t) // bucket_seconds)))
            b = timeline_buckets[b_idx]

            b["persons"].add(pid)
            if r["state"] == "moving":
                b["moving"].add(pid)
            else:
                b["stopped"].add(pid)

            z = r.get("zone")
            if z:
                if z not in b["zones"]:
                    b["zones"][z] = set()
                b["zones"][z].add(pid)

            if r.get("speed") is not None:
                b["speeds"].append(float(r["speed"]))

        timeline_data = []
        counts_series = []
        for b in timeline_buckets:
            total_c = len(b["persons"])
            mov_c = len(b["moving"])
            stp_c = len(b["stopped"])
            counts_series.append(total_c)

            zone_counts = {z: len(pids) for z, pids in b["zones"].items()}
            avg_spd = round(sum(b["speeds"]) / len(b["speeds"]), 3) if b["speeds"] else 0.0

            timeline_data.append({
                "t": b["t"],
                "time_label": b["time_label"],
                "total_count": total_c,
                "moving_count": mov_c,
                "stopped_count": stp_c,
                "avg_speed": avg_spd,
                "zones": zone_counts,
            })

        # Peak & Wave Detection
        peaks = []
        n_buckets = len(timeline_data)
        for i in range(n_buckets):
            c = timeline_data[i]["total_count"]
            if c == 0:
                continue

            is_local_max = True
            if i > 0 and timeline_data[i - 1]["total_count"] > c:
                is_local_max = False
            if i < n_buckets - 1 and timeline_data[i + 1]["total_count"] > c:
                is_local_max = False

            if is_local_max and c >= 1:
                z_counts = timeline_data[i]["zones"]
                dominant_z = max(z_counts.items(), key=lambda item: item[1])[0] if z_counts and any(z_counts.values()) else None

                peaks.append({
                    "t": timeline_data[i]["t"],
                    "time_label": timeline_data[i]["time_label"],
                    "count": c,
                    "dominant_zone": dominant_z,
                })

        # Quiet lulls detection
        lull_runs = []
        current_lull_start = None
        for i in range(n_buckets):
            c = timeline_data[i]["total_count"]
            if c == 0:
                if current_lull_start is None:
                    current_lull_start = timeline_data[i]["t"]
            else:
                if current_lull_start is not None:
                    lull_dur = timeline_data[i]["t"] - current_lull_start
                    if lull_dur >= bucket_seconds * 2:
                        lull_runs.append({
                            "start_t": current_lull_start,
                            "end_t": timeline_data[i]["t"],
                            "duration_seconds": round(lull_dur, 1),
                            "time_label": f"{int(current_lull_start // 60):02d}:{int(current_lull_start % 60):02d}",
                        })
                    current_lull_start = None

        if current_lull_start is not None:
            lull_dur = total_span - current_lull_start
            if lull_dur >= bucket_seconds * 2:
                lull_runs.append({
                    "start_t": current_lull_start,
                    "end_t": total_span,
                    "duration_seconds": round(lull_dur, 1),
                    "time_label": f"{int(current_lull_start // 60):02d}:{int(current_lull_start % 60):02d}",
                })

        # Wave Cadence
        wave_intervals = []
        if len(peaks) >= 2:
            for i in range(1, len(peaks)):
                dt = peaks[i]["t"] - peaks[i - 1]["t"]
                wave_intervals.append(dt)

        avg_cadence = round(sum(wave_intervals) / len(wave_intervals), 1) if wave_intervals else None

        # Statistics & Classification
        mean_c = sum(counts_series) / len(counts_series) if counts_series else 0.0
        variance = sum((x - mean_c) ** 2 for x in counts_series) / len(counts_series) if counts_series else 0.0
        std_dev = math.sqrt(variance)
        cv = (std_dev / mean_c) if mean_c > 0 else 0.0

        total_moving_pts = sum(1 for r in rows if r["state"] == "moving")
        total_stopped_pts = sum(1 for r in rows if r["state"] == "stopped")
        total_valid_pts = max(1, total_moving_pts + total_stopped_pts)
        mov_pct = round((total_moving_pts / total_valid_pts) * 100, 1)
        stp_pct = round((total_stopped_pts / total_valid_pts) * 100, 1)

        max_peak = max(counts_series) if counts_series else 0
        longest_lull = max([lr["duration_seconds"] for lr in lull_runs], default=0.0)

        if mean_c == 0:
            classification = "Inactivo"
            desc = "Espacio desprovisto de ocupantes durante la sesión."
        elif len(peaks) >= 2 and cv > 0.60:
            classification = "Pulsante / Por Olas"
            desc = f"Dinámica intermitente con oleadas de afluencia cada ~{avg_cadence or 0}s, seguidas de pausas."
        elif cv <= 0.45 and mean_c >= 1.0:
            classification = "Continuo / Estable"
            desc = "Flujo uniforme y homogéneo con densidad constante y sin fluctuaciones abruptas."
        elif mov_pct >= 75.0:
            classification = "Tránsito Rápido"
            desc = "Corredor de alta fluidez donde los ocupantes se desplazan activamente sin fijar permanencias."
        elif stp_pct >= 60.0:
            classification = "Estancia / Remanso"
            desc = "Espacio de permanencia donde la actividad dominante es estacionaria o de reposo."
        else:
            classification = "Fluctuante Mixto"
            desc = "Ritmo alterno con variación moderada en los niveles de ocupación y movimiento."

        # Per-Zone Peak Time Synchronization
        zone_rhythms = {}
        for z in configured_zones.keys():
            z_series = [b["zones"].get(z, 0) for b in timeline_data]
            z_max = max(z_series) if z_series else 0
            z_peak_t = None
            if z_max > 0:
                idx = z_series.index(z_max)
                z_peak_t = timeline_data[idx]["t"]

            zone_rhythms[z] = {
                "color": configured_zones.get(z, "#0a84ff"),
                "peak_count": z_max,
                "peak_time": z_peak_t,
                "peak_time_label": f"{int((z_peak_t or 0) // 60):02d}:{int((z_peak_t or 0) % 60):02d}" if z_peak_t is not None else None,
                "active_buckets_count": sum(1 for c in z_series if c > 0),
            }

        return {
            "session_id": session_id,
            "duration_seconds": round(total_span, 1),
            "bucket_seconds": bucket_seconds,
            "total_buckets": len(timeline_data),
            "timeline": timeline_data,
            "peaks": peaks,
            "valleys": lull_runs,
            "rhythm_summary": {
                "classification": classification,
                "description": desc,
                "coefficient_of_variation": round(cv, 2),
                "avg_cadence_seconds": avg_cadence,
                "max_peak_count": max_peak,
                "longest_lull_seconds": round(longest_lull, 1),
                "movement_ratio_percent": mov_pct,
                "stopped_ratio_percent": stp_pct,
                "unique_persons_count": len(all_unique_persons),
            },
            "zone_rhythms": zone_rhythms,
        }

    def get_session_crowd_events(
        self,
        session_id: str,
        cluster_radius: float = 0.16,
        min_cluster_size: int = 3
    ) -> Dict[str, Any]:
        """
        Phase 7: Detección de aglomeraciones y alertas espaciales.
        Agrupamiento por proximidad euclidiana (spatial clustering) y detección de
        cuellos de botella y picos de sobreocupación local.
        """
        cluster_radius = max(0.04, min(0.5, float(cluster_radius or 0.16)))
        min_cluster_size = max(2, min(20, int(min_cluster_size or 3)))

        with self.get_connection() as conn:
            session = self.get_session(session_id)
            if not session:
                return {}

            cur = conn.execute(
                """
                SELECT person_id, timestamp, x, y, speed, state, zone 
                FROM spatial_points 
                WHERE session_id = ? 
                ORDER BY timestamp ASC
                """,
                (session_id,)
            )
            rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            return {
                "session_id": session_id,
                "duration_seconds": 0,
                "cluster_radius": cluster_radius,
                "min_cluster_size": min_cluster_size,
                "total_events": 0,
                "total_crowded_seconds": 0.0,
                "crowd_time_percent": 0.0,
                "max_cluster_size": 0,
                "events": [],
                "hotspots": [],
            }

        start_t = rows[0]["timestamp"]
        end_t = rows[-1]["timestamp"]
        total_duration = max(1.0, end_t - start_t)

        # Slice points by 1-second intervals
        slices: Dict[int, Dict[int, Dict[str, Any]]] = {}
        for r in rows:
            sec = int(r["timestamp"] - start_t)
            pid = r["person_id"]
            if sec not in slices:
                slices[sec] = {}
            slices[sec][pid] = r

        # Detect spatial clusters per second
        raw_second_clusters = []
        for sec in sorted(slices.keys()):
            persons_in_sec = list(slices[sec].values())
            n_p = len(persons_in_sec)
            if n_p < min_cluster_size:
                continue

            # Graph adjacency by Euclidean distance
            adj = {i: [] for i in range(n_p)}
            for i in range(n_p):
                for j in range(i + 1, n_p):
                    dx = persons_in_sec[i]["x"] - persons_in_sec[j]["x"]
                    dy = persons_in_sec[i]["y"] - persons_in_sec[j]["y"]
                    dist = math.sqrt(dx * dx + dy * dy)
                    if dist <= cluster_radius:
                        adj[i].append(j)
                        adj[j].append(i)

            visited = set()
            for i in range(n_p):
                if i not in visited:
                    # BFS component
                    comp = []
                    q = [i]
                    visited.add(i)
                    while q:
                        curr = q.pop(0)
                        comp.append(curr)
                        for neighbor in adj[curr]:
                            if neighbor not in visited:
                                visited.add(neighbor)
                                q.append(neighbor)

                    if len(comp) >= min_cluster_size:
                        members = [persons_in_sec[idx] for idx in comp]
                        cx = sum(m["x"] for m in members) / len(members)
                        cy = sum(m["y"] for m in members) / len(members)
                        zones = [m.get("zone") for m in members if m.get("zone")]
                        dominant_zone = max(set(zones), key=zones.count) if zones else None

                        raw_second_clusters.append({
                            "sec": sec,
                            "size": len(members),
                            "cx": round(cx, 3),
                            "cy": round(cy, 3),
                            "dominant_zone": dominant_zone,
                            "person_ids": [m["person_id"] for m in members]
                        })

        # Merge adjacent seconds into continuous Crowd Events
        events = []
        if raw_second_clusters:
            current_event_secs = [raw_second_clusters[0]]
            for c in raw_second_clusters[1:]:
                last_c = current_event_secs[-1]
                # If gap is <= 2 seconds and centroids are within reasonable distance
                dx = c["cx"] - last_c["cx"]
                dy = c["cy"] - last_c["cy"]
                dist = math.sqrt(dx * dx + dy * dy)
                if (c["sec"] - last_c["sec"]) <= 2 and dist <= (cluster_radius * 1.5):
                    current_event_secs.append(c)
                else:
                    events.append(current_event_secs)
                    current_event_secs = [c]
            if current_event_secs:
                events.append(current_event_secs)

        formatted_events = []
        total_crowd_seconds = 0.0
        max_size_seen = 0
        hotspots_dict = {}

        for ev in events:
            start_sec = ev[0]["sec"]
            end_sec = ev[-1]["sec"]
            dur = max(1.0, float(end_sec - start_sec + 1))
            total_crowd_seconds += dur

            peak_size = max(c["size"] for c in ev)
            max_size_seen = max(max_size_seen, peak_size)

            avg_cx = sum(c["cx"] for c in ev) / len(ev)
            avg_cy = sum(c["cy"] for c in ev) / len(ev)

            # Zone majority
            ev_zones = [c["dominant_zone"] for c in ev if c["dominant_zone"]]
            dom_z = max(set(ev_zones), key=ev_zones.count) if ev_zones else None

            # Severity
            if peak_size >= 6:
                severity = "Crítica"
                color = "#ff453a"
            elif peak_size >= 4:
                severity = "Alta"
                color = "#ff9f0a"
            else:
                severity = "Moderada"
                color = "#ffd60a"

            # Hotspot grouping
            hs_key = f"{round(avg_cx, 1)}_{round(avg_cy, 1)}"
            if hs_key not in hotspots_dict:
                hotspots_dict[hs_key] = {
                    "cx": round(avg_cx, 3),
                    "cy": round(avg_cy, 3),
                    "zone": dom_z,
                    "event_count": 0,
                    "total_duration": 0.0
                }
            hotspots_dict[hs_key]["event_count"] += 1
            hotspots_dict[hs_key]["total_duration"] += dur

            formatted_events.append({
                "id": f"crowd_{start_sec}_{end_sec}",
                "start_time": start_sec,
                "end_time": end_sec,
                "duration_seconds": round(dur, 1),
                "start_time_label": f"{int(start_sec // 60):02d}:{int(start_sec % 60):02d}",
                "end_time_label": f"{int(end_sec // 60):02d}:{int(end_sec % 60):02d}",
                "peak_cluster_size": peak_size,
                "centroid_x": round(avg_cx, 3),
                "centroid_y": round(avg_cy, 3),
                "dominant_zone": dom_z,
                "severity": severity,
                "severity_color": color,
            })

        hotspots = sorted(
            hotspots_dict.values(),
            key=lambda item: item["total_duration"],
            reverse=True
        )[:5]

        crowd_pct = round((total_crowd_seconds / total_duration) * 100, 1)

        return {
            "session_id": session_id,
            "duration_seconds": round(total_duration, 1),
            "cluster_radius": cluster_radius,
            "min_cluster_size": min_cluster_size,
            "total_events": len(formatted_events),
            "total_crowded_seconds": round(total_crowd_seconds, 1),
            "crowd_time_percent": crowd_pct,
            "max_cluster_size": max_size_seen,
            "events": formatted_events,
            "hotspots": hotspots,
        }

    def compare_sessions(self, session_ids: List[str]) -> Dict[str, Any]:
        """
        Phase 8: Comparativa entre múltiples sesiones de observación (franjas/días).
        """
        if not session_ids:
            return {"sessions": [], "comparison": {}}

        results = []
        for sid in session_ids:
            s = self.get_session(sid)
            if not s:
                continue
            rhythms = self.get_session_rhythms(sid, bucket_seconds=15)
            zones = self.get_session_zone_metrics(sid)

            results.append({
                "session": s,
                "rhythms": rhythms.get("rhythm_summary", {}),
                "zones_summary": zones.get("zones", []),
                "timeline_sample": rhythms.get("timeline", [])[:10],
            })

        if not results:
            return {"sessions": [], "comparison": {}}

        # Comparative KPIs
        highest_volume = max(results, key=lambda item: (item["session"].get("total_persons") or 0))
        highest_concurrent = max(results, key=lambda item: (item["session"].get("max_concurrent") or 0))
        longest_dur = max(results, key=lambda item: (item["session"].get("duration_seconds") or 0.0))

        return {
            "sessions_count": len(results),
            "sessions": results,
            "summary_highlights": {
                "highest_volume_session": highest_volume["session"].get("name") or highest_volume["session"].get("id", "Sesión"),
                "highest_volume_count": highest_volume["session"].get("total_persons") or 0,
                "highest_concurrent_session": highest_concurrent["session"].get("name") or highest_concurrent["session"].get("id", "Sesión"),
                "highest_concurrent_count": highest_concurrent["session"].get("max_concurrent") or 0,
                "longest_session": longest_dur["session"].get("name") or longest_dur["session"].get("id", "Sesión"),
                "longest_duration": round(longest_dur["session"].get("duration_seconds") or 0.0, 1),
            }
        }

    def get_time_slots_analytics(self) -> Dict[str, Any]:
        """
        Phase 8: Agrupación histórica por franjas horarias (Madrugada, Mañana, Tarde, Noche)
        y días de la semana a partir de todas las sesiones registradas.
        """
        with self.get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, name, started_at, duration_seconds, total_persons, max_concurrent, avg_fps, created_at
                FROM sessions
                WHERE status = 'completed' AND started_at IS NOT NULL
                ORDER BY started_at DESC
                """
            )
            rows = [dict(r) for r in cur.fetchall()]

        slots = {
            "morning": {"label": "Mañana (06:00 - 12:00)", "sessions_count": 0, "total_persons": 0, "avg_concurrent": 0.0, "sessions": []},
            "afternoon": {"label": "Tarde (12:00 - 18:00)", "sessions_count": 0, "total_persons": 0, "avg_concurrent": 0.0, "sessions": []},
            "evening": {"label": "Noche (18:00 - 24:00)", "sessions_count": 0, "total_persons": 0, "avg_concurrent": 0.0, "sessions": []},
            "night": {"label": "Madrugada (00:00 - 06:00)", "sessions_count": 0, "total_persons": 0, "avg_concurrent": 0.0, "sessions": []},
        }

        days = {
            0: {"day": "Lunes", "sessions_count": 0, "total_persons": 0},
            1: {"day": "Martes", "sessions_count": 0, "total_persons": 0},
            2: {"day": "Miércoles", "sessions_count": 0, "total_persons": 0},
            3: {"day": "Jueves", "sessions_count": 0, "total_persons": 0},
            4: {"day": "Viernes", "sessions_count": 0, "total_persons": 0},
            5: {"day": "Sábado", "sessions_count": 0, "total_persons": 0},
            6: {"day": "Domingo", "sessions_count": 0, "total_persons": 0},
        }

        import datetime

        for r in rows:
            st = r["started_at"]
            dt = datetime.datetime.fromtimestamp(st)
            hour = dt.hour
            weekday = dt.weekday()

            if 6 <= hour < 12:
                slot_key = "morning"
            elif 12 <= hour < 18:
                slot_key = "afternoon"
            elif 18 <= hour < 24:
                slot_key = "evening"
            else:
                slot_key = "night"

            slots[slot_key]["sessions_count"] += 1
            slots[slot_key]["total_persons"] += (r.get("total_persons") or 0)
            slots[slot_key]["avg_concurrent"] += (r.get("max_concurrent") or 0)
            slots[slot_key]["sessions"].append(r.get("name") or r.get("id"))

            days[weekday]["sessions_count"] += 1
            days[weekday]["total_persons"] += (r.get("total_persons") or 0)

        for k in slots.keys():
            sc = slots[k]["sessions_count"]
            if sc > 0:
                slots[k]["avg_concurrent"] = round(slots[k]["avg_concurrent"] / sc, 1)

        return {
            "total_analyzed_sessions": len(rows),
            "slots": slots,
            "days_of_week": list(days.values())
        }

    def get_session_interactions(
        self,
        session_id: str,
        distance_threshold: float = 0.12,
        min_interaction_seconds: float = 3.0
    ) -> Dict[str, Any]:
        """
        Phase 9: Detección de interacciones interpersonales y proximidad social.
        Identifica pares de individuos en interacción continuada, agrupamiento y caminata conjunta.
        """
        distance_threshold = max(0.04, min(0.35, float(distance_threshold or 0.12)))
        min_interaction_seconds = max(1.0, min(60.0, float(min_interaction_seconds or 3.0)))

        with self.get_connection() as conn:
            session = self.get_session(session_id)
            if not session:
                return {}

            cur = conn.execute(
                """
                SELECT person_id, timestamp, x, y, speed, state, zone 
                FROM spatial_points 
                WHERE session_id = ? 
                ORDER BY timestamp ASC
                """,
                (session_id,)
            )
            rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            return {
                "session_id": session_id,
                "total_interactions": 0,
                "unique_interacting_persons": 0,
                "social_ratio_percent": 0.0,
                "avg_interaction_duration": 0.0,
                "interactions": [],
            }

        start_t = rows[0]["timestamp"]
        end_t = rows[-1]["timestamp"]
        total_span = max(1.0, end_t - start_t)

        all_persons = set(r["person_id"] for r in rows)

        # Bin points by 1-second intervals
        slices: Dict[int, Dict[int, Dict[str, Any]]] = {}
        for r in rows:
            sec = int(r["timestamp"] - start_t)
            pid = r["person_id"]
            if sec not in slices:
                slices[sec] = {}
            slices[sec][pid] = r

        # Pair proximity occurrences: {(p1, p2): [sec1, sec2, ...]}
        pair_seconds: Dict[tuple, List[Dict[str, Any]]] = {}
        sorted_secs = sorted(slices.keys())

        for sec in sorted_secs:
            persons = list(slices[sec].values())
            n = len(persons)
            for i in range(n):
                for j in range(i + 1, n):
                    p1 = persons[i]
                    p2 = persons[j]
                    pid1 = min(p1["person_id"], p2["person_id"])
                    pid2 = max(p1["person_id"], p2["person_id"])
                    pair_key = (pid1, pid2)

                    dx = p1["x"] - p2["x"]
                    dy = p1["y"] - p2["y"]
                    d = math.sqrt(dx * dx + dy * dy)

                    if d <= distance_threshold:
                        if pair_key not in pair_seconds:
                            pair_seconds[pair_key] = []
                        pair_seconds[pair_key].append({
                            "sec": sec,
                            "dist": d,
                            "zone": p1.get("zone") or p2.get("zone"),
                            "state1": p1.get("state"),
                            "state2": p2.get("state"),
                        })

        # Find continuous runs >= min_interaction_seconds
        encounters = []
        interacting_pids = set()

        for (pid1, pid2), sec_list in pair_seconds.items():
            if not sec_list:
                continue

            # Group consecutive seconds with gap <= 2s
            runs = []
            curr_run = [sec_list[0]]
            for item in sec_list[1:]:
                if (item["sec"] - curr_run[-1]["sec"]) <= 2:
                    curr_run.append(item)
                else:
                    runs.append(curr_run)
                    curr_run = [item]
            if curr_run:
                runs.append(curr_run)

            for run in runs:
                dur = max(1.0, float(run[-1]["sec"] - run[0]["sec"] + 1))
                if dur >= min_interaction_seconds:
                    interacting_pids.add(pid1)
                    interacting_pids.add(pid2)

                    avg_d = sum(item["dist"] for item in run) / len(run)
                    zones = [item["zone"] for item in run if item["zone"]]
                    dom_zone = max(set(zones), key=zones.count) if zones else None

                    # Classification
                    stopped_both = sum(1 for item in run if item["state1"] == "stopped" and item["state2"] == "stopped")
                    moving_both = sum(1 for item in run if item["state1"] == "moving" and item["state2"] == "moving")

                    if stopped_both >= (len(run) * 0.5):
                        interaction_type = "Conversación Estacionaria"
                        type_badge = "☕ Conversación"
                    elif moving_both >= (len(run) * 0.5):
                        interaction_type = "Caminata Conjunta"
                        type_badge = "🚶 Caminata Conjunta"
                    else:
                        interaction_type = "Interacción Mixta"
                        type_badge = "🔄 Mixta"

                    start_sec = run[0]["sec"]
                    end_sec = run[-1]["sec"]

                    encounters.append({
                        "person_a": pid1,
                        "person_b": pid2,
                        "label": f"P{pid1:02d} ↔ P{pid2:02d}",
                        "start_time": start_sec,
                        "end_time": end_sec,
                        "duration_seconds": round(dur, 1),
                        "start_time_label": f"{int(start_sec // 60):02d}:{int(start_sec % 60):02d}",
                        "end_time_label": f"{int(end_sec // 60):02d}:{int(end_sec % 60):02d}",
                        "avg_distance": round(avg_d, 3),
                        "zone": dom_zone,
                        "interaction_type": interaction_type,
                        "type_badge": type_badge,
                    })

        encounters.sort(key=lambda item: item["duration_seconds"], reverse=True)

        avg_dur = round(sum(e["duration_seconds"] for e in encounters) / len(encounters), 1) if encounters else 0.0
        longest_dur = max([e["duration_seconds"] for e in encounters], default=0.0)
        total_p = max(1, len(all_persons))
        social_pct = round((len(interacting_pids) / total_p) * 100, 1)

        return {
            "session_id": session_id,
            "duration_seconds": round(total_span, 1),
            "distance_threshold": distance_threshold,
            "min_interaction_seconds": min_interaction_seconds,
            "total_interactions_count": len(encounters),
            "unique_interacting_persons": len(interacting_pids),
            "total_individuals_count": len(all_persons),
            "social_ratio_percent": social_pct,
            "avg_interaction_duration_seconds": avg_dur,
            "longest_interaction_seconds": round(longest_dur, 1),
            "interactions": encounters,
        }

    def export_session_tabular_data(
        self,
        session_id: str,
        sections: Optional[List[str]] = None,
        delimiter: str = ","
    ) -> str:
        """
        Phase 10: Exportación tabular de variables configurables en formato CSV/Excel
        con codificación UTF-8 BOM para apertura directa sin distorsión de caracteres.
        """
        import io
        import csv

        if sections is None:
            sections = ["summary", "zones", "rhythms", "crowds", "interactions", "peaks"]

        s = self.get_session(session_id)
        if not s:
            return ""

        output = io.StringIO()
        # Add UTF-8 BOM for Microsoft Excel compatibility
        output.write("\ufeff")
        writer = csv.writer(output, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)

        # ─── 1. Resumen General ───
        if "summary" in sections:
            writer.writerow(["# INFORME DE OBSERVACIÓN ESPACIAL — RITMOS"])
            writer.writerow(["ID de Sesión", s.get("id", "")])
            writer.writerow(["Nombre del Espacio", s.get("name", "")])
            writer.writerow(["Estado", s.get("status", "")])
            writer.writerow(["Fecha / Hora Creación", s.get("created_at", "")])
            writer.writerow(["Duración (segundos)", s.get("duration_seconds", 0)])
            writer.writerow(["Duración (minutos)", round((s.get("duration_seconds") or 0) / 60, 2)])
            writer.writerow(["Total Cuerpos Registrados", s.get("total_persons", 0)])
            writer.writerow(["Pico Concurrente Máximo", s.get("max_concurrent", 0)])
            writer.writerow(["Fotogramas Procesados", s.get("total_frames", 0)])
            writer.writerow(["FPS Promedio", s.get("avg_fps", 0)])
            writer.writerow([])

        # ─── 2. Métricas de Zonas (Fase 5) ───
        if "zones" in sections:
            zones_data = self.get_session_zone_metrics(session_id)
            zones_list = zones_data.get("zones", [])
            writer.writerow(["# MÉTRICAS POR ZONA ESPACIAL (FASE 5)"])
            writer.writerow([
                "Zona", "Color", "Total Visitas", "Personas Únicas",
                "Permanencia Total (s)", "Permanencia Media (s)", "Permanencia Mín (s)",
                "Permanencia Máx (s)", "Tasa Ocupación (%)", "Pico Simultáneo"
            ])
            for z in zones_list:
                writer.writerow([
                    z.get("zone", ""),
                    z.get("color", ""),
                    z.get("visits_count", 0),
                    z.get("unique_persons_count", 0),
                    z.get("total_dwell_seconds", 0),
                    z.get("avg_dwell_seconds", 0),
                    z.get("min_dwell_seconds", 0),
                    z.get("max_dwell_seconds", 0),
                    z.get("occupancy_rate_percent", 0),
                    z.get("peak_occupancy", 0)
                ])
            writer.writerow([])

        # ─── 3. Ritmos Temporales (Fase 6) ───
        rhythms_data = self.get_session_rhythms(session_id, bucket_seconds=5) if ("rhythms" in sections or "peaks" in sections) else {}
        if "rhythms" in sections:
            r_sum = rhythms_data.get("rhythm_summary", {})
            writer.writerow(["# RITMOS TEMPORALES Y CADENCIA DE OLEADAS (FASE 6)"])
            writer.writerow(["Clasificación de Ritmo", r_sum.get("classification", "")])
            writer.writerow(["Descripción", r_sum.get("description", "")])
            writer.writerow(["Cadencia Media entre Oleadas (s)", r_sum.get("avg_cadence_seconds", "")])
            writer.writerow(["Coeficiente de Variación (CV)", r_sum.get("coefficient_of_variation", 0)])
            writer.writerow(["Pico Máximo en Oleada", r_sum.get("max_peak_count", 0)])
            writer.writerow(["Valle de Quietud Máximo (s)", r_sum.get("longest_lull_seconds", 0)])
            writer.writerow(["Ratio Movimiento (%)", r_sum.get("movement_ratio_percent", 0)])
            writer.writerow(["Ratio Detención (%)", r_sum.get("stopped_ratio_percent", 0)])
            writer.writerow([])

        # ─── 4. Fotogramas y Picos de Afluencia ───
        if "peaks" in sections:
            peaks_list = rhythms_data.get("peaks", [])
            writer.writerow(["# REGISTRO DE PICOS DE AFLUENCIA Y FOTOGRAMAS CLAVE"])
            writer.writerow(["Marca Temporal", "Tiempo (segundos)", "Personas Simultáneas", "Zona Dominante"])
            for p in peaks_list:
                writer.writerow([
                    p.get("time_label", ""),
                    p.get("t", 0),
                    p.get("count", 0),
                    p.get("dominant_zone") or "Área General"
                ])
            writer.writerow([])

        # ─── 5. Aglomeraciones y Cuellos de Botella (Fase 7) ───
        if "crowds" in sections:
            crowd_data = self.get_session_crowd_events(session_id)
            c_events = crowd_data.get("events", [])
            c_hotspots = crowd_data.get("hotspots", [])
            writer.writerow(["# AGLOMERACIONES Y CUELLOS DE BOTELLA (FASE 7)"])
            writer.writerow(["Total Incidentes", crowd_data.get("total_events", 0)])
            writer.writerow(["Tiempo en Aglomeración (s)", crowd_data.get("total_crowded_seconds", 0)])
            writer.writerow(["Porcentaje Tiempo en Congestión (%)", crowd_data.get("crowd_time_percent", 0)])
            writer.writerow(["Pico Máximo en Racimo", crowd_data.get("max_cluster_size", 0)])
            writer.writerow([])
            writer.writerow(["-- Puntos Críticos y Hotspots Espaciales --"])
            writer.writerow(["Ranking", "Centroide X", "Centroide Y", "Zona", "Apariciones", "Duración Acumulada (s)"])
            for i, hs in enumerate(c_hotspots, 1):
                writer.writerow([
                    f"#{i}", hs.get("cx", 0), hs.get("cy", 0),
                    hs.get("zone") or "Área Abierta",
                    hs.get("event_count", 0),
                    hs.get("total_duration", 0)
                ])
            writer.writerow([])
            writer.writerow(["-- Línea de Tiempo de Aglomeraciones --"])
            writer.writerow(["ID Evento", "Inicio", "Fin", "Duración (s)", "Personas", "Severidad", "Centroide X", "Centroide Y", "Zona"])
            for ev in c_events:
                writer.writerow([
                    ev.get("id", ""),
                    ev.get("start_time_label", ""),
                    ev.get("end_time_label", ""),
                    ev.get("duration_seconds", 0),
                    ev.get("peak_cluster_size", 0),
                    ev.get("severity", ""),
                    ev.get("centroid_x", 0),
                    ev.get("centroid_y", 0),
                    ev.get("dominant_zone") or "Área General"
                ])
            writer.writerow([])

        # ─── 6. Proximidad Social e Interacciones (Fase 9) ───
        if "interactions" in sections:
            inter_data = self.get_session_interactions(session_id)
            i_list = inter_data.get("interactions", [])
            writer.writerow(["# INTERACCIONES Y PROXIMIDAD SOCIAL (FASE 9)"])
            writer.writerow(["Ratio de Sociabilidad (%)", inter_data.get("social_ratio_percent", 0)])
            writer.writerow(["Total Interacciones Registradas", inter_data.get("total_interactions_count", 0)])
            writer.writerow(["Personas en Interacción", inter_data.get("unique_interacting_persons", 0)])
            writer.writerow(["Duración Media de Interacción (s)", inter_data.get("avg_interaction_duration_seconds", 0)])
            writer.writerow(["Interacción más Larga (s)", inter_data.get("longest_interaction_seconds", 0)])
            writer.writerow([])
            writer.writerow(["-- Listado de Parejas y Grupos en Interacción --"])
            writer.writerow(["Pareja", "Tipo de Interacción", "Inicio", "Fin", "Duración (s)", "Distancia Media (m)", "Zona"])
            for it in i_list:
                writer.writerow([
                    it.get("label", ""),
                    it.get("interaction_type", ""),
                    it.get("start_time_label", ""),
                    it.get("end_time_label", ""),
                    it.get("duration_seconds", 0),
                    it.get("avg_distance", 0),
                    it.get("zone") or "Área General"
                ])
            writer.writerow([])

        return output.getvalue()

    def export_session_excel(
        self,
        session_id: str,
        sections: Optional[List[str]] = None
    ) -> bytes:
        """
        Exportación ejecutiva a Microsoft Excel (.xlsx) con múltiples hojas formateadas,
        paleta corporativa, bordes limpios, auto-ajuste de columnas y gráficos nativos.
        """
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from openpyxl.chart import BarChart, LineChart, Reference

        if sections is None:
            sections = ["summary", "zones", "rhythms", "crowds", "interactions", "peaks"]

        s = self.get_session(session_id)
        if not s:
            return b""

        wb = openpyxl.Workbook()
        # Remove default empty sheet
        wb.remove(wb.active)

        # Style Definitions
        font_title = Font(name="Segoe UI", size=14, bold=True, color="1A365D")
        font_subtitle = Font(name="Segoe UI", size=9, italic=True, color="718096")
        font_section = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        font_header = Font(name="Segoe UI", size=9.5, bold=True, color="FFFFFF")
        font_kpi_num = Font(name="Segoe UI", size=16, bold=True, color="1A365D")
        font_bold = Font(name="Segoe UI", size=9.5, bold=True, color="2D3748")
        font_normal = Font(name="Segoe UI", size=9.5, color="2D3748")
        font_mono = Font(name="Consolas", size=9, color="2D3748")

        fill_navy = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
        fill_blue = PatternFill(start_color="2B6CB0", end_color="2B6CB0", fill_type="solid")
        fill_header = PatternFill(start_color="2D3748", end_color="2D3748", fill_type="solid")
        fill_zebra = PatternFill(start_color="F7FAFC", end_color="F7FAFC", fill_type="solid")
        fill_kpi = PatternFill(start_color="EDF2F7", end_color="EDF2F7", fill_type="solid")

        thin_side = Side(style="thin", color="E2E8F0")
        border_all = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
        border_header = Border(left=thin_side, right=thin_side, top=thin_side, bottom=Side(style="medium", color="1A365D"))

        align_center = Alignment(horizontal="center", vertical="center")
        align_left = Alignment(horizontal="left", vertical="center")
        align_right = Alignment(horizontal="right", vertical="center")

        def style_header_row(ws, row_idx, col_count, fill=fill_header):
            for col in range(1, col_count + 1):
                cell = ws.cell(row=row_idx, column=col)
                cell.font = font_header
                cell.fill = fill
                cell.alignment = align_center
                cell.border = border_header

        # ─── 1. HOJA: RESUMEN GENERAL ───
        if "summary" in sections:
            ws_sum = wb.create_sheet(title="Resumen Ejecutivo")
            ws_sum.views.sheetView[0].showGridLines = True

            # Title
            ws_sum.merge_cells("A1:F1")
            ws_sum["A1"] = "RITMOS • INFORME EJECUTIVO DE OBSERVACIÓN ESPACIAL"
            ws_sum["A1"].font = font_title
            ws_sum["A1"].alignment = align_left

            ws_sum.merge_cells("A2:F2")
            ws_sum["A2"] = f"Generado automáticamente para investigación urbana y concurrencia espacial • ID: {s.get('id', '')}"
            ws_sum["A2"].font = font_subtitle
            ws_sum["A2"].alignment = align_left

            # Metadata Table
            headers_meta = ["Parámetro", "Valor Registrado"]
            ws_sum.cell(row=4, column=1, value=headers_meta[0])
            ws_sum.cell(row=4, column=2, value=headers_meta[1])
            style_header_row(ws_sum, 4, 2, fill=fill_navy)

            meta_rows = [
                ("Nombre del Espacio", s.get("name", "Sin Nombre")),
                ("ID de Sesión", s.get("id", "")),
                ("Fecha / Hora de Inicio", s.get("created_at", "")),
                ("Estado de Sesión", s.get("status", "Completada")),
                ("Duración Total (segundos)", f"{s.get('duration_seconds', 0)} s"),
                ("Duración Total (minutos)", f"{round((s.get('duration_seconds') or 0) / 60, 2)} min"),
                ("Fotogramas Totales Analizados", s.get("total_frames", 0)),
                ("Rendimiento Promedio (FPS)", f"{s.get('avg_fps', 0)} fps"),
            ]
            for r_i, (k, v) in enumerate(meta_rows, start=5):
                c1 = ws_sum.cell(row=r_i, column=1, value=k)
                c2 = ws_sum.cell(row=r_i, column=2, value=v)
                c1.font = font_bold; c1.alignment = align_left; c1.border = border_all
                c2.font = font_normal; c2.alignment = align_left; c2.border = border_all
                if r_i % 2 == 0:
                    c1.fill = fill_zebra; c2.fill = fill_zebra

            # KPI Highlights Box (Right side)
            ws_sum.merge_cells("D4:F4")
            ws_sum["D4"] = "INDICADORES CLAVE (KPIS)"
            ws_sum["D4"].font = font_section
            ws_sum["D4"].fill = fill_blue
            ws_sum["D4"].alignment = align_center

            kpi_data = [
                ("Total Individuos Únicos", s.get("total_persons", 0), "personas detectadas y seguidas"),
                ("Pico Concurrente Máximo", s.get("max_concurrent", 0), "personas simultáneas en encuadre"),
            ]
            # Fetch rhythms for movement dynamics
            rhythms_data = self.get_session_rhythms(session_id, bucket_seconds=5) if ("rhythms" in sections or "peaks" in sections) else {}
            r_sum = rhythms_data.get("rhythm_summary", {})
            if r_sum:
                kpi_data.append(("Dinámica Movimiento vs Parado", f"{r_sum.get('movement_ratio_percent', 0)}% / {r_sum.get('stopped_ratio_percent', 0)}%", "actividad cinemática observada"))
                kpi_data.append(("Patrón Clasificado", r_sum.get("classification", "Estándar"), r_sum.get("description", "")))

            kpi_row = 5
            for title, val, sub in kpi_data:
                ws_sum.merge_cells(f"D{kpi_row}:F{kpi_row}")
                c_lbl = ws_sum[f"D{kpi_row}"]
                c_lbl.value = title.upper()
                c_lbl.font = Font(name="Segoe UI", size=8, bold=True, color="718096")
                c_lbl.alignment = align_left
                c_lbl.fill = fill_kpi

                ws_sum.merge_cells(f"D{kpi_row+1}:F{kpi_row+1}")
                c_val = ws_sum[f"D{kpi_row+1}"]
                c_val.value = val
                c_val.font = font_kpi_num
                c_val.alignment = align_left
                c_val.fill = fill_kpi

                ws_sum.merge_cells(f"D{kpi_row+2}:F{kpi_row+2}")
                c_sub = ws_sum[f"D{kpi_row+2}"]
                c_sub.value = sub
                c_sub.font = Font(name="Segoe UI", size=7.5, italic=True, color="718096")
                c_sub.alignment = align_left
                c_sub.fill = fill_kpi

                for r in range(kpi_row, kpi_row + 3):
                    for col_l in ["D", "E", "F"]:
                        ws_sum[f"{col_l}{r}"].border = border_all
                kpi_row += 4

        # ─── 2. HOJA: MÉTRICAS POR ZONA (FASE 5) ───
        if "zones" in sections:
            ws_zones = wb.create_sheet(title="Metricas por Zona")
            ws_zones.views.sheetView[0].showGridLines = True

            ws_zones.merge_cells("A1:H1")
            ws_zones["A1"] = "ANÁLISIS DE PERMANENCIA Y OCUPACIÓN ESPACIAL POR ZONA (FASE 5)"
            ws_zones["A1"].font = font_title
            ws_zones["A1"].alignment = align_left

            headers_zone = [
                "Zona Espacial", "Color", "Total Visitas", "Personas Únicas",
                "Permanencia Media (s)", "Permanencia Máx (s)", "Tasa Ocupación (%)", "Pico Simultáneo"
            ]
            for col_i, h in enumerate(headers_zone, start=1):
                ws_zones.cell(row=3, column=col_i, value=h)
            style_header_row(ws_zones, 3, len(headers_zone), fill=fill_navy)

            zones_data = self.get_session_zone_metrics(session_id)
            zones_list = zones_data.get("zones", [])

            for z_i, z in enumerate(zones_list, start=4):
                row_vals = [
                    z.get("zone", ""),
                    z.get("color", ""),
                    z.get("visits_count", 0),
                    z.get("unique_persons_count", 0),
                    z.get("avg_dwell_seconds", 0),
                    z.get("max_dwell_seconds", 0),
                    z.get("occupancy_rate_percent", 0),
                    z.get("peak_occupancy", 0)
                ]
                for c_i, val in enumerate(row_vals, start=1):
                    cell = ws_zones.cell(row=z_i, column=c_i, value=val)
                    cell.font = font_bold if c_i == 1 else font_normal
                    cell.alignment = align_left if c_i in (1, 2) else align_right
                    cell.border = border_all
                    if z_i % 2 == 0:
                        cell.fill = fill_zebra

            # Embedded Excel Bar Chart
            if len(zones_list) > 0:
                chart_zones = BarChart()
                chart_zones.type = "col"
                chart_zones.style = 10
                chart_zones.title = "Tasa de Ocupación (%) y Visitas por Zona"
                chart_zones.y_axis.title = "Valor"
                chart_zones.x_axis.title = "Zonas Espaciales"
                chart_zones.width = 16
                chart_zones.height = 10

                data_ref = Reference(ws_zones, min_col=7, min_row=3, max_row=3 + len(zones_list))
                cats_ref = Reference(ws_zones, min_col=1, min_row=4, max_row=3 + len(zones_list))
                chart_zones.add_data(data_ref, titles_from_data=True)
                chart_zones.set_categories(cats_ref)
                ws_zones.add_chart(chart_zones, "J3")

        # ─── 3. HOJA: RITMOS Y PICOS (FASE 6) ───
        if "rhythms" in sections or "peaks" in sections:
            ws_rhy = wb.create_sheet(title="Ritmos y Picos")
            ws_rhy.views.sheetView[0].showGridLines = True

            ws_rhy.merge_cells("A1:F1")
            ws_rhy["A1"] = "RITMOS TEMPORALES, CADENCIA DE OLEADAS Y PICOS (FASE 6)"
            ws_rhy["A1"].font = font_title
            ws_rhy["A1"].alignment = align_left

            # Classification card
            if not rhythms_data:
                rhythms_data = self.get_session_rhythms(session_id, bucket_seconds=5)
            r_sum = rhythms_data.get("rhythm_summary", {})

            ws_rhy.merge_cells("A3:D3")
            ws_rhy["A3"] = f"Clasificación: {r_sum.get('classification', 'N/A')}"
            ws_rhy["A3"].font = font_section
            ws_rhy["A3"].fill = fill_blue
            ws_rhy["A3"].alignment = align_left

            rhy_meta = [
                ("Cadencia Media entre Oleadas", f"{r_sum.get('avg_cadence_seconds', 'N/A')} s"),
                ("Coeficiente de Variación (CV)", r_sum.get('coefficient_of_variation', 0)),
                ("Pico Máximo en Oleada", f"{r_sum.get('max_peak_count', 0)} personas"),
                ("Valle de Quietud Máximo", f"{r_sum.get('longest_lull_seconds', 0)} s"),
            ]
            for idx, (label, val) in enumerate(rhy_meta, start=4):
                c1 = ws_rhy.cell(row=idx, column=1, value=label)
                c2 = ws_rhy.cell(row=idx, column=2, value=val)
                c1.font = font_bold; c1.border = border_all
                c2.font = font_normal; c2.border = border_all; c2.alignment = align_right
                if idx % 2 == 0:
                    c1.fill = fill_zebra; c2.fill = fill_zebra

            # Table of Peaks
            peaks_list = rhythms_data.get("peaks", [])
            start_peak_row = 10
            ws_rhy.cell(row=start_peak_row-1, column=1, value="Marca Temporal")
            ws_rhy.cell(row=start_peak_row-1, column=2, value="Tiempo (s)")
            ws_rhy.cell(row=start_peak_row-1, column=3, value="Concurrencia Máxima")
            ws_rhy.cell(row=start_peak_row-1, column=4, value="Zona Dominante")
            style_header_row(ws_rhy, start_peak_row-1, 4, fill=fill_navy)

            for p_i, p in enumerate(peaks_list, start=start_peak_row):
                r_vals = [
                    p.get("time_label", ""),
                    p.get("t", 0),
                    p.get("count", 0),
                    p.get("dominant_zone") or "Área General"
                ]
                for c_i, val in enumerate(r_vals, start=1):
                    cell = ws_rhy.cell(row=p_i, column=c_i, value=val)
                    cell.font = font_mono if c_i == 1 else font_normal
                    cell.alignment = align_right if c_i in (2, 3) else align_left
                    cell.border = border_all
                    if p_i % 2 == 0:
                        cell.fill = fill_zebra

            # Embedded Line Chart for Peaks
            if len(peaks_list) > 1:
                chart_peaks = LineChart()
                chart_peaks.title = "Oleadas y Picos de Concurrencia Simultánea"
                chart_peaks.style = 13
                chart_peaks.y_axis.title = "Personas Simultáneas"
                chart_peaks.x_axis.title = "Marca Temporal"
                chart_peaks.width = 16
                chart_peaks.height = 10

                data_peaks = Reference(ws_rhy, min_col=3, min_row=start_peak_row-1, max_row=start_peak_row-1 + len(peaks_list))
                cats_peaks = Reference(ws_rhy, min_col=1, min_row=start_peak_row, max_row=start_peak_row-1 + len(peaks_list))
                chart_peaks.add_data(data_peaks, titles_from_data=True)
                chart_peaks.set_categories(cats_peaks)
                ws_rhy.add_chart(chart_peaks, "F3")

        # ─── 4. HOJA: AGLOMERACIONES Y HOTSPOTS (FASE 7) ───
        if "crowds" in sections:
            ws_crw = wb.create_sheet(title="Aglomeraciones")
            ws_crw.views.sheetView[0].showGridLines = True

            ws_crw.merge_cells("A1:G1")
            ws_crw["A1"] = "DETECCIÓN DE AGLOMERACIONES Y CUELLOS DE BOTELLA (FASE 7)"
            ws_crw["A1"].font = font_title
            ws_crw["A1"].alignment = align_left

            crowd_data = self.get_session_crowd_events(session_id)
            c_hotspots = crowd_data.get("hotspots", [])
            c_events = crowd_data.get("events", [])

            # KPI Summary
            crw_stats = [
                ("Total Incidentes Detectados", crowd_data.get("total_events", 0)),
                ("Tiempo en Aglomeración", f"{crowd_data.get('total_crowded_seconds', 0)} s ({crowd_data.get('crowd_time_percent', 0)}%)"),
                ("Pico Máximo en Racimo", f"{crowd_data.get('max_cluster_size', 0)} personas"),
            ]
            for idx, (label, val) in enumerate(crw_stats, start=3):
                c1 = ws_crw.cell(row=idx, column=1, value=label)
                c2 = ws_crw.cell(row=idx, column=2, value=val)
                c1.font = font_bold; c1.border = border_all
                c2.font = font_normal; c2.border = border_all; c2.alignment = align_right
                if idx % 2 == 0:
                    c1.fill = fill_zebra; c2.fill = fill_zebra

            # Hotspots Table
            ws_crw.cell(row=7, column=1, value="Ranking")
            ws_crw.cell(row=7, column=2, value="Centroide X")
            ws_crw.cell(row=7, column=3, value="Centroide Y")
            ws_crw.cell(row=7, column=4, value="Zona Espacial")
            ws_crw.cell(row=7, column=5, value="Apariciones")
            ws_crw.cell(row=7, column=6, value="Duración Acumulada (s)")
            style_header_row(ws_crw, 7, 6, fill=fill_navy)

            for hs_i, hs in enumerate(c_hotspots, start=8):
                hs_vals = [
                    f"#{hs_i-7}", hs.get("cx", 0), hs.get("cy", 0),
                    hs.get("zone") or "Área Abierta",
                    hs.get("event_count", 0),
                    hs.get("total_duration", 0)
                ]
                for c_i, val in enumerate(hs_vals, start=1):
                    cell = ws_crw.cell(row=hs_i, column=c_i, value=val)
                    cell.font = font_normal
                    cell.alignment = align_right if c_i in (2, 3, 5, 6) else align_center
                    cell.border = border_all
                    if hs_i % 2 == 0:
                        cell.fill = fill_zebra

            # Events Timeline Table
            start_ev_row = 9 + len(c_hotspots)
            ws_crw.cell(row=start_ev_row-1, column=1, value="ID Evento")
            ws_crw.cell(row=start_ev_row-1, column=2, value="Inicio")
            ws_crw.cell(row=start_ev_row-1, column=3, value="Fin")
            ws_crw.cell(row=start_ev_row-1, column=4, value="Duración (s)")
            ws_crw.cell(row=start_ev_row-1, column=5, value="Personas")
            ws_crw.cell(row=start_ev_row-1, column=6, value="Severidad")
            ws_crw.cell(row=start_ev_row-1, column=7, value="Zona")
            style_header_row(ws_crw, start_ev_row-1, 7, fill=fill_blue)

            for ev_i, ev in enumerate(c_events, start=start_ev_row):
                ev_vals = [
                    ev.get("id", ""),
                    ev.get("start_time_label", ""),
                    ev.get("end_time_label", ""),
                    ev.get("duration_seconds", 0),
                    ev.get("peak_cluster_size", 0),
                    ev.get("severity", ""),
                    ev.get("dominant_zone") or "Área General"
                ]
                for c_i, val in enumerate(ev_vals, start=1):
                    cell = ws_crw.cell(row=ev_i, column=c_i, value=val)
                    cell.font = font_mono if c_i in (1, 2, 3) else font_normal
                    cell.alignment = align_right if c_i in (4, 5) else align_left
                    cell.border = border_all
                    if ev_i % 2 == 0:
                        cell.fill = fill_zebra

        # ─── 5. HOJA: INTERACCIONES SOCIALES (FASE 9) ───
        if "interactions" in sections:
            ws_soc = wb.create_sheet(title="Proximidad Social")
            ws_soc.views.sheetView[0].showGridLines = True

            ws_soc.merge_cells("A1:G1")
            ws_soc["A1"] = "INTERACCIONES INTERPERSONALES Y PROXIMIDAD SOCIAL (FASE 9)"
            ws_soc["A1"].font = font_title
            ws_soc["A1"].alignment = align_left

            inter_data = self.get_session_interactions(session_id)
            i_list = inter_data.get("interactions", [])

            soc_stats = [
                ("Ratio de Sociabilidad Espacial", f"{inter_data.get('social_ratio_percent', 0)} %"),
                ("Total Interacciones Registradas", inter_data.get("total_interactions_count", 0)),
                ("Personas Únicas Participantes", inter_data.get("unique_interacting_persons", 0)),
                ("Duración Media de Interacción", f"{inter_data.get('avg_interaction_duration_seconds', 0)} s"),
            ]
            for idx, (label, val) in enumerate(soc_stats, start=3):
                c1 = ws_soc.cell(row=idx, column=1, value=label)
                c2 = ws_soc.cell(row=idx, column=2, value=val)
                c1.font = font_bold; c1.border = border_all
                c2.font = font_normal; c2.border = border_all; c2.alignment = align_right
                if idx % 2 == 0:
                    c1.fill = fill_zebra; c2.fill = fill_zebra

            ws_soc.cell(row=8, column=1, value="Pareja")
            ws_soc.cell(row=8, column=2, value="Tipo de Interacción")
            ws_soc.cell(row=8, column=3, value="Inicio")
            ws_soc.cell(row=8, column=4, value="Fin")
            ws_soc.cell(row=8, column=5, value="Duración (s)")
            ws_soc.cell(row=8, column=6, value="Distancia Media (m)")
            ws_soc.cell(row=8, column=7, value="Zona")
            style_header_row(ws_soc, 8, 7, fill=fill_navy)

            for it_i, it in enumerate(i_list, start=9):
                it_vals = [
                    it.get("label", ""),
                    it.get("interaction_type", ""),
                    it.get("start_time_label", ""),
                    it.get("end_time_label", ""),
                    it.get("duration_seconds", 0),
                    it.get("avg_distance", 0),
                    it.get("zone") or "Área General"
                ]
                for c_i, val in enumerate(it_vals, start=1):
                    cell = ws_soc.cell(row=it_i, column=c_i, value=val)
                    cell.font = font_mono if c_i in (1, 3, 4) else font_normal
                    cell.alignment = align_right if c_i in (5, 6) else align_left
                    cell.border = border_all
                    if it_i % 2 == 0:
                        cell.fill = fill_zebra

        # ─── AUTO-FIT COLUMN WIDTHS FOR ALL SHEETS ───
        for ws in wb.worksheets:
            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    if cell.value:
                        # Avoid calculating width from chart or large title banners
                        val_str = str(cell.value)
                        if "\n" not in val_str and len(val_str) < 60:
                            max_len = max(max_len, len(val_str))
                ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 40)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # ─── SIMPLE TABULAR REPORT & EXPORT ────────────────────────
    def get_simple_session_report(self, session_id: str) -> Dict[str, Any]:
        """
        Generate a clear, simple tabular report of the session and all person trajectories.
        """
        s = self.get_session(session_id)
        if not s:
            return {}

        with self.get_connection() as conn:
            cur = conn.execute(
                """
                SELECT person_id, x, y, timestamp, state, speed
                FROM spatial_points
                WHERE session_id = ?
                ORDER BY person_id, timestamp ASC
                """,
                (session_id,)
            )
            rows = [dict(r) for r in cur.fetchall()]

        from collections import defaultdict
        import math

        grouped = defaultdict(list)
        total_mov = 0
        total_stop = 0

        for r in rows:
            grouped[r["person_id"]].append(r)
            if r.get("state") == "moving":
                total_mov += 1
            else:
                total_stop += 1

        total_pts = len(rows)
        mov_ratio = round((total_mov / total_pts * 100), 1) if total_pts > 0 else 0
        stop_ratio = round((total_stop / total_pts * 100), 1) if total_pts > 0 else 0

        persons = []
        for pid, pts in grouped.items():
            t_start = pts[0]["timestamp"]
            t_end = pts[-1]["timestamp"]
            dur = max(0.5, round(t_end - t_start, 1))

            # Approximate Euclidean distance scaled to realistic space (~16m scene width)
            norm_dist = sum(
                math.hypot(pts[i]["x"] - pts[i - 1]["x"], pts[i]["y"] - pts[i - 1]["y"])
                for i in range(1, len(pts))
            )
            dist_m = round(norm_dist * 16.0, 1)
            avg_spd = round(dist_m / dur, 2)
            mov_cnt = sum(1 for p in pts if p.get("state") == "moving")
            dom_state = "En Movimiento" if mov_cnt >= len(pts) * 0.4 else "Estático / Sedente"

            persons.append({
                "person_id": pid,
                "label": f"P{pid:02d}",
                "duration_seconds": dur,
                "distance_meters": dist_m,
                "avg_speed_ms": avg_spd,
                "dominant_state": dom_state,
                "points_count": len(pts),
                "start_coords": (round(pts[0]["x"], 2), round(pts[0]["y"], 2)),
                "end_coords": (round(pts[-1]["x"], 2), round(pts[-1]["y"], 2)),
            })

        # Sort persons by points count descending
        persons.sort(key=lambda p: p["points_count"], reverse=True)

        return {
            "session": s,
            "summary": {
                "id": s.get("id"),
                "name": s.get("name", "Observación"),
                "created_at": s.get("created_at"),
                "started_at": s.get("started_at"),
                "duration_seconds": s.get("duration_seconds", 0),
                "duration_minutes": round((s.get("duration_seconds") or 0) / 60, 2),
                "total_persons": len(persons),
                "max_concurrent": s.get("max_concurrent", 0),
                "total_points": total_pts,
                "movement_ratio_percent": mov_ratio,
                "stopped_ratio_percent": stop_ratio,
                "weather": s.get("weather_condition", "N/A"),
                "timeslot": s.get("time_slot", "N/A"),
            },
            "persons": persons
        }

    def export_simple_session_csv(self, session_id: str, delimiter: str = ",") -> str:
        """Export simple, clear tabular report as CSV with UTF-8 BOM."""
        report = self.get_simple_session_report(session_id)
        if not report:
            return ""

        import io
        import csv

        out = io.StringIO()
        out.write("\ufeff")  # UTF-8 BOM for Excel
        writer = csv.writer(out, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)

        s = report["summary"]
        writer.writerow(["# RESUMEN GENERAL DE OBSERVACIÓN — CARTOGRAFÍA"])
        writer.writerow(["Espacio Observado", s["name"]])
        writer.writerow(["ID de Sesión", s["id"]])
        writer.writerow(["Fecha y Hora", s.get("created_at") or ""])
        writer.writerow(["Duración (minutos)", s["duration_minutes"]])
        writer.writerow(["Duración (segundos)", s["duration_seconds"]])
        writer.writerow(["Total Personas Registradas", s["total_persons"]])
        writer.writerow(["Pico Máximo Simultáneo", s["max_concurrent"]])
        writer.writerow(["Total Coordenadas Registradas", s["total_points"]])
        writer.writerow(["Dinámica Espacial", f"{s['movement_ratio_percent']}% Movimiento / {s['stopped_ratio_percent']}% Estático"])
        writer.writerow([])

        writer.writerow(["# REGISTRO DETALLADO DE RECORRIDOS POR PERSONA"])
        writer.writerow([
            "ID Persona",
            "Tiempo en Escena (s)",
            "Distancia Recorrida (m)",
            "Velocidad Media (m/s)",
            "Estado Predominante",
            "Puntos Mapeados",
            "Coordenada Inicio (X)",
            "Coordenada Inicio (Y)",
            "Coordenada Fin (X)",
            "Coordenada Fin (Y)"
        ])

        for p in report["persons"]:
            writer.writerow([
                p["label"],
                p["duration_seconds"],
                p["distance_meters"],
                p["avg_speed_ms"],
                p["dominant_state"],
                p["points_count"],
                p["start_coords"][0],
                p["start_coords"][1],
                p["end_coords"][0],
                p["end_coords"][1]
            ])

        return out.getvalue()

    def export_simple_session_excel(self, session_id: str) -> bytes:
        """Export simple, clean Excel workbook (.xlsx)."""
        report = self.get_simple_session_report(session_id)
        if not report:
            return b""

        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        import io

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Resumen de Observación"

        title_font = Font(name="Calibri", size=14, bold=True, color="1C1C1E")
        header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="0071E3", end_color="0071E3", fill_type="solid")
        section_font = Font(name="Calibri", size=11, bold=True, color="0071E3")
        meta_label_font = Font(name="Calibri", size=10, bold=True, color="444444")
        data_font = Font(name="Calibri", size=10)
        thin_border = Border(
            left=Side(style='thin', color="E0E0E0"),
            right=Side(style='thin', color="E0E0E0"),
            top=Side(style='thin', color="E0E0E0"),
            bottom=Side(style='thin', color="E0E0E0")
        )

        s = report["summary"]
        ws.cell(row=1, column=1, value="INFORME DE OBSERVACIÓN Y RECORRIDOS").font = title_font
        ws.cell(row=2, column=1, value=f"Espacio: {s['name']}  |  Fecha: {s.get('created_at') or ''}  |  ID: {s['id']}").font = data_font

        # Tabla 1: Resumen General
        ws.cell(row=4, column=1, value="Métrica de Sesión").font = header_font
        ws.cell(row=4, column=1).fill = header_fill
        ws.cell(row=4, column=2, value="Valor").font = header_font
        ws.cell(row=4, column=2).fill = header_fill

        metrics_data = [
            ("Espacio Observado", s["name"]),
            ("Fecha y Hora", str(s.get("created_at") or "")),
            ("Duración Total", f"{s['duration_minutes']} min ({s['duration_seconds']} s)"),
            ("Total Personas Registradas", f"{s['total_persons']} personas"),
            ("Pico Máximo Simultáneo", f"{s['max_concurrent']} personas"),
            ("Total Coordenadas Registradas", f"{s['total_points']} puntos"),
            ("Dinámica de Movimiento", f"{s['movement_ratio_percent']}% Movimiento / {s['stopped_ratio_percent']}% Estático"),
        ]

        row_idx = 5
        for lbl, val in metrics_data:
            c1 = ws.cell(row=row_idx, column=1, value=lbl)
            c2 = ws.cell(row=row_idx, column=2, value=val)
            c1.font = meta_label_font
            c2.font = data_font
            c1.border = thin_border
            c2.border = thin_border
            row_idx += 1

        row_idx += 2
        # Tabla 2: Detalle de Personas
        ws.cell(row=row_idx, column=1, value="REGISTRO DETALLADO DE RECORRIDOS POR PERSONA").font = section_font
        row_idx += 1

        headers = [
            "ID Persona", "Tiempo en Escena (s)", "Distancia (m)",
            "Velocidad (m/s)", "Estado Predominante", "Puntos Coordenada",
            "Inicio (X, Y)", "Fin (X, Y)"
        ]
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        row_idx += 1
        for p in report["persons"]:
            row_vals = [
                p["label"],
                p["duration_seconds"],
                p["distance_meters"],
                p["avg_speed_ms"],
                p["dominant_state"],
                p["points_count"],
                f"{p['start_coords'][0]}, {p['start_coords'][1]}",
                f"{p['end_coords'][0]}, {p['end_coords'][1]}",
            ]
            for col_idx, v in enumerate(row_vals, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=v)
                cell.font = data_font
                cell.border = thin_border
                if col_idx in (2, 3, 4, 6):
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (1, 5):
                    cell.alignment = Alignment(horizontal="center")
            row_idx += 1

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 14)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()



# Global database singleton
db = Database()


