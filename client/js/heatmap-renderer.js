/**
 * Ritmos — Heatmap & Trajectories Renderer (Phase 4)
 * High-performance HTML5 Canvas engine for:
 * 1. Cumulative Presence Density Heatmaps
 * 2. Cumulative Dwell / Stoppage Heatmaps
 * 3. Flow & Movement Corridor Heatmaps
 * 4. Reconstructed Vector Trajectories with Directional Arrows
 * Designed with Apple iOS / Puppertino dark aesthetics and GPU-accelerated rasterization.
 */

class HeatmapRenderer {
    constructor(canvasId, cameraManager) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
        this.camera = cameraManager;

        // Current active mode: 'off' | 'presence' | 'dwell' | 'flow' | 'trajectories'
        this.mode = 'off';

        // Rendering parameters (subdued opacity so background scene is clearly visible)
        this.opacity = 0.42;
        this.radius = 28; // Radius of each point in pixels
        this.blur = 18;

        // Filters
        this.selectedPersonId = null; // null = all
        this.timeWindowSeconds = 0;   // 0 = all time, >0 = last N seconds

        // Points storage: Array of { x, y, state, person_id, timestamp, speed, direction, zone }
        this.points = [];
        this.maxPoints = 60000;

        // Offscreen canvas for fast alpha/density accumulation
        this.offscreen = document.createElement('canvas');
        this.offCtx = this.offscreen.getContext('2d', { willReadFrequently: true });

        // Pre-computed color palettes (256-color LUTs)
        this.palettes = {
            presence: this._createPalette([
                { stop: 0.0, color: 'rgba(0, 0, 0, 0)' },
                { stop: 0.15, color: 'rgba(10, 132, 255, 0.4)' },  // iOS Blue
                { stop: 0.35, color: 'rgba(100, 210, 255, 0.7)' }, // Cyan
                { stop: 0.55, color: 'rgba(48, 209, 88, 0.85)' },  // iOS Green
                { stop: 0.75, color: 'rgba(255, 214, 10, 0.95)' }, // iOS Yellow
                { stop: 0.90, color: 'rgba(255, 159, 10, 1.0)' },  // iOS Orange
                { stop: 1.0, color: 'rgba(255, 69, 58, 1.0)' }     // iOS Red
            ]),
            dwell: this._createPalette([
                { stop: 0.0, color: 'rgba(0, 0, 0, 0)' },
                { stop: 0.20, color: 'rgba(94, 92, 230, 0.45)' }, // Indigo
                { stop: 0.45, color: 'rgba(191, 90, 242, 0.75)' }, // Purple
                { stop: 0.70, color: 'rgba(255, 55, 95, 0.9)' },  // Hot Pink
                { stop: 0.88, color: 'rgba(255, 69, 58, 1.0)' },  // Red
                { stop: 1.0, color: 'rgba(255, 214, 10, 1.0)' }   // Hot Core Yellow
            ]),
            flow: this._createPalette([
                { stop: 0.0, color: 'rgba(0, 0, 0, 0)' },
                { stop: 0.20, color: 'rgba(0, 150, 190, 0.45)' }, // Dark Teal
                { stop: 0.40, color: 'rgba(100, 210, 255, 0.75)' }, // Electric Cyan
                { stop: 0.65, color: 'rgba(48, 209, 88, 0.85)' },  // Mint Green
                { stop: 0.85, color: 'rgba(52, 199, 89, 0.95)' },  // Spring
                { stop: 1.0, color: 'rgba(255, 214, 10, 1.0)' }   // Neon Gold
            ])
        };

        // Apple iOS palette for trajectories
        this.personColors = [
            '#0a84ff', '#30d158', '#ffd60a', '#ff9f0a',
            '#bf5af2', '#64d2ff', '#ff375f', '#5e5ce6',
            '#34c759', '#40c8e0', '#ff6482', '#ffb340'
        ];

