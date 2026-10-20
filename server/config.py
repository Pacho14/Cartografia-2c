"""
Spatial Rhythm Observer — Configuration
Central configuration for the server.
"""

import os
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
CLIENT_DIR = BASE_DIR.parent / "client"
STORAGE_DIR = BASE_DIR / "storage"
VIDEOS_DIR = STORAGE_DIR / "videos"
MODELS_DIR = BASE_DIR / "models_cache"

# Create directories
STORAGE_DIR.mkdir(exist_ok=True)
VIDEOS_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# ─── YOLO Configuration ─────────────────────────────────
# Model variant: "yolo11n.pt" (fast, less accurate) or "yolo11s.pt" (balanced)
YOLO_MODEL = os.getenv("YOLO_MODEL", "yolo11n.pt")

# Minimum confidence threshold for detections (0.22 for enhanced capture)
YOLO_CONFIDENCE = float(os.getenv("YOLO_CONFIDENCE", "0.22"))

# Inference resolution: 384 gives ~45ms inference on CPU (vs 200ms at 640)
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "384"))

# Classes to detect (COCO class IDs)
# 0=person, 1=bicycle, 13=bench, 14=bird, 15=cat, 16=dog,
# 24=backpack, 25=umbrella, 56=chair, 60=dining table
DETECT_CLASSES = [0]  # Phase 1: persons only

# Tracker: "bytetrack.yaml" (static camera) or "botsort.yaml" (moving camera)
TRACKER_CONFIG = os.getenv("TRACKER_CONFIG", "bytetrack.yaml")

# ─── Processing Configuration ───────────────────────────
# Target analysis FPS (frames the server will process per second)
DEFAULT_ANALYSIS_FPS = int(os.getenv("DEFAULT_ANALYSIS_FPS", "15"))

# Speed threshold (normalized units/frame) below which a person is "stopped"
STOP_SPEED_THRESHOLD = float(os.getenv("STOP_SPEED_THRESHOLD", "0.005"))

# How many frames a person can be missing before considered "exited"
TRACK_DISAPPEAR_FRAMES = int(os.getenv("TRACK_DISAPPEAR_FRAMES", "12"))

# ─── Server Configuration ───────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

# ─── WebSocket Configuration ────────────────────────────
# Maximum frame size in bytes (5 MB)
WS_MAX_SIZE = int(os.getenv("WS_MAX_SIZE", str(5 * 1024 * 1024)))
