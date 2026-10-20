/**
 * Ritmos — Experiencia de Registro de Recorridos y Mapa de Calor Espacial
 * Flujo simplificado:
 * 1. Registro de recorridos de personas en vivo con visión computacional YOLO11.
 * 2. Auto-stop tras 10 minutos de grabación (600 segundos) y guardado automático de video en SQLite.
 * 3. Inmediatamente genera y superpone el mapa de calor sobre el video capturado con reproducción interactiva.
 */

(function () {
    'use strict';

    // ─── Estado de la Aplicación ─────────────────────────
    const state = {
        sessionActive: false,
        sessionId: null,
        sessionName: "Jardín Gandhi",
        sessionStartTime: null,
        recordedPointsCount: 0,
        maxSimultaneous: 0,
        timerInterval: null,
        _autoSaved10Min: false,
    };

    // ─── Toast Notificaciones Elegantes ──────────────────
    function showToast(message, duration = 3200) {
        let toast = document.getElementById('mobile-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'mobile-toast';
            toast.style.cssText = 'position:fixed; bottom:24px; left:50%; transform:translateX(-50%); background:rgba(20,20,24,0.92); backdrop-filter:blur(18px); color:#fff; border:1px solid rgba(255,255,255,0.18); padding:10px 22px; border-radius:24px; font-size:0.88rem; font-weight:600; box-shadow:0 8px 32px rgba(0,0,0,0.5); z-index:99999; transition:opacity 0.28s, transform 0.28s; pointer-events:none; text-align:center; max-width:90vw;';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(-50%) translateY(0)';
        clearTimeout(toast._timer);
        toast._timer = setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(-50%) translateY(10px)';
        }, duration);
    }

    // ─── Componentes ─────────────────────────────────────
    const camera = new CameraManager();
    const ws = new WebSocketManager();
    let overlay = null;
    let heatmap = null;
    let timeline = null;

    // ─── Elementos DOM ───────────────────────────────────
    const dom = {
        // Encabezado
        spaceNameInput: document.getElementById('space-name-input'),
        btnOpenHistory: document.getElementById('btn-open-history'),
        historyCount: document.getElementById('history-count'),
        connectionStatus: document.getElementById('connection-status'),

        // Modal Historial
        modalHistory: document.getElementById('modal-history'),
        btnCloseHistory: document.getElementById('btn-close-history'),
        historyContainer: document.getElementById('history-sessions-container'),

        // Modal de Informe Ejecutivo & Descarga
        modalExport: document.getElementById('modal-export'),
        btnCloseExport: document.getElementById('btn-close-export'),
        reportSessionName: document.getElementById('report-session-name'),
        reportSessionId: document.getElementById('report-session-id'),
        btnDownloadExcel: document.getElementById('btn-download-excel'),
        btnDownloadCsv: document.getElementById('btn-download-csv'),
        btnPrintReport: document.getElementById('btn-print-report'),
        printableReportDoc: document.getElementById('printable-report-doc'),
        btnTimelineReport: document.getElementById('btn-timeline-report'),

        // Contenedor de Video & Canvases
        cameraContainer: document.getElementById('camera-container'),
        cameraVideo: document.getElementById('camera-video'),
        replayVideo: document.getElementById('replay-video'),
        heatmapCanvas: document.getElementById('heatmap-canvas'),
        overlayCanvas: document.getElementById('overlay-canvas'),
        cameraPlaceholder: document.getElementById('camera-placeholder'),
        processingIndicator: document.getElementById('processing-indicator'),
        frameInfo: document.getElementById('frame-info'),
        fpsDisplay: document.getElementById('fps-display'),
        resolutionDisplay: document.getElementById('resolution-display'),
        btnExitFullscreen: document.getElementById('btn-exit-fullscreen'),

        // Modo Replay Flotante
        replayModeBadge: document.getElementById('replay-mode-badge'),
        btnExitReplayFloating: document.getElementById('btn-exit-replay-floating'),

        // Barra de Reproducción Interactiva (Video Capturado + Mapa de Calor)
        timelinePlayerBar: document.getElementById('timeline-player-bar'),
        timelineSessionName: document.getElementById('timeline-session-name'),
        timelinePointsStat: document.getElementById('timeline-points-stat'),
        timelineCurrentTime: document.getElementById('timeline-current-time'),
        timelineTotalDuration: document.getElementById('timeline-total-duration'),
        timelineScrubber: document.getElementById('timeline-scrubber'),
        btnTimelinePlay: document.getElementById('btn-timeline-play'),
        timelinePlayIcon: document.getElementById('timeline-play-icon'),
        btnTimelineRestart: document.getElementById('btn-timeline-restart'),
        btnTimelineStepBack: document.getElementById('btn-timeline-step-back'),
        btnTimelineStepFwd: document.getElementById('btn-timeline-step-fwd'),
        btnTimelineClose: document.getElementById('btn-timeline-close'),
        timelineSpeedBtns: document.querySelectorAll('.btn-timeline-speed'),
        toggleLayerHeatmap: document.getElementById('toggle-layer-heatmap'),
        toggleLayerTrajectories: document.getElementById('toggle-layer-trajectories'),

        // HUD & Temporizador
        timerValue: document.getElementById('timer-value'),
        statVisible: document.getElementById('stat-visible'),
        statTotal: document.getElementById('stat-total'),
        sessionStatus: document.getElementById('session-status-text'),

        // Botones de Control
        btnCamera: document.getElementById('btn-camera'),
        btnCameraFlip: document.getElementById('btn-camera-flip'),
        cameraFlipLabel: document.getElementById('camera-flip-label'),
        btnStart: document.getElementById('btn-start'),
        btnStop: document.getElementById('btn-stop'),
        btnFullscreen: document.getElementById('btn-fullscreen'),

        // Selectores de Configuración
        selectAspect: document.getElementById('select-aspect'),
        selectFPS: document.getElementById('select-fps'),
        selectQuality: document.getElementById('select-quality'),
    };

    // ═══════════════════════════════════════════════════════
    // SINCRONIZACIÓN INICIAL
    // ═══════════════════════════════════════════════════════

    async function refreshHistoryCount() {
        try {
            const res = await fetch('/api/sessions');
            if (res.ok) {
                const data = await res.json();
                if (dom.historyCount) dom.historyCount.textContent = data.count || 0;
            }
        } catch (e) {
            console.warn('[App] No se pudo obtener el conteo de grabaciones:', e);
        }
    }

    refreshHistoryCount();

    // ═══════════════════════════════════════════════════════
    // CÁMARA Y TRANSMISIÓN LOCKSTEP (CERO LAG)
    // ═══════════════════════════════════════════════════════

    let isAwaitingVisionResult = false;
    let frameWatchdogTimer = null;
    let lastFrameSentTimestamp = 0;
    const minFrameIntervalMs = 25; // Fluido a 35-40 FPS

    function triggerNextCameraFrame() {
        if (!camera.isActive || !ws.isConnected) return;
        if (isAwaitingVisionResult) return;

        const now = Date.now();
        const delta = now - lastFrameSentTimestamp;
        if (delta < minFrameIntervalMs) {
            setTimeout(triggerNextCameraFrame, minFrameIntervalMs - delta);
            return;
        }

        camera.captureNow();
    }

    camera.onStart = (info) => {
        if (dom.cameraPlaceholder) dom.cameraPlaceholder.classList.add('hidden');
        if (dom.resolutionDisplay) dom.resolutionDisplay.textContent = `${info.width}×${info.height}`;
        if (dom.btnCamera) {
            const lbl = dom.btnCamera.querySelector('.btn-label');
            if (lbl) lbl.textContent = 'Detener Cam';
        }
        if (dom.btnStart) dom.btnStart.disabled = false;

        if (!overlay) {
            overlay = new CanvasOverlay('overlay-canvas', camera);
        }
        if (!heatmap) {
            heatmap = new HeatmapRenderer('heatmap-canvas', camera);
        }

        if (dom.cameraFlipLabel) dom.cameraFlipLabel.textContent = camera.getCameraLabel();

        if (!ws.isConnected) {
            ws.connect();
        }

        isAwaitingVisionResult = false;
        triggerNextCameraFrame();
        showToast('📷 Cámara lista — Presiona Iniciar Grabación');
    };

    camera.onStop = () => {
        if (dom.cameraPlaceholder) dom.cameraPlaceholder.classList.remove('hidden');
        if (dom.btnCamera) {
            const lbl = dom.btnCamera.querySelector('.btn-label');
            if (lbl) lbl.textContent = 'Cámara';
        }
        if (dom.btnStart) dom.btnStart.disabled = true;

        if (state.sessionActive) {
            stopSession();
        }
        if (overlay) overlay.clear();
        if (heatmap) heatmap.clear();
    };

    camera.onError = (error) => {
        let msg = 'Error al acceder a la cámara.';
        if (error.name === 'NotAllowedError') {
            msg = 'Permiso denegado. Habilita el acceso a la cámara en el navegador.';
        } else if (error.name === 'NotFoundError') {
            msg = 'No se encontró cámara disponible.';
        }
        showToast(`⚠️ ${msg}`);
        alert(msg);
    };

    camera.onFrame = (blob) => {
        if (!ws.isConnected) return;

        if (ws.getBufferedAmount && ws.getBufferedAmount() > 32768) {
            isAwaitingVisionResult = false;
            setTimeout(triggerNextCameraFrame, 50);
            return;
        }

        isAwaitingVisionResult = true;
        lastFrameSentTimestamp = Date.now();
        ws.sendFrame(blob);

        clearTimeout(frameWatchdogTimer);
        frameWatchdogTimer = setTimeout(() => {
            isAwaitingVisionResult = false;
            triggerNextCameraFrame();
        }, 450);
    };

    // ═══════════════════════════════════════════════════════
    // WEBSOCKET: DETECCIÓN Y REGISTRO DE RECORRIDOS
    // ═══════════════════════════════════════════════════════

    ws.onConnect = () => {
        if (dom.connectionStatus) {
            dom.connectionStatus.className = 'status-indicator connected';
            const txt = dom.connectionStatus.querySelector('.status-text');
            if (txt) txt.textContent = 'En Línea';
        }
        if (dom.processingIndicator) dom.processingIndicator.classList.remove('hidden');
        isAwaitingVisionResult = false;
        triggerNextCameraFrame();
    };

    ws.onDisconnect = () => {
        if (dom.connectionStatus) {
            dom.connectionStatus.className = 'status-indicator disconnected';
            const txt = dom.connectionStatus.querySelector('.status-text');
            if (txt) txt.textContent = 'Desconectado';
        }
        if (dom.processingIndicator) dom.processingIndicator.classList.add('hidden');
        isAwaitingVisionResult = false;
    };

    ws.onResult = (result) => {
        clearTimeout(frameWatchdogTimer);
        isAwaitingVisionResult = false;

        const { persons, frame_stats } = result;

        // 1. Dibujar recorridos (trajectories) y personas en el canvas
        if (overlay) {
            overlay.update(persons);
        }

        // 2. Acumular puntos si la sesión de grabación está activa
        if (state.sessionActive && persons && persons.length > 0) {
            state.recordedPointsCount += persons.length;
        }

        // 3. Actualizar HUD
        const visibleCount = (persons || []).length;
        if (dom.statVisible) dom.statVisible.textContent = visibleCount;
        if (visibleCount > state.maxSimultaneous) {
            state.maxSimultaneous = visibleCount;
        }
        if (frame_stats) {
            if (dom.statTotal) dom.statTotal.textContent = frame_stats.total_detected;
            if (dom.fpsDisplay) dom.fpsDisplay.textContent = `${frame_stats.effective_fps || '--'} FPS`;
        }

        triggerNextCameraFrame();
    };

    // ═══════════════════════════════════════════════════════
    // CICLO DE GRABACIÓN (10 MINUTOS + AUTO-STOP)
    // ═══════════════════════════════════════════════════════

    function startSession() {
        if (timeline && (timeline.session || (dom.replayVideo && !dom.replayVideo.classList.contains('hidden')))) {
            exitReplayAndReturnToLive();
        }

        if (!camera.isActive) {
            showToast('⚠️ Primero enciende la cámara');
            return;
        }

        const spaceName = (dom.spaceNameInput ? dom.spaceNameInput.value : "").trim() || "Jardín Gandhi";
        const sessionId = `session_${Date.now()}`;

        state.sessionActive = true;
        state.sessionId = sessionId;
        state.sessionName = spaceName;
        state.sessionStartTime = Date.now();
        state.recordedPointsCount = 0;
        state.maxSimultaneous = 0;
        state._autoSaved10Min = false;

        if (!ws.isConnected) {
            ws.connect();
        }

        // Iniciar sesión en el backend para almacenar coordenadas
        ws.sendControl({
            action: 'session_start',
            session_id: sessionId,
            name: spaceName
        });

        // Iniciar grabación de video de la cámara
        const recStarted = camera.startVideoRecording();
        if (recStarted) {
            showToast(`🔴 Grabando recorridos y video (Auto-stop a 10 min)`);
        } else {
            showToast(`🔴 Grabando recorridos (Auto-stop a 10 min)`);
        }

        // Actualizar UI
        if (dom.btnStart) dom.btnStart.classList.add('hidden');
        if (dom.btnStop) dom.btnStop.classList.remove('hidden');
        if (dom.sessionStatus) {
            dom.sessionStatus.textContent = `🔴 Grabando: ${spaceName}`;
            dom.sessionStatus.className = 'recording';
        }
        if (dom.spaceNameInput) dom.spaceNameInput.disabled = true;

        startTimer();
    }

    function startTimer() {
        clearInterval(state.timerInterval);
        state.timerInterval = setInterval(() => {
            if (!state.sessionActive) return;

            const elapsedMs = Date.now() - state.sessionStartTime;
            const totalSec = Math.max(0, Math.floor(elapsedMs / 1000));

            const h = Math.floor(totalSec / 3600);
            const m = Math.floor((totalSec % 3600) / 60);
            const s = totalSec % 60;

            if (dom.timerValue) {
                dom.timerValue.textContent =
                    `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
            }

            // REGLA: Parar de grabar después de 10 min (600 segundos) automáticamente
            if (totalSec >= 600 && state.sessionActive && !state._autoSaved10Min) {
                state._autoSaved10Min = true;
                showToast('⏱️ ¡10 minutos completados! Finalizando y creando mapa de calor...');
                stopSession();
            }
        }, 500);
    }

    async function stopSession() {
        if (!state.sessionActive) return;

        const stoppedSessionId = state.sessionId;
        state.sessionActive = false;

        clearInterval(state.timerInterval);
        state.timerInterval = null;

        ws.sendControl({ action: 'session_stop' });

        showToast('💾 Finalizando y guardando video capturado...');
        if (dom.sessionStatus) {
            dom.sessionStatus.textContent = 'Procesando video y mapa de calor...';
            dom.sessionStatus.className = '';
        }

        // Detener grabación de video de la cámara y subir al servidor
        try {
            const videoBlob = await camera.stopVideoRecording();
            if (videoBlob && videoBlob.size > 0 && stoppedSessionId) {
                const isMp4 = videoBlob.type && videoBlob.type.includes('mp4');
                const ext = isMp4 ? 'mp4' : 'webm';
                const filename = `${stoppedSessionId}.${ext}`;
                const formData = new FormData();
                formData.append('video', videoBlob, filename);
                formData.append('file', videoBlob, filename);

                const upRes = await fetch(`/api/sessions/${stoppedSessionId}/video`, {
                    method: 'POST',
                    body: formData,
                });

                if (upRes.ok) {
                    const mbSize = (videoBlob.size / 1024 / 1024).toFixed(2);
                    console.log(`[App] Video guardado con éxito: ${mbSize} MB`);
                } else {
                    console.warn('[App] Error al subir video:', upRes.status);
                }
            }
        } catch (e) {
            console.warn('[App] Excepción al finalizar video:', e);
        }

        // Restaurar botones de control
        if (dom.btnStart) dom.btnStart.classList.remove('hidden');
        if (dom.btnStop) dom.btnStop.classList.add('hidden');
        if (dom.spaceNameInput) dom.spaceNameInput.disabled = false;
        if (dom.sessionStatus) dom.sessionStatus.textContent = '✅ Grabación completada';

        refreshHistoryCount();

        // ═══════════════════════════════════════════════════════
        // TRANSICIÓN AUTOMÁTICA DIRECTA:
        // "Después lo único que harás es crear un mapa de calor
        //  encima del video capturado, el resto de funciones elimínalas."
        // ═══════════════════════════════════════════════════════
        showToast('🔥 Cargando mapa de calor sobre el video capturado...');
        setTimeout(() => {
            viewSessionHeatmap(stoppedSessionId);
        }, 500);
    }

    // ═══════════════════════════════════════════════════════
    // REPRODUCCIÓN: VIDEO CAPTURADO + MAPA DE CALOR ENCIMA
    // ═══════════════════════════════════════════════════════

    function formatTime(sec) {
        sec = Math.max(0, Math.floor(sec || 0));
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    function initTimelinePlayer() {
        if (!timeline) {
            timeline = new TimelinePlayer({
                heatmap: heatmap,
                overlay: overlay,
                videoElement: dom.replayVideo,
                onTimeUpdate: (info) => {
                    if (dom.timelineCurrentTime) dom.timelineCurrentTime.textContent = formatTime(info.currentTime);
                    if (dom.timelineTotalDuration) dom.timelineTotalDuration.textContent = formatTime(info.duration);
                    if (dom.timelineScrubber) {
                        dom.timelineScrubber.value = info.currentTime;
                        dom.timelineScrubber.max = info.duration;
                    }
                    if (dom.timelinePointsStat) {
                        const videoTag = info.hasVideo ? ' • 🎬 Video Sincronizado' : '';
                        dom.timelinePointsStat.textContent = `${info.pointsCount} puntos • ${info.activePersonsCount} personas${videoTag}`;
                    }
                    if (dom.timelinePlayIcon) {
                        dom.timelinePlayIcon.textContent = info.isPlaying ? '⏸' : '▶';
                    }
                },
                onStateChange: (info) => {
                    if (info.isPlaying !== undefined && dom.timelinePlayIcon) {
                        dom.timelinePlayIcon.textContent = info.isPlaying ? '⏸' : '▶';
                    }
                    if (info.duration !== undefined && dom.timelineScrubber) {
                        dom.timelineScrubber.max = info.duration;
                        if (dom.timelineTotalDuration) dom.timelineTotalDuration.textContent = formatTime(info.duration);
                    }
                    if (info.session && info.session.name && dom.timelineSessionName) {
                        dom.timelineSessionName.textContent = info.session.name;
                    }
                }
            });
        }
    }

    window.viewSessionHeatmap = async (sessionId) => {
        try {
            if (!heatmap) {
                heatmap = new HeatmapRenderer('heatmap-canvas', camera);
            }
            if (!overlay) {
                overlay = new CanvasOverlay('overlay-canvas', camera);
            }

            // Pausar stream de cámara para dar paso al video capturado
            if (camera.isActive) {
                camera.pauseCapture();
            }
            if (dom.cameraPlaceholder) dom.cameraPlaceholder.classList.add('hidden');
            if (dom.replayModeBadge) dom.replayModeBadge.classList.remove('hidden');

            // Obtener metadatos de sesión y coordenadas del mapa de calor
            const [metaRes, pointsRes] = await Promise.all([
                fetch(`/api/sessions/${sessionId}`),
                fetch(`/api/analytics/sessions/${sessionId}/heatmap?limit=60000`)
            ]);

            if (!pointsRes.ok) throw new Error('No se pudieron obtener las coordenadas del mapa de calor');
            const data = await pointsRes.json();
            const metaData = metaRes.ok ? await metaRes.json() : { session: {} };
            const session = metaData.session || { id: sessionId, name: `Sesión ${sessionId}` };

            initTimelinePlayer();
            await timeline.loadSession(session, data.points);

            // Asegurar que el mapa de calor está en modo presencia
            if (heatmap) {
                heatmap.setMode('presence');
            }

            // Mostrar barra de controles del reproductor
            if (dom.timelinePlayerBar) dom.timelinePlayerBar.classList.remove('hidden');

            // Cerrar modal de historial si estaba abierto
            closeHistoryModal();

            showToast(`🎬 Video capturado + Mapa de calor: ${session.name}`);
        } catch (e) {
            console.error('[App] Error al cargar video y mapa de calor:', e);
            alert(`Error: ${e.message}`);
        }
    };

    function exitReplayAndReturnToLive() {
        if (timeline) {
            timeline.close();
        }
        if (dom.replayVideo) {
            dom.replayVideo.pause();
            dom.replayVideo.removeAttribute('src');
            dom.replayVideo.load();
            dom.replayVideo.classList.add('hidden');
        }
        if (dom.timelinePlayerBar) dom.timelinePlayerBar.classList.add('hidden');
        if (dom.replayModeBadge) dom.replayModeBadge.classList.add('hidden');

        if (heatmap) {
            heatmap.clear();
            if (heatmap.canvas) heatmap.canvas.style.display = 'block';
        }
        if (overlay) {
            overlay.clear();
            overlay.update([]);
        }

        if (camera.isActive) {
            if (dom.cameraPlaceholder) dom.cameraPlaceholder.classList.add('hidden');
            camera.resumeCapture();
            if (dom.sessionStatus) dom.sessionStatus.textContent = 'Cámara en vivo lista';
        } else {
            if (dom.cameraPlaceholder) dom.cameraPlaceholder.classList.remove('hidden');
            if (dom.sessionStatus) dom.sessionStatus.textContent = 'En espera — Presiona Iniciar Cámara';
        }

        if (dom.btnStart) dom.btnStart.classList.remove('hidden');
        if (dom.btnStop) dom.btnStop.classList.add('hidden');

        showToast('📹 Regresando a la cámara en vivo');
    }

    // ═══════════════════════════════════════════════════════
    // HISTORIAL DE GRABACIONES (SIMPLIFICADO)
    // ═══════════════════════════════════════════════════════

    async function openHistoryModal() {
        if (!dom.modalHistory || !dom.historyContainer) return;
        dom.modalHistory.classList.add('active');
        dom.historyContainer.innerHTML = '<div class="persons-empty">Cargando grabaciones...</div>';

        try {
            const res = await fetch('/api/sessions');
            if (!res.ok) throw new Error('Error al consultar sesiones');
            const data = await res.json();
            const sessions = data.sessions || [];

            if (dom.historyCount) dom.historyCount.textContent = sessions.length;

            if (sessions.length === 0) {
                dom.historyContainer.innerHTML = `
                    <div class="persons-empty">
                        No hay grabaciones todavía.<br>
                        Inicia la cámara, presiona "Iniciar Grabación" y tras 10 minutos (o al presionar Finalizar) verás aquí tu video con el mapa de calor.
                    </div>
                `;
                return;
            }

            let html = '';
            for (const s of sessions) {
                const dateStr = s.started_at ? new Date(s.started_at * 1000).toLocaleString() : (s.created_at || 'Fecha no disponible');
                const durMin = ((s.duration_seconds || 0) / 60).toFixed(1);
                const hasVideo = !!s.video_path;

                html += `
                    <div class="session-card" style="border-left: 4px solid var(--accent-blue);">
                        <div class="session-card-header">
                            <div>
                                <span class="session-title">${s.name || 'Grabación'}</span>
                                <span class="session-date"> • ${dateStr}</span>
                                ${hasVideo ? '<span class="tag tag-sm" style="background:rgba(48,209,88,0.22); color:#30d158; border:0.5px solid rgba(48,209,88,0.45); font-size:0.7rem; padding:2px 8px; border-radius:10px; margin-left:6px;">🎬 Video Disponible</span>' : ''}
                            </div>
                            <span class="session-date" style="font-family:var(--font-mono);">${durMin} min</span>
                        </div>
                        <div class="session-metrics">
                            <div class="session-metric-item">
                                <span>Duración</span>
                                <strong>${durMin} min</strong>
                            </div>
                            <div class="session-metric-item">
                                <span>Personas Registradas</span>
                                <strong>${s.total_persons || 0}</strong>
                            </div>
                            <div class="session-metric-item">
                                <span>Pico Simultáneo</span>
                                <strong>${s.max_concurrent || 0}</strong>
                            </div>
                        </div>
                        <div class="session-actions" style="margin-top:10px; display:flex; gap:8px; justify-content:flex-end; align-items:center;">
                            <button class="btn btn-sm btn-secondary" onclick="openReportModal('${s.id}')" style="background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.22); color:#fff; display:inline-flex; align-items:center; gap:6px; font-weight:500;" title="Ver y descargar informe ejecutivo de la sesión">
                                <span>📊</span>
                                <span>Descargar Informe</span>
                            </button>
                            <button class="btn btn-sm btn-primary" onclick="viewSessionHeatmap('${s.id}')" title="Ver video capturado con mapa de calor encima">
                                🎬 Ver Video + Mapa de Calor
                            </button>
                            ${hasVideo ? `
                            <a href="/api/sessions/${s.id}/video" download="${s.id}.mp4" class="btn btn-sm btn-secondary" title="Descargar archivo de video">
                                📥 Video
                            </a>` : ''}
                            <button class="btn btn-sm btn-danger" onclick="deleteSession('${s.id}')" title="Eliminar grabación">
                                🗑️
                            </button>
                        </div>
                    </div>
                `;
            }

            dom.historyContainer.innerHTML = html;
        } catch (e) {
            dom.historyContainer.innerHTML = `<div class="persons-empty">Error al cargar historial: ${e.message}</div>`;
        }
    }

    function closeHistoryModal() {
        if (dom.modalHistory) dom.modalHistory.classList.remove('active');
    }

    // ═══════════════════════════════════════════════════════
    // INFORME EJECUTIVO Y DESCARGA
    // ═══════════════════════════════════════════════════════

    async function openReportModal(sessionId) {
        if (!dom.modalExport || !dom.printableReportDoc) return;

        dom.modalExport.classList.add('active');
        if (dom.reportSessionId) dom.reportSessionId.textContent = `(ID: ${sessionId})`;
        dom.printableReportDoc.innerHTML = `
            <div style="text-align: center; padding: 40px 20px; color: #64748b;">
                <div class="pulse-dot" style="display:inline-block; margin-bottom: 12px; background: #0071e3;"></div>
                <p style="font-size: 0.9rem; font-weight: 500;">Generando y procesando informe de la sesión...</p>
            </div>
        `;

        if (dom.btnDownloadExcel) {
            dom.btnDownloadExcel.href = `/api/analytics/sessions/${sessionId}/export/excel`;
            dom.btnDownloadExcel.download = `informe_${sessionId}.xlsx`;
        }
        if (dom.btnDownloadCsv) {
            dom.btnDownloadCsv.href = `/api/analytics/sessions/${sessionId}/export/csv`;
            dom.btnDownloadCsv.download = `informe_${sessionId}.csv`;
        }

        try {
            const res = await fetch(`/api/analytics/sessions/${sessionId}/report`);
            if (!res.ok) throw new Error('No se pudo cargar el informe de la sesión');
            const data = await res.json();
            const s = data.summary || {};
            const persons = data.persons || [];

            if (dom.reportSessionName) dom.reportSessionName.textContent = s.name || 'Jardín Gandhi';
            if (dom.btnDownloadExcel) dom.btnDownloadExcel.download = `${s.name || 'informe'}_${sessionId}.xlsx`;
            if (dom.btnDownloadCsv) dom.btnDownloadCsv.download = `${s.name || 'informe'}_${sessionId}.csv`;

            const dateStr = s.created_at ? new Date(s.created_at).toLocaleString() : (s.started_at ? new Date(s.started_at * 1000).toLocaleString() : 'Fecha no especificada');

            let personsRows = '';
            if (persons.length === 0) {
                personsRows = `<tr><td colspan="7" style="text-align:center; padding:16px; color:#888;">No se registraron personas individuales en esta sesión.</td></tr>`;
            } else {
                for (const p of persons) {
                    const isMoving = p.dominant_state && p.dominant_state.includes('Movimiento');
                    personsRows += `
                        <tr>
                            <td style="font-family:var(--font-mono); font-weight:600; color:#0071e3; text-align:center;">${p.label}</td>
                            <td style="text-align:right; font-family:var(--font-mono);">${p.duration_seconds} s</td>
                            <td style="text-align:right; font-family:var(--font-mono);">${p.distance_meters} m</td>
                            <td style="text-align:right; font-family:var(--font-mono);">${p.avg_speed_ms} m/s</td>
                            <td style="text-align:center;"><span style="display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.68rem; font-weight:600; background:${isMoving ? 'rgba(48,209,88,0.15)' : 'rgba(255,159,10,0.15)'}; color:${isMoving ? '#1b5e20' : '#b45309'};">${p.dominant_state}</span></td>
                            <td style="text-align:right; font-family:var(--font-mono);">${p.points_count}</td>
                            <td style="font-family:var(--font-mono); font-size:0.7rem; color:#555; text-align:center;">(${p.start_coords[0]}, ${p.start_coords[1]}) ➔ (${p.end_coords[0]}, ${p.end_coords[1]})</td>
                        </tr>
                    `;
                }
            }

            dom.printableReportDoc.innerHTML = `
                <div class="report-doc-header">
                    <div class="report-doc-brand">RITMOS — CARTOGRAFÍA ESPACIAL DE RECORRIDOS</div>
                    <h2 class="report-doc-title">Informe de Observación y Cartografía</h2>
                    <div class="report-doc-meta">
                        <span><strong>Espacio:</strong> ${s.name || 'Jardín Gandhi'}</span>
                        <span>•</span>
                        <span><strong>Fecha y Hora:</strong> ${dateStr}</span>
                        <span>•</span>
                        <span><strong>ID Sesión:</strong> ${sessionId}</span>
                    </div>
                </div>

                <div class="report-section">
                    <h4 class="report-sec-heading">Resumen General de la Sesión</h4>
                    <div class="report-kpis-grid">
                        <div class="report-kpi-item">
                            <span class="report-kpi-lbl">Duración</span>
                            <span class="report-kpi-val">${s.duration_minutes || 0} min</span>
                            <span class="report-kpi-sub">${s.duration_seconds || 0} segundos</span>
                        </div>
                        <div class="report-kpi-item">
                            <span class="report-kpi-lbl">Personas Registradas</span>
                            <span class="report-kpi-val">${s.total_persons || 0}</span>
                            <span class="report-kpi-sub">Individuos únicos</span>
                        </div>
                        <div class="report-kpi-item">
                            <span class="report-kpi-lbl">Pico Simultáneo</span>
                            <span class="report-kpi-val">${s.max_concurrent || 0}</span>
                            <span class="report-kpi-sub">Máx concurrente</span>
                        </div>
                        <div class="report-kpi-item">
                            <span class="report-kpi-lbl">Total Coordenadas</span>
                            <span class="report-kpi-val">${s.total_points || 0}</span>
                            <span class="report-kpi-sub">Puntos mapeados</span>
                        </div>
                        <div class="report-kpi-item">
                            <span class="report-kpi-lbl">Dinámica de Movimiento</span>
                            <span class="report-kpi-val" style="font-size:1.05rem;">${s.movement_ratio_percent || 0}%</span>
                            <span class="report-kpi-sub">En desplazamiento</span>
                        </div>
                        <div class="report-kpi-item">
                            <span class="report-kpi-lbl">Permanencia Estática</span>
                            <span class="report-kpi-val" style="font-size:1.05rem;">${s.stopped_ratio_percent || 0}%</span>
                            <span class="report-kpi-sub">Detenido / En reposo</span>
                        </div>
                    </div>
                </div>

                <div class="report-section" style="margin-top: 14px;">
                    <h4 class="report-sec-heading">Registro Detallado de Recorridos por Persona (${persons.length})</h4>
                    <div style="overflow-x: auto;">
                        <table class="report-table">
                            <thead>
                                <tr>
                                    <th style="text-align:center;">ID</th>
                                    <th style="text-align:right;">Tiempo</th>
                                    <th style="text-align:right;">Distancia</th>
                                    <th style="text-align:right;">Velocidad Media</th>
                                    <th style="text-align:center;">Estado Predominante</th>
                                    <th style="text-align:right;">Puntos</th>
                                    <th style="text-align:center;">Coordenadas (Inicio ➔ Fin)</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${personsRows}
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="report-doc-footer">
                    <span>Generado por <strong>Ritmos — Spatial Rhythm Observer</strong></span>
                    <span>Documento técnico de investigación empírica</span>
                </div>
            `;
        } catch (e) {
            console.error('[App] Error al generar informe:', e);
            dom.printableReportDoc.innerHTML = `
                <div class="persons-empty" style="color:#ff6961;">
                    Error al cargar datos del informe: ${e.message}
                </div>
            `;
        }
    }

    function closeReportModal() {
        if (dom.modalExport) dom.modalExport.classList.remove('active');
    }

    window.openReportModal = openReportModal;
    window.closeReportModal = closeReportModal;

    window.deleteSession = async (sessionId) => {
        if (!confirm(`¿Eliminar la grabación ${sessionId} y sus datos?`)) return;
        try {
            const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
            if (res.ok) {
                openHistoryModal();
                refreshHistoryCount();
                showToast('🗑️ Grabación eliminada');
            } else {
                alert('No se pudo eliminar la grabación.');
            }
        } catch (e) {
            alert(`Error: ${e.message}`);
        }
    };

    // ═══════════════════════════════════════════════════════
    // EVENT LISTENERS
    // ═══════════════════════════════════════════════════════

    // Control de Cámara
    if (dom.btnCamera) {
        dom.btnCamera.addEventListener('click', () => {
            if (camera.isActive) {
                camera.stop();
            } else {
                camera.start();
            }
        });
    }

    if (dom.btnCameraFlip) {
        dom.btnCameraFlip.addEventListener('click', async () => {
            const label = await camera.switchCamera();
            if (dom.cameraFlipLabel) dom.cameraFlipLabel.textContent = label;
            showToast(`Cámara cambiada: ${label}`);
        });
    }

    // Grabación
    if (dom.btnStart) dom.btnStart.addEventListener('click', startSession);
    if (dom.btnStop) dom.btnStop.addEventListener('click', stopSession);

    // Formato de Aspect Ratio
    if (dom.selectAspect && dom.cameraContainer) {
        dom.selectAspect.addEventListener('change', () => {
            const val = dom.selectAspect.value;
            if (val === '16-9') dom.cameraContainer.style.aspectRatio = '16 / 9';
            else if (val === '4-3') dom.cameraContainer.style.aspectRatio = '4 / 3';
            else dom.cameraContainer.style.aspectRatio = 'auto';
            if (overlay) overlay._render();
        });
    }

    // Pantalla Completa
    if (dom.btnFullscreen && dom.cameraContainer) {
        dom.btnFullscreen.addEventListener('click', () => {
            camera.toggleFullscreen(dom.cameraContainer);
        });
    }
    if (dom.btnExitFullscreen && dom.cameraContainer) {
        dom.btnExitFullscreen.addEventListener('click', () => {
            camera.toggleFullscreen(dom.cameraContainer);
        });
    }
    document.addEventListener('fullscreenchange', () => {
        const isFS = !!(document.fullscreenElement || document.webkitFullscreenElement);
        if (dom.btnExitFullscreen) dom.btnExitFullscreen.classList.toggle('hidden', !isFS);
        if (overlay) overlay._render();
    });

    // Modal de Historial
    if (dom.btnOpenHistory) dom.btnOpenHistory.addEventListener('click', openHistoryModal);
    if (dom.btnCloseHistory) dom.btnCloseHistory.addEventListener('click', closeHistoryModal);
    if (dom.modalHistory) {
        dom.modalHistory.addEventListener('click', (e) => {
            if (e.target === dom.modalHistory) closeHistoryModal();
        });
    }

    // Controles del Reproductor (Video Capturado + Mapa de Calor)
    if (dom.timelineScrubber) {
        dom.timelineScrubber.addEventListener('input', (e) => {
            if (timeline) timeline.seekTo(parseFloat(e.target.value));
        });
    }

    if (dom.btnTimelinePlay) {
        dom.btnTimelinePlay.addEventListener('click', () => {
            if (timeline) timeline.togglePlay();
        });
    }

    if (dom.btnTimelineRestart) {
        dom.btnTimelineRestart.addEventListener('click', () => {
            if (timeline) timeline.restart();
        });
    }

    if (dom.btnTimelineStepBack) {
        dom.btnTimelineStepBack.addEventListener('click', () => {
            if (timeline) timeline.step(-1);
        });
    }

    if (dom.btnTimelineStepFwd) {
        dom.btnTimelineStepFwd.addEventListener('click', () => {
            if (timeline) timeline.step(1);
        });
    }

    if (dom.btnTimelineClose) {
        dom.btnTimelineClose.addEventListener('click', exitReplayAndReturnToLive);
    }
    if (dom.btnExitReplayFloating) {
        dom.btnExitReplayFloating.addEventListener('click', exitReplayAndReturnToLive);
    }

    // Selector de Velocidad (0.5x, 1x, 2x, 4x)
    dom.timelineSpeedBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            dom.timelineSpeedBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const spd = parseFloat(btn.getAttribute('data-speed'));
            if (timeline) timeline.setPlaybackSpeed(spd);
        });
    });

    // Alternar Capas: Mapa de Calor y Recorridos
    if (dom.toggleLayerHeatmap) {
        dom.toggleLayerHeatmap.addEventListener('click', () => {
            if (timeline) {
                const active = timeline.toggleLayer('heatmap');
                dom.toggleLayerHeatmap.classList.toggle('active', active);
            }
        });
    }

    if (dom.toggleLayerTrajectories) {
        dom.toggleLayerTrajectories.addEventListener('click', () => {
            if (timeline) {
                const active = timeline.toggleLayer('trajectories');
                dom.toggleLayerTrajectories.classList.toggle('active', active);
            }
        });
    }

    // Modal de Informe Ejecutivo & Descarga
    if (dom.btnCloseExport) dom.btnCloseExport.addEventListener('click', closeReportModal);
    if (dom.modalExport) {
        dom.modalExport.addEventListener('click', (e) => {
            if (e.target === dom.modalExport) closeReportModal();
        });
    }
    if (dom.btnPrintReport) {
        dom.btnPrintReport.addEventListener('click', () => {
            window.print();
        });
    }
    if (dom.btnTimelineReport) {
        dom.btnTimelineReport.addEventListener('click', () => {
            if (timeline && timeline.session && timeline.session.id) {
                openReportModal(timeline.session.id);
            } else if (state.sessionId) {
                openReportModal(state.sessionId);
            } else {
                showToast('No hay una grabación seleccionada para ver su informe');
            }
        });
    }

})();
