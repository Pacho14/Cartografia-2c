/**
 * Ritmos — Interactive Timeline Player (Phase 4: Historical Motion & Heatmap Replay)
 * Controls second-by-second scrubbing, play/pause, step forward/backward,
 * synchronized video playback, parameter layer toggles, and clean/cinema mode.
 */

class TimelinePlayer {
    constructor(options = {}) {
        this.heatmap = options.heatmap || null;
        this.overlay = options.overlay || null;
        this.videoEl = options.videoElement || document.getElementById('replay-video');
        this.onTimeUpdate = options.onTimeUpdate || null;
        this.onStateChange = options.onStateChange || null;

        // Session data
        this.session = null;
        this.allPoints = [];
        this.startedAt = 0;
        this.endedAt = 0;
        this.duration = 0;

        // Playback state
        this.currentTime = 0; // seconds (0 to duration)
        this.isPlaying = false;
        this.playbackSpeed = 1.0;
        this.mode = 'cumulative'; // 'cumulative' (0 to t) | 'window' (last 15s)
        this.windowSeconds = 15;
        this.hasVideo = false;
        this.isCleanMode = false;

        // Layer visibility states (controlled live without resetting playback)
        this.layers = {
            heatmap: true,
            trajectories: true,
            zones: true,
            labels: true,
            grid: false,
        };

        this._lastFrameTime = null;
        this._animId = null;

        this._bindVideoEvents();
    }

    _bindVideoEvents() {
        if (!this.videoEl) return;

        this.videoEl.addEventListener('timeupdate', () => {
            if (this.hasVideo && this.isPlaying) {
                this.currentTime = Math.min(this.duration, this.videoEl.currentTime);
                this.sync(false);
            }
        });

        this.videoEl.addEventListener('ended', () => {
            this.pause();
            this.seekTo(this.duration);
        });

        this.videoEl.addEventListener('error', (e) => {
            console.warn('[Timeline] Video not available for this session, using simulated clock.', e);
            this.hasVideo = false;
            this.videoEl.classList.add('hidden');
        });
    }

    /**
     * Load historical session data and prepare timeline + video replay
     */
    async loadSession(session, points) {
        this.pause();
        this.session = session || {};

        // Sort points chronologically
        const rawPts = (points || []).slice();
        rawPts.sort((a, b) => a.timestamp - b.timestamp);
        this.allPoints = rawPts;

        if (this.allPoints.length > 0) {
            this.startedAt = this.allPoints[0].timestamp;
            this.endedAt = this.allPoints[this.allPoints.length - 1].timestamp;
            this.duration = Math.max(1, this.endedAt - this.startedAt);
        } else {
            this.startedAt = this.session.started_at || (Date.now() / 1000);
            this.endedAt = this.session.ended_at || this.startedAt;
            this.duration = Math.max(1, this.session.duration_seconds || 1);
        }

        // Setup session video element
        this.hasVideo = false;
        if (this.videoEl && this.session.id) {
            this.videoEl.pause();
            this.videoEl.removeAttribute('src');
            this.videoEl.load();

            // Set video source
            const videoUrl = `/api/sessions/${this.session.id}/video`;
            this.videoEl.src = videoUrl;
            this.videoEl.playbackRate = this.playbackSpeed;

            try {
                // Test if video is playable
                await new Promise((resolve, reject) => {
                    const onLoaded = () => {
                        this.videoEl.removeEventListener('loadedmetadata', onLoaded);
                        this.videoEl.removeEventListener('error', onError);
                        this.hasVideo = true;
                        this.videoEl.classList.remove('hidden');
                        if (this.videoEl.duration && !isNaN(this.videoEl.duration) && this.videoEl.duration > 0) {
                            this.duration = Math.max(this.duration, this.videoEl.duration);
                        }
                        resolve(true);
                    };
                    const onError = (err) => {
                        this.videoEl.removeEventListener('loadedmetadata', onLoaded);
                        this.videoEl.removeEventListener('error', onError);
                        this.hasVideo = false;
                        this.videoEl.classList.add('hidden');
                        resolve(false);
                    };
                    this.videoEl.addEventListener('loadedmetadata', onLoaded);
                    this.videoEl.addEventListener('error', onError);
                    // Timeout fallback in case video metadata does not load
                    setTimeout(() => resolve(false), 1500);
                });
            } catch (err) {
                this.hasVideo = false;
                this.videoEl.classList.add('hidden');
            }
        }

        // Set heatmap mode to presence for video overlay
        if (this.heatmap) {
            this.heatmap.setMode('presence');
        }
        this.layers.heatmap = true;
        this.layers.trajectories = true;
        this.layers.zones = false;

        // Apply layer visual preferences
        this.applyLayerStates();

        // Start at beginning or end
        this.currentTime = 0;
        this.seekTo(0);

        if (this.onStateChange) {
            this.onStateChange({
                session: this.session,
                duration: this.duration,
                totalPoints: this.allPoints.length,
                hasVideo: this.hasVideo,
            });
        }
    }

