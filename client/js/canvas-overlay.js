/**
 * Ritmos — Canvas Overlay Module (Phase 3: Spatial Zones & Interactive Drawing)
 * Renders detection results, tracking trails, and interactive spatial zones
 * on top of the camera video feed with an Apple iOS / Puppertino design system.
 */

function hexToRgba(hex, alpha) {
    if (!hex || typeof hex !== 'string' || hex[0] !== '#') return `rgba(10, 132, 255, ${alpha})`;
    let c = hex.substring(1);
    if (c.length === 3) c = c.split('').map(x => x + x).join('');
    const num = parseInt(c, 16);
    return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
}

function pointInPolygon(x, y, polygon) {
    if (!polygon || polygon.length < 3) return false;
    let inside = false;
    const n = polygon.length;
    let p1 = polygon[0];
    for (let i = 1; i <= n; i++) {
        const p2 = polygon[i % n];
        if (y > Math.min(p1.y, p2.y)) {
            if (y <= Math.max(p1.y, p2.y)) {
                if (x <= Math.max(p1.x, p2.x)) {
                    if (p1.y !== p2.y) {
                        const xinters = (y - p1.y) * (p2.x - p1.x) / (p2.y - p1.y) + p1.x;
                        if (p1.x === p2.x || x <= xinters) {
                            inside = !inside;
                        }
                    }
                }
            }
        }
        p1 = p2;
    }
    return inside;
}

class CanvasOverlay {
    constructor(canvasId, cameraManager) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.camera = cameraManager;

        // Visual settings
        this.showBoundingBoxes = true;
        this.showLabels = true;
        this.showCoordinates = true;
        this.showTrails = true;
        this.showGrid = false;
        this.showZones = false;
        this.trailLength = 45;

        // Apple iOS dark color palette
        this.personColors = [
            '#0a84ff', '#30d158', '#ffd60a', '#ff9f0a',
            '#bf5af2', '#64d2ff', '#ff375f', '#5e5ce6',
            '#34c759', '#40c8e0', '#ff6482', '#ffb340'
        ];

        // Spatial Zones (Phase 3)
        this.zones = [];
        this.isDrawingZone = false;
        this.drawingPoints = []; // [{x, y}, ...] in normalized coords
        this.drawingColor = '#0a84ff';
        this.hoverPoint = null;
        this.onPointAdded = null;

        // Trail history: { personId: [{x, y, timestamp}, ...] }
        this.trails = {};
        this.lastPersons = [];
        this._radarAngle = 0;