        this._setupResizeObserver();
    }

    _setupResizeObserver() {
        if (!this.canvas || !window.ResizeObserver) return;
        const observer = new ResizeObserver(() => {
            this._syncDimensions();
            if (this.mode !== 'off') this.render();
        });
        observer.observe(this.canvas.parentElement);
    }

    _syncDimensions() {
        const container = this.canvas.parentElement;
        if (!container) return;
        const w = container.clientWidth;
        const h = container.clientHeight;
        if (this.canvas.width !== w || this.canvas.height !== h) {
            this.canvas.width = w;
            this.canvas.height = h;
            this.offscreen.width = w;
            this.offscreen.height = h;
        }
    }

    _createPalette(stops) {
        const pCanvas = document.createElement('canvas');
        pCanvas.width = 256;
        pCanvas.height = 1;
        const pCtx = pCanvas.getContext('2d');
        const grad = pCtx.createLinearGradient(0, 0, 256, 0);
        for (const s of stops) {
            grad.addColorStop(s.stop, s.color);
        }
        pCtx.fillStyle = grad;
        pCtx.fillRect(0, 0, 256, 1);
        return pCtx.getImageData(0, 0, 256, 1).data;
    }

    /**
     * Set heatmap mode: 'off' | 'presence' | 'dwell' | 'flow' | 'trajectories'
     */
    setMode(mode) {
        this.mode = mode || 'off';
        if (this.mode === 'off') {
            this.clear();
        } else {
            this.render();
        }
    }

    setOpacity(val) {
        this.opacity = Math.max(0.1, Math.min(1.0, parseFloat(val) || 0.75));
        if (this.mode !== 'off') this.render();
    }

    setRadius(val) {
        this.radius = Math.max(8, Math.min(80, parseInt(val, 10) || 28));
        if (this.mode !== 'off') this.render();
    }

    setPersonFilter(personId) {
        this.selectedPersonId = (personId !== null && personId !== undefined && personId !== '' && personId !== 'all') 
            ? parseInt(personId, 10) : null;
        if (this.mode !== 'off') this.render();
    }

    setTimeWindow(seconds) {
        this.timeWindowSeconds = parseFloat(seconds) || 0;
        if (this.mode !== 'off') this.render();
    }

    /**
     * Add live points from detection frame
     */
    addLivePoints(persons) {
        if (!persons || persons.length === 0) return;
        const now = Date.now() / 1000;
        for (const p of persons) {
            this.points.push({
                x: p.x, // Normalized (0-1)
                y: p.y,
                state: p.state || 'stopped',
                person_id: p.id,
                timestamp: now,
                speed: p.speed || 0,
                direction: p.direction || 0,
                zone: p.zone || null
            });
        }
        if (this.points.length > this.maxPoints) {
            this.points.splice(0, this.points.length - this.maxPoints);
        }
        if (this.mode !== 'off') {
            this.render();
        }
    }

    /**
     * Load historical session points
     */
    loadSessionPoints(points) {
        this.points = (points || []).map(p => ({
            x: p.x,
            y: p.y,
            state: p.state || 'stopped',
            person_id: p.person_id || p.id,
            timestamp: p.timestamp,
            speed: p.speed || 0,
            direction: p.direction || 0,
            zone: p.zone || null
        }));
        if (this.mode !== 'off') {
            this.render();
        }
    }

    clear() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.offCtx.clearRect(0, 0, this.offscreen.width, this.offscreen.height);
    }

    resetPoints() {
        this.points = [];
        this.clear();
    }

    getPointsCount() {
        return this.points.length;
    }

    getUniquePersons() {
        const set = new Set();
        for (const p of this.points) {
            if (p.person_id !== undefined && p.person_id !== null) {
                set.add(p.person_id);
            }
        }
        return Array.from(set).sort((a, b) => a - b);
    }

    /**
     * Filter points according to current active filters
     */
    _getFilteredPoints() {
        if (this.points.length === 0) return [];
        let pts = this.points;

        // Filter by state if in dwell or flow mode
        if (this.mode === 'dwell') {
            pts = pts.filter(p => p.state === 'stopped');
        } else if (this.mode === 'flow') {
            pts = pts.filter(p => p.state === 'moving');
        }

        // Filter by person
        if (this.selectedPersonId !== null) {
            pts = pts.filter(p => p.person_id === this.selectedPersonId);
        }

        // Filter by time window
        if (this.timeWindowSeconds > 0) {
            const now = Date.now() / 1000;
            const threshold = now - this.timeWindowSeconds;
            pts = pts.filter(p => p.timestamp >= threshold);
        }

        return pts;
    }

    /**
     * Main Render Dispatcher
     */
    render() {
        this._syncDimensions();
        this.clear();
        if (this.mode === 'off') return;

        const dims = this.camera.getVideoDimensions();
        if (!dims.renderWidth || !dims.renderHeight) return;

        if (this.mode === 'trajectories') {
            this._renderTrajectories(dims);
        } else {
            this._renderDensityHeatmap(dims);
        }
    }

    /**
     * Render Density Heatmap using Fast Offscreen Grayscale + 256-LUT Color Mapping
     */
    _renderDensityHeatmap(dims) {
        const pts = this._getFilteredPoints();
        if (pts.length === 0) return;

        const w = this.offscreen.width;
        const h = this.offscreen.height;
        this.offCtx.clearRect(0, 0, w, h);

        const r = this.radius;
        // Step 1: Draw radial falloff alpha circles onto offscreen canvas
        // Intensity scaling adapts based on point sample density (calibrated for high translucency)
        const baseAlpha = Math.max(0.025, Math.min(0.18, 1.8 / Math.sqrt(Math.max(10, pts.length))));

        for (let i = 0; i < pts.length; i++) {
            const p = pts[i];
            const px = dims.offsetX + p.x * dims.renderWidth;
            const py = dims.offsetY + p.y * dims.renderHeight;

            const radGrad = this.offCtx.createRadialGradient(px, py, 0, px, py, r);
            radGrad.addColorStop(0, `rgba(0, 0, 0, ${baseAlpha})`);
            radGrad.addColorStop(0.45, `rgba(0, 0, 0, ${baseAlpha * 0.4})`);
            radGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');

            this.offCtx.fillStyle = radGrad;
            this.offCtx.beginPath();
            this.offCtx.arc(px, py, r, 0, Math.PI * 2);
            this.offCtx.fill();
        }

        // Step 2: Read alpha values and colorize with selected palette
        const imgData = this.offCtx.getImageData(0, 0, w, h);
        const data = imgData.data;
        const palette = this.palettes[this.mode] || this.palettes.presence;
        const len = data.length;

        for (let i = 3; i < len; i += 4) {
            const alpha = data[i];
            if (alpha > 0) {
                const lutIdx = alpha * 4;
                data[i - 3] = palette[lutIdx];     // R
                data[i - 2] = palette[lutIdx + 1]; // G
                data[i - 1] = palette[lutIdx + 2]; // B
                // Smooth translucent non-blocking alpha:
                // Allows seeing scene elements behind the heat cloud while preserving contrast
                const normAlpha = alpha / 255.0;
                const curve = Math.sin(normAlpha * Math.PI * 0.5);
                data[i] = Math.round(palette[lutIdx + 3] * curve * this.opacity * 210); // Alpha
            }
        }

        this.ctx.putImageData(imgData, 0, 0);

        // Step 3: Draw subtle glassmorphic scale legend in corner
        this._renderHeatmapLegend();
    }

    /**
     * Render Reconstructed Trajectories with directional arrows and nodes
     */
    _renderTrajectories(dims) {
        const pts = this._getFilteredPoints();
        if (pts.length === 0) return;

        // Group points by person
        const byPerson = {};
        for (const p of pts) {
            const pid = p.person_id;
            if (!byPerson[pid]) byPerson[pid] = [];
            byPerson[pid].push(p);
        }

        this.ctx.save();
        this.ctx.globalAlpha = Math.min(0.75, this.opacity * 1.35);

        for (const [pidStr, personPts] of Object.entries(byPerson)) {
            const pid = parseInt(pidStr, 10);
            if (personPts.length < 2) continue;

            const color = this.personColors[(pid - 1) % this.personColors.length];

            // 1. Draw glowing polyline
            this.ctx.beginPath();
            const firstScreen = {
                x: dims.offsetX + personPts[0].x * dims.renderWidth,
                y: dims.offsetY + personPts[0].y * dims.renderHeight
            };
            this.ctx.moveTo(firstScreen.x, firstScreen.y);

            const screenPts = [firstScreen];
            for (let i = 1; i < personPts.length; i++) {
                const sp = {
                    x: dims.offsetX + personPts[i].x * dims.renderWidth,
                    y: dims.offsetY + personPts[i].y * dims.renderHeight
                };
                this.ctx.lineTo(sp.x, sp.y);
                screenPts.push(sp);
            }

            // Trajectory path line
            this.ctx.strokeStyle = color;
            this.ctx.lineWidth = 2;
            this.ctx.lineCap = 'round';
            this.ctx.lineJoin = 'round';
            this.ctx.stroke();

            // 2. Draw directional arrows along the path
            const arrowSpacing = 50; // pixels between arrows
            let distAcc = 0;
            for (let i = 1; i < screenPts.length; i++) {
                const p1 = screenPts[i - 1];
                const p2 = screenPts[i];
                const dx = p2.x - p1.x;
                const dy = p2.y - p1.y;
                const segDist = Math.sqrt(dx * dx + dy * dy);

                distAcc += segDist;
                if (distAcc >= arrowSpacing && segDist > 4) {
                    distAcc = 0;
                    const angle = Math.atan2(dy, dx);
                    this._drawDirectionArrow((p1.x + p2.x) / 2, (p1.y + p2.y) / 2, angle, color);
                }
            }

            // 3. Draw Start Node (Green Apple Circle)
            this._drawTrajectoryNode(firstScreen.x, firstScreen.y, '#30d158', `P${pid < 10 ? '0' : ''}${pid} Inicio`);

            // 4. Draw End/Current Node (Hot Red / Apple Pill)
            const lastScreen = screenPts[screenPts.length - 1];
            this._drawTrajectoryNode(lastScreen.x, lastScreen.y, color, `P${pid < 10 ? '0' : ''}${pid} Fin`);
        }

        this.ctx.restore();
    }

    _drawDirectionArrow(x, y, angle, color) {
        const size = 6;
        this.ctx.save();
        this.ctx.translate(x, y);
        this.ctx.rotate(angle);
        this.ctx.fillStyle = '#ffffff';
        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = 1.5;
        this.ctx.beginPath();
        this.ctx.moveTo(size * 1.2, 0);
        this.ctx.lineTo(-size, -size * 0.8);
        this.ctx.lineTo(-size * 0.4, 0);
        this.ctx.lineTo(-size, size * 0.8);
        this.ctx.closePath();
        this.ctx.fill();
        this.ctx.stroke();
        this.ctx.restore();
    }

    _drawTrajectoryNode(x, y, color, label) {
        this.ctx.save();
        // Outer halo
        this.ctx.fillStyle = color;
        this.ctx.beginPath();
        this.ctx.arc(x, y, 6, 0, Math.PI * 2);
        this.ctx.fill();

        this.ctx.fillStyle = '#ffffff';
        this.ctx.beginPath();
        this.ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        this.ctx.fill();

        // Label pill
        this.ctx.font = '600 9px -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif';
        const txtWidth = this.ctx.measureText(label).width;
        const padX = 6;
        const padY = 3;
        const pillW = txtWidth + padX * 2;
        const pillH = 15;
        const pillX = x - pillW / 2;
        const pillY = y - 20;

        this.ctx.fillStyle = 'rgba(28, 28, 30, 0.88)';
        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = 1;
        this._drawRoundedRect(pillX, pillY, pillW, pillH, 7);
        this.ctx.fill();
        this.ctx.stroke();

        this.ctx.fillStyle = '#ffffff';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText(label, x, pillY + pillH / 2);
        this.ctx.restore();
    }

    _drawRoundedRect(x, y, w, h, r) {
        this.ctx.beginPath();
        this.ctx.moveTo(x + r, y);
        this.ctx.lineTo(x + w - r, y);
        this.ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        this.ctx.lineTo(x + w, y + h - r);
        this.ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        this.ctx.lineTo(x + r, y + h);
        this.ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        this.ctx.lineTo(x, y + r);
        this.ctx.quadraticCurveTo(x, y, x + r, y);
        this.ctx.closePath();
    }

    _renderHeatmapLegend() {
        const x = this.canvas.width - 150;
        const y = this.canvas.height - 38;
        const w = 135;
        const h = 26;
        if (x < 10 || y < 10) return;

        this.ctx.save();
        // Glassmorphic background
        this.ctx.fillStyle = 'rgba(28, 28, 30, 0.78)';
        this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
        this.ctx.lineWidth = 0.5;
        this._drawRoundedRect(x, y, w, h, 8);
        this.ctx.fill();
        this.ctx.stroke();

        // Gradient bar
        const barX = x + 8;
        const barY = y + 7;
        const barW = 75;
        const barH = 10;
        const barGrad = this.ctx.createLinearGradient(barX, 0, barX + barW, 0);

        if (this.mode === 'dwell') {
            barGrad.addColorStop(0, '#5e5ce6');
            barGrad.addColorStop(0.5, '#bf5af2');
            barGrad.addColorStop(1, '#ffd60a');
        } else if (this.mode === 'flow') {
            barGrad.addColorStop(0, '#0096be');
            barGrad.addColorStop(0.5, '#64d2ff');
            barGrad.addColorStop(1, '#ffd60a');
        } else {
            barGrad.addColorStop(0, '#0a84ff');
            barGrad.addColorStop(0.5, '#30d158');
            barGrad.addColorStop(1, '#ff453a');
        }

        this.ctx.fillStyle = barGrad;
        this._drawRoundedRect(barX, barY, barW, barH, 4);
        this.ctx.fill();

        // Label
        this.ctx.fillStyle = 'rgba(235, 235, 245, 0.8)';
        this.ctx.font = '600 9px -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif';
        this.ctx.textAlign = 'left';
        this.ctx.textBaseline = 'middle';
        const labelText = this.mode === 'dwell' ? 'Detención' : (this.mode === 'flow' ? 'Flujos' : 'Densidad');
        this.ctx.fillText(labelText, barX + barW + 6, barY + barH / 2);
        this.ctx.restore();
    }

    /**
     * Export the current view (video + heatmap overlay) as a PNG snapshot
     */
    exportSnapshot() {
        const outCanvas = document.createElement('canvas');
        outCanvas.width = this.canvas.width;
        outCanvas.height = this.canvas.height;
        const outCtx = outCanvas.getContext('2d');

        // Draw video frame if accessible
        const video = this.camera ? this.camera.video : document.getElementById('camera-video');
        if (video && video.readyState >= 2) {
            const dims = this.camera.getVideoDimensions();
            try {
                outCtx.drawImage(video, dims.offsetX, dims.offsetY, dims.renderWidth, dims.renderHeight);
            } catch (e) {
                outCtx.fillStyle = '#1c1c1e';
                outCtx.fillRect(0, 0, outCanvas.width, outCanvas.height);
            }
        } else {
            outCtx.fillStyle = '#1c1c1e';
            outCtx.fillRect(0, 0, outCanvas.width, outCanvas.height);
        }

        // Draw heatmap
        outCtx.drawImage(this.canvas, 0, 0);

        // Download
        const link = document.createElement('a');
        link.download = `ritmos_heatmap_${this.mode}_${Date.now()}.png`;
        link.href = outCanvas.toDataURL('image/png');
        link.click();
    }
}