    play() {
        if (this.currentTime >= this.duration) {
            this.seekTo(0);
        }
        this.isPlaying = true;
        this._lastFrameTime = performance.now();

        if (this.hasVideo && this.videoEl) {
            this.videoEl.playbackRate = this.playbackSpeed;
            this.videoEl.play().catch(e => console.warn('[Timeline] Video play auto-play warning:', e));
        }

        this._loop();
        if (this.onStateChange) this.onStateChange({ isPlaying: true });
    }

    pause() {
        this.isPlaying = false;
        if (this._animId) {
            cancelAnimationFrame(this._animId);
            this._animId = null;
        }
        if (this.hasVideo && this.videoEl) {
            this.videoEl.pause();
        }
        if (this.onStateChange) this.onStateChange({ isPlaying: false });
    }

    togglePlay() {
        if (this.isPlaying) {
            this.pause();
        } else {
            this.play();
        }
    }

    restart() {
        this.pause();
        this.seekTo(0);
    }

    step(deltaSeconds) {
        this.pause();
        this.seekTo(this.currentTime + deltaSeconds);
    }

    seekTo(seconds) {
        this.currentTime = Math.max(0, Math.min(this.duration, seconds));
        if (this.hasVideo && this.videoEl) {
            this.videoEl.currentTime = this.currentTime;
        }
        this.sync();
    }

    setPlaybackSpeed(speed) {
        this.playbackSpeed = parseFloat(speed) || 1.0;
        if (this.hasVideo && this.videoEl) {
            this.videoEl.playbackRate = this.playbackSpeed;
        }
    }

    setMode(mode) {
        this.mode = mode || 'cumulative';
        this.sync();
    }

    // ─── Layer Parameter Controls ───────────────────────

    toggleLayer(layerName) {
        if (this.layers[layerName] === undefined) return;
        this.layers[layerName] = !this.layers[layerName];
        this.applyLayerStates();
        return this.layers[layerName];
    }

    setLayer(layerName, enabled) {
        if (this.layers[layerName] === undefined) return;
        this.layers[layerName] = !!enabled;
        this.applyLayerStates();
    }

    applyLayerStates() {
        // 1. Heatmap layer
        if (this.heatmap && this.heatmap.canvas) {
            this.heatmap.canvas.style.display = this.layers.heatmap ? 'block' : 'none';
        }

        // 2. Trajectories, Zones, Labels, Grid in CanvasOverlay
        if (this.overlay) {
            this.overlay.setTrailsVisible(this.layers.trajectories);
            this.overlay.setZonesVisible(this.layers.zones);
            this.overlay.setLabelsVisible(this.layers.labels);
            this.overlay.setGrid(this.layers.grid);
        }

        // Redraw current frame
        this.sync();
    }

    // ─── Clean / Cinema Mode ────────────────────────────

    toggleCleanMode(force) {
        this.isCleanMode = force !== undefined ? !!force : !this.isCleanMode;
        const timelinePlayerBar = document.getElementById('timeline-player-bar');
        const heatmapBar = document.getElementById('heatmap-floating-bar');
        const restoreBtn = document.getElementById('btn-timeline-restore-controls');

        if (this.isCleanMode) {
            if (timelinePlayerBar) timelinePlayerBar.classList.add('hidden');
            if (heatmapBar) heatmapBar.classList.add('hidden');
            if (restoreBtn) restoreBtn.classList.remove('hidden');
        } else {
            if (timelinePlayerBar) timelinePlayerBar.classList.remove('hidden');
            if (restoreBtn) restoreBtn.classList.add('hidden');
        }
        return this.isCleanMode;
    }