        this._setupResizeObserver();
        this._setupDrawingEvents();
    }

    /**
     * Update the overlay with new detection results.
     */
    update(persons) {
        this.lastPersons = persons || [];
        const now = Date.now();

        // Automatic client-side zone tagging
        for (const person of this.lastPersons) {
            if (!person.zone && this.zones.length > 0) {
                for (const z of this.zones) {
                    if (pointInPolygon(person.x, person.y, z.polygon)) {
                        person.zone = z.name;
                        person.zone_color = z.color;
                        person.zone_id = z.id;
                        break;
                    }
                }
            }

            // Update trails
            if (!this.trails[person.id]) {
                this.trails[person.id] = [];
            }
            this.trails[person.id].push({
                x: person.x, // Feet coordinate (normalized)
                y: person.y,
                center_x: person.center_x,
                center_y: person.center_y,
                t: now,
            });
            if (this.trails[person.id].length > this.trailLength) {
                this.trails[person.id].shift();
            }
        }

        // Clean trails immediately for people who left (eliminates ghost lag on screen)
        const activeIds = new Set(this.lastPersons.map(p => p.id));
        for (const id of Object.keys(this.trails)) {
            if (!activeIds.has(parseInt(id))) {
                delete this.trails[id];
            }
        }

        this._render();
    }

    clear() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.trails = {};
        this.lastPersons = [];
    }

    getPersonColor(personId) {
        return this.personColors[(personId - 1) % this.personColors.length];
    }

    setGrid(enabled) {
        this.showGrid = !!enabled;
        this._render();
    }

    toggleGrid() {
        this.showGrid = !this.showGrid;
        this._render();
        return this.showGrid;
    }

    setZonesVisible(enabled) {
        this.showZones = !!enabled;
        this._render();
    }

    setTrailsVisible(enabled) {
        this.showTrails = !!enabled;
        this._render();
    }

    setLabelsVisible(enabled) {
        this.showLabels = !!enabled;
        this.showCoordinates = !!enabled;
        this._render();
    }

    // ─── Spatial Zones Management (Phase 3) ──────────────

    setZones(zones) {
        this.zones = zones || [];
        this._render();
    }

    setOccupancyOverrides(counts) {
        this.zoneOccupanciesOverride = counts || null;
        this._render();
    }

    startDrawingZone(color) {
        this.isDrawingZone = true;
        this.drawingPoints = [];
        this.drawingColor = color || '#0a84ff';
        this.hoverPoint = null;
        // Make canvas interactable
        this.canvas.classList.add('drawing-active');
        this.canvas.style.pointerEvents = 'auto';
        this.canvas.style.cursor = 'crosshair';
        this._render();
    }

    addDrawingPoint(normX, normY) {
        if (!this.isDrawingZone) return;
        this.drawingPoints.push({
            x: Math.max(0, Math.min(1, normX)),
            y: Math.max(0, Math.min(1, normY)),
        });
        this._render();
        return this.drawingPoints.length;
    }

    undoDrawingPoint() {
        if (this.drawingPoints.length > 0) {
            this.drawingPoints.pop();
            this._render();
        }
        return this.drawingPoints.length;
    }

    cancelDrawingZone() {
        this.isDrawingZone = false;
        this.drawingPoints = [];
        this.hoverPoint = null;
        this.canvas.classList.remove('drawing-active');
        this.canvas.style.pointerEvents = 'none';
        this.canvas.style.cursor = 'default';
        this._render();
    }

    finishDrawingZone() {
        const points = [...this.drawingPoints];
        this.cancelDrawingZone();
        return points;
    }

    convertEventCoordsToNormalized(e) {
        const rect = this.canvas.getBoundingClientRect();
        const clientX = e.clientX !== undefined ? e.clientX : (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
        const clientY = e.clientY !== undefined ? e.clientY : (e.touches && e.touches[0] ? e.touches[0].clientY : 0);

        const canvasX = clientX - rect.left;
        const canvasY = clientY - rect.top;

        const dims = this.camera.getVideoDimensions();
        if (!dims.renderWidth || !dims.renderHeight) {
            return { x: canvasX / rect.width, y: canvasY / rect.height };
        }

        const normX = (canvasX - dims.offsetX) / dims.renderWidth;
        const normY = (canvasY - dims.offsetY) / dims.renderHeight;

        return {
            x: Math.max(0, Math.min(1, normX)),
            y: Math.max(0, Math.min(1, normY)),
        };
    }

    // ─── Private Rendering Methods ──────────────────────

    _render() {
        const dims = this.camera.getVideoDimensions();
        if (!dims.renderWidth) return;

        const container = this.canvas.parentElement;
        if (this.canvas.width !== container.clientWidth ||
            this.canvas.height !== container.clientHeight) {
            this.canvas.width = container.clientWidth;
            this.canvas.height = container.clientHeight;
        }

        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // 1. Draw Spatial Coordinate Grid
        if (this.showGrid) {
            this._renderGrid(dims);
        }

        // 2. Draw Spatial Zones (Phase 3)
        if (this.showZones) {
            this._renderZones(dims);
        }

        // 3. Draw Active Zone Drawing Preview
        if (this.isDrawingZone) {
            this._renderDrawingPreview(dims);
        }

        // 4. Draw Trails
        if (this.showTrails) {
            this._renderTrails(dims);
        }

        // 5. Draw Persons & Auto Labels
        for (const person of this.lastPersons) {
            this._renderPerson(person, dims);
        }
    }

    _renderZones(dims) {
        const { offsetX, offsetY, renderWidth, renderHeight } = dims;

        for (const zone of this.zones) {
            const poly = zone.polygon;
            if (!poly || poly.length < 3) continue;

            const color = zone.color || '#0a84ff';

            this.ctx.save();
            this.ctx.beginPath();

            let sumX = 0;
            let sumY = 0;

            for (let i = 0; i < poly.length; i++) {
                const px = offsetX + poly[i].x * renderWidth;
                const py = offsetY + poly[i].y * renderHeight;
                sumX += px;
                sumY += py;

                if (i === 0) {
                    this.ctx.moveTo(px, py);
                } else {
                    this.ctx.lineTo(px, py);
                }
            }
            this.ctx.closePath();

            // Calculate headcount for this zone
            const count = this.zoneOccupanciesOverride 
                ? (this.zoneOccupanciesOverride[zone.name] || 0)
                : (this.lastPersons ? this.lastPersons.filter(p => p.zone === zone.name).length : 0);

            // Subdued, highly translucent tint: 0.045 when empty, 0.11 when occupied
            // Ensures scene behind the zone remains fully visible without visual occlusion
            const fillAlpha = count > 0 ? 0.11 : 0.045;
            this.ctx.fillStyle = hexToRgba(color, fillAlpha);
            this.ctx.fill();

            // Crisp Apple Border: subtle when empty, slightly more emphasized when occupied
            this.ctx.strokeStyle = hexToRgba(color, count > 0 ? 0.75 : 0.45);
            this.ctx.lineWidth = count > 0 ? 1.6 : 1.2;
            this.ctx.stroke();

            // Vertex dots (subtle Apple points)
            for (let i = 0; i < poly.length; i++) {
                const px = offsetX + poly[i].x * renderWidth;
                const py = offsetY + poly[i].y * renderHeight;
                this.ctx.beginPath();
                this.ctx.arc(px, py, 3, 0, Math.PI * 2);
                this.ctx.fillStyle = '#ffffff';
                this.ctx.fill();
                this.ctx.strokeStyle = color;
                this.ctx.lineWidth = 1.5;
                this.ctx.stroke();
            }

            // Zone Name & Headcount Badge at centroid
            const centroidX = sumX / poly.length;
            const centroidY = sumY / poly.length;

            const labelText = `${zone.name} • ${count} ${count === 1 ? 'cuerpo' : 'cuerpos'}`;
            this.ctx.font = '600 10.5px -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif';
            const badgeW = this.ctx.measureText(labelText).width + 16;
            const badgeH = 22;

            // Pill squircle - translucent frosted Apple glass
            this.ctx.fillStyle = count > 0 ? 'rgba(28, 28, 30, 0.85)' : 'rgba(28, 28, 30, 0.72)';
            this.ctx.strokeStyle = hexToRgba(color, count > 0 ? 0.65 : 0.38);
            this.ctx.lineWidth = 1;
            this.ctx.beginPath();
            this.ctx.roundRect(centroidX - badgeW / 2, centroidY - badgeH / 2, badgeW, badgeH, 11);
            this.ctx.fill();
            this.ctx.stroke();

            // Label text
            this.ctx.fillStyle = count > 0 ? '#ffffff' : 'rgba(235, 235, 245, 0.82)';
            this.ctx.textAlign = 'center';
            this.ctx.textBaseline = 'middle';
            this.ctx.fillText(labelText, centroidX, centroidY);

            this.ctx.restore();
        }
    }

    _renderDrawingPreview(dims) {
        const { offsetX, offsetY, renderWidth, renderHeight } = dims;

        this.ctx.save();
        this.ctx.strokeStyle = this.drawingColor;
        this.ctx.lineWidth = 2.5;
        this.ctx.setLineDash([6, 4]);

        if (this.drawingPoints.length > 0) {
            this.ctx.beginPath();
            for (let i = 0; i < this.drawingPoints.length; i++) {
                const px = offsetX + this.drawingPoints[i].x * renderWidth;
                const py = offsetY + this.drawingPoints[i].y * renderHeight;
                if (i === 0) this.ctx.moveTo(px, py);
                else this.ctx.lineTo(px, py);
            }

            // Line to current hover / touch cursor
            if (this.hoverPoint) {
                const hx = offsetX + this.hoverPoint.x * renderWidth;
                const hy = offsetY + this.hoverPoint.y * renderHeight;
                this.ctx.lineTo(hx, hy);
            }
            this.ctx.stroke();

            // Solid vertices markers
            this.ctx.setLineDash([]);
            for (let i = 0; i < this.drawingPoints.length; i++) {
                const px = offsetX + this.drawingPoints[i].x * renderWidth;
                const py = offsetY + this.drawingPoints[i].y * renderHeight;

                this.ctx.beginPath();
                this.ctx.arc(px, py, 7, 0, Math.PI * 2);
                this.ctx.fillStyle = this.drawingColor;
                this.ctx.fill();
                this.ctx.strokeStyle = '#ffffff';
                this.ctx.lineWidth = 2;
                this.ctx.stroke();

                // Index number
                this.ctx.font = '700 10px "SF Mono", monospace';
                this.ctx.fillStyle = '#ffffff';
                this.ctx.textAlign = 'center';
                this.ctx.textBaseline = 'middle';
                this.ctx.fillText(String(i + 1), px, py);
            }
        }

        // Floating cursor pointer
        if (this.hoverPoint) {
            const hx = offsetX + this.hoverPoint.x * renderWidth;
            const hy = offsetY + this.hoverPoint.y * renderHeight;
            this.ctx.beginPath();
            this.ctx.arc(hx, hy, 5, 0, Math.PI * 2);
            this.ctx.fillStyle = '#ffffff';
            this.ctx.fill();
        }

        this.ctx.restore();
    }

    _renderGrid(dims) {
        const { offsetX, offsetY, renderWidth, renderHeight } = dims;
        this.ctx.save();
        this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
        this.ctx.lineWidth = 1;
        this.ctx.setLineDash([4, 6]);

        const steps = 5;
        this.ctx.font = "9px 'SF Mono', monospace";
        this.ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';

        // Vertical lines
        for (let i = 1; i < steps; i++) {
            const frac = i / steps;
            const x = offsetX + frac * renderWidth;
            this.ctx.beginPath();
            this.ctx.moveTo(x, offsetY);
            this.ctx.lineTo(x, offsetY + renderHeight);
            this.ctx.stroke();
            this.ctx.fillText(`X:${frac.toFixed(1)}`, x + 3, offsetY + 12);
        }

        // Horizontal lines
        for (let i = 1; i < steps; i++) {
            const frac = i / steps;
            const y = offsetY + frac * renderHeight;
            this.ctx.beginPath();
            this.ctx.moveTo(offsetX, y);
            this.ctx.lineTo(offsetX + renderWidth, y);
            this.ctx.stroke();
            this.ctx.fillText(`Y:${frac.toFixed(1)}`, offsetX + 4, y - 4);
        }

        // Space boundary
        this.ctx.setLineDash([]);
        this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
        this.ctx.strokeRect(offsetX, offsetY, renderWidth, renderHeight);
        this.ctx.restore();
    }

    _renderPerson(person, dims) {
        const color = this.getPersonColor(person.id);
        const { offsetX, offsetY, renderWidth, renderHeight } = dims;

        // Coordinates
        const footX = offsetX + person.x * renderWidth;
        const footY = offsetY + person.y * renderHeight;

        // Bounding box with corner brackets
        if (this.showBoundingBoxes && person.bbox) {
            const bx1 = offsetX + person.bbox[0] * renderWidth;
            const by1 = offsetY + person.bbox[1] * renderHeight;
            const bx2 = offsetX + person.bbox[2] * renderWidth;
            const by2 = offsetY + person.bbox[3] * renderHeight;
            const bw = bx2 - bx1;
            const bh = by2 - by1;
            const cornerLen = Math.min(14, bw * 0.25, bh * 0.25);

            this.ctx.save();
            this.ctx.strokeStyle = color;
            this.ctx.lineWidth = 1.5;
            this.ctx.lineCap = 'round';

            // Top-left
            this.ctx.beginPath();
            this.ctx.moveTo(bx1, by1 + cornerLen);
            this.ctx.lineTo(bx1, by1);
            this.ctx.lineTo(bx1 + cornerLen, by1);
            this.ctx.stroke();

            // Top-right
            this.ctx.beginPath();
            this.ctx.moveTo(bx2 - cornerLen, by1);
            this.ctx.lineTo(bx2, by1);
            this.ctx.lineTo(bx2, by1 + cornerLen);
            this.ctx.stroke();

            // Bottom-left
            this.ctx.beginPath();
            this.ctx.moveTo(bx1, by2 - cornerLen);
            this.ctx.lineTo(bx1, by2);
            this.ctx.lineTo(bx1 + cornerLen, by2);
            this.ctx.stroke();

            // Bottom-right
            this.ctx.beginPath();
            this.ctx.moveTo(bx2 - cornerLen, by2);
            this.ctx.lineTo(bx2, by2);
            this.ctx.lineTo(bx2, by2 - cornerLen);
            this.ctx.stroke();

            this.ctx.restore();
        }

        // Foot Anchor & Spatial Coordinate Reticle
        this.ctx.save();

        // Radar ground ellipse
        this.ctx.beginPath();
        this.ctx.ellipse(footX, footY, 14, 6, 0, 0, Math.PI * 2);
        this.ctx.fillStyle = color + '25';
        this.ctx.fill();
        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = 1.5;
        this.ctx.stroke();

        // Crosshair ticks
        this.ctx.beginPath();
        this.ctx.moveTo(footX - 16, footY);
        this.ctx.lineTo(footX - 8, footY);
        this.ctx.moveTo(footX + 8, footY);
        this.ctx.lineTo(footX + 16, footY);
        this.ctx.strokeStyle = color;
        this.ctx.stroke();

        // Inner glowing core
        this.ctx.beginPath();
        this.ctx.arc(footX, footY, 3, 0, Math.PI * 2);
        this.ctx.fillStyle = '#ffffff';
        this.ctx.fill();
        this.ctx.restore();

        // Automatic HUD Tag with ID, Zone & Coordinates
        if (this.showLabels) {
            const label = person.label || `P${String(person.id).padStart(2, '0')}`;
            const zoneText = person.zone ? `[${person.zone}]` : '';
            const coordText = `(${person.x.toFixed(2)}, ${person.y.toFixed(2)})`;
            const stateIcon = person.state === 'moving' ? '● MOV' : '■ STP';

            const fontSize = 11;
            this.ctx.font = `600 ${fontSize}px "SF Mono", Menlo, -apple-system, monospace`;
            const labelWidth = this.ctx.measureText(label).width;
            const zoneWidth = person.zone ? this.ctx.measureText(zoneText).width + 8 : 0;
            const coordWidth = this.showCoordinates ? this.ctx.measureText(coordText).width + 8 : 0;
            const stateWidth = this.ctx.measureText(stateIcon).width + 6;
            const totalWidth = labelWidth + zoneWidth + coordWidth + stateWidth + 16;

            const tagX = footX - totalWidth / 2;
            const tagY = footY + 12;

            // Background pill (iOS style squircle)
            this.ctx.save();
            this.ctx.fillStyle = 'rgba(28, 28, 30, 0.94)';
            this.ctx.strokeStyle = color + '99';
            this.ctx.lineWidth = 1.5;
            this.ctx.beginPath();
            this.ctx.roundRect(tagX, tagY, totalWidth, 20, 10);
            this.ctx.fill();
            this.ctx.stroke();

            // Label (e.g. P01)
            this.ctx.fillStyle = color;
            this.ctx.textAlign = 'left';
            this.ctx.textBaseline = 'alphabetic';
            this.ctx.fillText(label, tagX + 8, tagY + 14);

            let cursorX = tagX + labelWidth + 14;

            // Zone tag (e.g. [Entrada])
            if (person.zone) {
                this.ctx.fillStyle = person.zone_color || '#64d2ff';
                this.ctx.fillText(zoneText, cursorX, tagY + 14);
                cursorX += zoneWidth;
            }

            // Coordinates (e.g. (0.45, 0.72))
            if (this.showCoordinates) {
                this.ctx.fillStyle = '#94a3b8';
                this.ctx.fillText(coordText, cursorX, tagY + 14);
                cursorX += coordWidth;
            }

            // State indicator
            this.ctx.fillStyle = person.state === 'moving' ? '#30d158' : '#ff9f0a';
            this.ctx.fillText(stateIcon, cursorX, tagY + 14);
            this.ctx.restore();
        }
    }

    _renderTrails(dims) {
        const { offsetX, offsetY, renderWidth, renderHeight } = dims;

        for (const [personId, trail] of Object.entries(this.trails)) {
            if (trail.length < 2) continue;
            const color = this.getPersonColor(parseInt(personId));

            this.ctx.save();
            this.ctx.lineCap = 'round';
            this.ctx.lineJoin = 'round';

            // Draw line segments with fading alpha
            for (let i = 1; i < trail.length; i++) {
                const prev = trail[i - 1];
                const curr = trail[i];
                const p1x = offsetX + prev.x * renderWidth;
                const p1y = offsetY + prev.y * renderHeight;
                const p2x = offsetX + curr.x * renderWidth;
                const p2y = offsetY + curr.y * renderHeight;

                const progress = i / trail.length;
                this.ctx.lineWidth = 1.5 + progress * 2.0; // Grows thicker towards the current position
                this.ctx.strokeStyle = color;
                this.ctx.globalAlpha = Math.min(0.9, 0.15 + progress * 0.75);

                this.ctx.beginPath();
                this.ctx.moveTo(p1x, p1y);
                this.ctx.lineTo(p2x, p2y);
                this.ctx.stroke();
            }

            // Draw subtle breadcrumbs along the path
            for (let i = 0; i < trail.length; i += 6) {
                const pt = trail[i];
                const px = offsetX + pt.x * renderWidth;
                const py = offsetY + pt.y * renderHeight;
                const alpha = (i + 1) / trail.length;

                this.ctx.beginPath();
                this.ctx.arc(px, py, 2.5, 0, Math.PI * 2);
                this.ctx.fillStyle = color;
                this.ctx.globalAlpha = alpha * 0.7;
                this.ctx.fill();
            }

            this.ctx.restore();
        }
    }

    _setupResizeObserver() {
        const container = this.canvas.parentElement;
        if (container && window.ResizeObserver) {
            const observer = new ResizeObserver(() => {
                this._render();
            });
            observer.observe(container);
        }
    }

    _setupDrawingEvents() {
        // Register points on pointerdown (mouse click or touch tap)
        const handlePoint = (e) => {
            if (!this.isDrawingZone) return;
            e.preventDefault();
            e.stopPropagation();
            const norm = this.convertEventCoordsToNormalized(e);
            const count = this.addDrawingPoint(norm.x, norm.y);
            if (this.onPointAdded) {
                this.onPointAdded(count);
            }
        };

        this.canvas.addEventListener('pointerdown', handlePoint);

        // Hover tracking for live guideline
        this.canvas.addEventListener('pointermove', (e) => {
            if (!this.isDrawingZone) return;
            this.hoverPoint = this.convertEventCoordsToNormalized(e);
            this._render();
        });
    }
}

window.CanvasOverlay = CanvasOverlay;