    _loop() {
        if (!this.isPlaying) return;

        // If video is not driving playback, advance with timer
        if (!this.hasVideo) {
            const now = performance.now();
            const dt = (now - this._lastFrameTime) / 1000;
            this._lastFrameTime = now;

            this.currentTime += dt * this.playbackSpeed;

            if (this.currentTime >= this.duration) {
                this.currentTime = this.duration;
                this.sync();
                this.pause();
                return;
            }

            this.sync();
        }

        this._animId = requestAnimationFrame(() => this._loop());
    }

    /**
     * Synchronize Heatmap, Trajectories, and Zones to current instant
     */
    sync(triggerVideo = true) {
        if (triggerVideo && this.hasVideo && this.videoEl && Math.abs(this.videoEl.currentTime - this.currentTime) > 0.4) {
            this.videoEl.currentTime = this.currentTime;
        }

        const absT = this.startedAt + this.currentTime;
        let filtered = [];

        if (this.mode === 'window') {
            const startWindow = absT - this.windowSeconds;
            filtered = this.allPoints.filter(p => p.timestamp >= startWindow && p.timestamp <= absT);
        } else {
            // Cumulative: all points up to current time
            filtered = this.allPoints.filter(p => p.timestamp <= absT);
        }

        // 1. Update Heatmap (if enabled)
        if (this.heatmap && this.layers.heatmap) {
            this.heatmap.loadSessionPoints(filtered);
        }

        // 2. Compute Instantaneous Active Occupants & Zone Headcounts (window of last 3 seconds)
        const recentWindow = 3.0;
        const recentPts = this.allPoints.filter(p => p.timestamp >= absT - recentWindow && p.timestamp <= absT);

        // Group by person to keep only the latest coordinate for each person
        const latestByPerson = {};
        for (const p of recentPts) {
            const pid = p.person_id || p.id;
            latestByPerson[pid] = {
                id: pid,
                label: `P${pid < 10 ? '0' : ''}${pid}`,
                x: p.x,
                y: p.y,
                center_x: p.x,
                center_y: p.y - 0.08,
                speed: p.speed,
                direction: p.direction,
                state: p.state,
                zone: p.zone,
                bbox: [p.x - 0.03, p.y - 0.16, p.x + 0.03, p.y]
            };
        }

        const activePersonsList = Object.values(latestByPerson);

        // Calculate zone counts
        const zoneCounts = {};
        for (const ap of activePersonsList) {
            if (ap.zone) {
                zoneCounts[ap.zone] = (zoneCounts[ap.zone] || 0) + 1;
            }
        }

        // 3. Update Canvas Overlay with active persons and zone overrides
        if (this.overlay) {
            this.overlay.setOccupancyOverrides(zoneCounts);
            this.overlay.update(activePersonsList);
        }

        // 4. Callback to update UI
        if (this.onTimeUpdate) {
            this.onTimeUpdate({
                currentTime: this.currentTime,
                duration: this.duration,
                isPlaying: this.isPlaying,
                pointsCount: filtered.length,
                activePersonsCount: activePersonsList.length,
                zoneCounts: zoneCounts,
                hasVideo: this.hasVideo,
            });
        }
    }

    close() {
        this.pause();
        if (this.videoEl) {
            this.videoEl.pause();
            this.videoEl.removeAttribute('src');
            this.videoEl.load();
            this.videoEl.classList.add('hidden');
        }
        this.toggleCleanMode(false);
        this.allPoints = [];
        this.session = null;
        if (this.overlay) {
            this.overlay.setOccupancyOverrides(null);
            this.overlay.setTrailsVisible(true);
            this.overlay.setZonesVisible(true);
            this.overlay.setLabelsVisible(true);
            this.overlay.clear();
        }
        if (this.heatmap) {
            if (this.heatmap.canvas) this.heatmap.canvas.style.display = 'block';
            this.heatmap.clear();
        }
    }
}

window.TimelinePlayer = TimelinePlayer;
