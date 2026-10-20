/**
 * Spatial Rhythm Observer — Camera Module
 * Handles camera access, frame extraction, and streaming to server.
 */

class CameraManager {
    constructor() {
        this.video = document.getElementById('camera-video');
        this.stream = null;
        this.isActive = false;
        this.captureCanvas = document.createElement('canvas');
        this.captureCtx = this.captureCanvas.getContext('2d');
        
        // Frame capture settings
        this.analysisFPS = 5;
        this.jpegQuality = 0.6;
        this.captureInterval = null;
        
        // Camera device selection & enumeration
        this.facingMode = 'environment'; // 'environment' or 'user'
        this.videoDevices = [];
        this.currentDeviceIndex = 0;
        this.currentDeviceId = null;

        // Resolution
        this.frameWidth = 0;
        this.frameHeight = 0;

        // Callbacks
        this.onFrame = null;  // Called with JPEG Blob for each captured frame
        this.onStart = null;
        this.onStop = null;
        this.onError = null;
    }

    /**
     * Enumerate all video input devices available on the system.
     */
    async getAvailableVideoDevices() {
        try {
            if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
                return [];
            }
            const devices = await navigator.mediaDevices.enumerateDevices();
            this.videoDevices = devices.filter(d => d.kind === 'videoinput');
            return this.videoDevices;
        } catch (e) {
            console.warn('[Camera] Error enumerating devices:', e);
            return [];
        }
    }

    /**
     * Request camera access and start the video stream.
     */
    async startCamera() {
        try {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error('Tu navegador o contexto (requiere HTTPS o localhost) no soporta acceso a la cámara.');
            }

            // Build constraints preferring exact deviceId or facingMode
            const videoConstraints = {
                width: { ideal: 1920, min: 640 },
                height: { ideal: 1080, min: 480 },
                frameRate: { ideal: 30 },
            };

            if (this.currentDeviceId) {
                videoConstraints.deviceId = { exact: this.currentDeviceId };
            } else {
                videoConstraints.facingMode = { ideal: this.facingMode };
            }

            try {
                this.stream = await navigator.mediaDevices.getUserMedia({
                    video: videoConstraints,
                    audio: false
                });
            } catch (firstErr) {
                console.warn('[Camera] Failed with specific constraints, trying fallback:', firstErr);
                try {
                    this.stream = await navigator.mediaDevices.getUserMedia({
                        video: { facingMode: this.facingMode },
                        audio: false
                    });
                } catch (secondErr) {
                    console.warn('[Camera] Fallback to video:true:', secondErr);
                    this.stream = await navigator.mediaDevices.getUserMedia({
                        video: true,
                        audio: false
                    });
                }
            }

            this.video.srcObject = this.stream;

            // Wait for video to be ready and playing
            await new Promise((resolve) => {
                const onLoaded = async () => {
                    this.video.removeEventListener('loadedmetadata', onLoaded);
                    try {
                        await this.video.play();
                    } catch (playErr) {
                        console.warn('[Camera] Video play error:', playErr);
                    }
                    resolve();
                };

                if (this.video.readyState >= 1) {
                    onLoaded();
                } else {
                    this.video.addEventListener('loadedmetadata', onLoaded);
                }
            });

            // Get actual resolution
            this.frameWidth = this.video.videoWidth || 640;
            this.frameHeight = this.video.videoHeight || 480;
            this.captureCanvas.width = this.frameWidth;
            this.captureCanvas.height = this.frameHeight;

            this.isActive = true;

            // Populate device list now that permission is granted
            await this.getAvailableVideoDevices();

            console.log(`[Camera] Started: ${this.frameWidth}×${this.frameHeight} — Devices found: ${this.videoDevices.length}`);

            if (this.onStart) {
                this.onStart({
                    width: this.frameWidth,
                    height: this.frameHeight,
                    deviceCount: this.videoDevices.length,
                    currentLabel: this.getCameraLabel()
                });
            }

            return true;
        } catch (error) {
            console.error('[Camera] Error:', error);
            if (this.onError) {
                this.onError(error);
            }
            return false;
        }
    }

    /**
     * Aliases for start / stop
     */
    async start() {
        return await this.startCamera();
    }

    stop() {
        return this.stopCamera();
    }

    /**
     * Switch between all available cameras on device.
     */
    async switchCamera() {
        await this.getAvailableVideoDevices();

        if (this.videoDevices.length > 1) {
            this.currentDeviceIndex = (this.currentDeviceIndex + 1) % this.videoDevices.length;
            this.currentDeviceId = this.videoDevices[this.currentDeviceIndex].deviceId;
            console.log(`[Camera] Cycled to device [${this.currentDeviceIndex + 1}/${this.videoDevices.length}]`);
        } else {
            // Toggle between environment and user
            this.facingMode = (this.facingMode === 'environment') ? 'user' : 'environment';
            this.currentDeviceId = null;
            console.log(`[Camera] Toggled facing mode to: ${this.facingMode}`);
        }

        if (this.isActive) {
            const wasCapturing = !!this.captureInterval;
            const currentFps = this.analysisFPS;
            const currentQuality = this.jpegQuality;

            this.stopCamera();
            const started = await this.startCamera();
            if (started && wasCapturing) {
                this.startCapture(currentFps, currentQuality);
            }
        }
        return this.getCameraLabel();
    }

    async switchFacingMode() {
        return await this.switchCamera();
    }

    getCameraLabel() {
        if (this.videoDevices.length > 1 && this.videoDevices[this.currentDeviceIndex]) {
            const dev = this.videoDevices[this.currentDeviceIndex];
            if (dev.label) {
                return dev.label.length > 18 ? dev.label.substring(0, 18) + '…' : dev.label;
            }
            return `Cámara ${this.currentDeviceIndex + 1}`;
        }
        return this.facingMode === 'environment' ? 'Trasera' : 'Frontal';
    }

    /**
     * Toggle fullscreen on the given element or camera container.
     */
    toggleFullscreen(element) {
        element = element || document.getElementById('camera-container');
        if (!element) return false;

        const isFullscreen = !!(document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement);
        if (!isFullscreen) {
            if (element.requestFullscreen) {
                element.requestFullscreen();
            } else if (element.webkitRequestFullscreen) {
                element.webkitRequestFullscreen();
            } else if (element.mozRequestFullScreen) {
                element.mozRequestFullScreen();
            } else if (element.msRequestFullscreen) {
                element.msRequestFullscreen();
            }
            return true;
        } else {
            if (document.exitFullscreen) {
                document.exitFullscreen();
            } else if (document.webkitExitFullscreen) {
                document.webkitExitFullscreen();
            } else if (document.mozCancelFullScreen) {
                document.mozCancelFullScreen();
            } else if (document.msExitFullscreen) {
                document.msExitFullscreen();
            }
            return false;
        }
    }

    /**
     * Stop the camera stream.
     */
    stopCamera() {
        this.stopCapture();

        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }

        if (this.video) {
            this.video.srcObject = null;
        }
        this.isActive = false;

        console.log('[Camera] Stopped');
        if (this.onStop) {
            this.onStop();
        }
    }

    /**
     * Start capturing frames at the configured FPS.
     */
    startCapture(fps, quality) {
        if (typeof fps === 'number' && fps > 0) {
            this.setAnalysisFPS(fps);
        }
        if (typeof quality === 'number' && quality > 0) {
            this.setQuality(quality);
        }

        if (!this.isActive) {
            console.warn('[Camera] Cannot start capture: camera not active');
            return false;
        }

        this.stopCapture();  // Clear any existing interval

        const intervalMs = Math.round(1000 / this.analysisFPS);

        this.captureInterval = setInterval(() => {
            this._captureFrame();
        }, intervalMs);

        console.log(`[Camera] Capturing at ${this.analysisFPS} FPS (${intervalMs}ms interval)`);
        return true;
    }

    /**
     * Stop frame capture (but keep camera running).
     */
    stopCapture() {
        if (this.captureInterval) {
            clearInterval(this.captureInterval);
            this.captureInterval = null;
        }
    }

    pauseCapture() {
        this.stopCapture();
    }

    resumeCapture() {
        this.startCapture();
    }

    /**
     * Trigger immediate frame capture (used by adaptive lockstep streaming).
     */
    captureNow() {
        if (!this.isActive || !this.video || !this.video.videoWidth) return false;
        this._captureFrame();
        return true;
    }

    /**
     * Capture a single frame and invoke the onFrame callback.
     * Uses 384px max dimension and 0.50 quality to produce ultra-compact (~8-10 KB)
     * JPEG blobs that upload in <6ms for buttery smooth real-time performance.
     */
    _captureFrame() {
        if (!this.isActive || !this.video || !this.video.videoWidth || !this.video.videoHeight) return;

        const vW = this.video.videoWidth;
        const vH = this.video.videoHeight;
        const maxDim = 384;

        let cW = vW;
        let cH = vH;
        if (cW > maxDim || cH > maxDim) {
            if (cW >= cH) {
                cH = Math.round((vH * maxDim) / vW);
                cW = maxDim;
            } else {
                cW = Math.round((vW * maxDim) / vH);
                cH = maxDim;
            }
        }

        if (this.captureCanvas.width !== cW || this.captureCanvas.height !== cH) {
            this.captureCanvas.width = cW;
            this.captureCanvas.height = cH;
        }

        // Draw downscaled frame to offscreen canvas
        this.captureCtx.drawImage(this.video, 0, 0, cW, cH);

        // Convert to compact JPEG Blob (~8-10KB)
        this.captureCanvas.toBlob(
            (blob) => {
                if (blob && this.onFrame) {
                    this.onFrame(blob);
                }
            },
            'image/jpeg',
            0.50
        );
    }

    /**
     * Set analysis FPS.
     */
    setAnalysisFPS(fps) {
        this.analysisFPS = Math.max(1, Math.min(30, fps));
        
        // Restart capture if currently capturing
        if (this.captureInterval) {
            this.startCapture();
        }
    }

    /**
     * Set JPEG quality (0.0 - 1.0).
     */
    setQuality(quality) {
        this.jpegQuality = Math.max(0.1, Math.min(1.0, quality));
    }

    setJPEGQuality(quality) {
        this.setQuality(quality);
    }

    /**
     * Get current video dimensions (for overlay canvas sizing).
     */
    getVideoDimensions(customElement) {
        const replayEl = document.getElementById('replay-video');
        const isReplaying = replayEl && !replayEl.classList.contains('hidden');
        const target = customElement || (isReplaying ? replayEl : this.video);
        if (!target) return { width: 0, height: 0, renderWidth: 0, renderHeight: 0, offsetX: 0, offsetY: 0 };

        const rect = target.getBoundingClientRect();
        const vW = (target.videoWidth && target.videoWidth > 0) ? target.videoWidth : this.frameWidth;
        const vH = (target.videoHeight && target.videoHeight > 0) ? target.videoHeight : this.frameHeight;
        const videoAspect = vW / (vH || 1);
        const containerAspect = rect.width / (rect.height || 1);

        let renderWidth, renderHeight, offsetX, offsetY;

        if (containerAspect > videoAspect) {
            // Container is wider — video is height-constrained
            renderHeight = rect.height;
            renderWidth = renderHeight * videoAspect;
            offsetX = (rect.width - renderWidth) / 2;
            offsetY = 0;
        } else {
            // Container is taller — video is width-constrained
            renderWidth = rect.width;
            renderHeight = renderWidth / videoAspect;
            offsetX = 0;
            offsetY = (rect.height - renderHeight) / 2;
        }

        return {
            containerWidth: rect.width,
            containerHeight: rect.height,
            renderWidth,
            renderHeight,
            offsetX,
            offsetY,
            videoWidth: vW,
            videoHeight: vH,
        };
    }

    /**
     * Start recording the camera stream into a video file (WebM / MP4)
     */
    startVideoRecording() {
        if (!this.stream) {
            console.warn('[Camera] Cannot record: no active stream');
            return false;
        }

        try {
            this.recordedChunks = [];
            let options = {};

            // Prioritize mp4 for iOS Safari, webm for Chrome/Firefox
            const candidates = [
                'video/mp4',
                'video/webm;codecs=vp9',
                'video/webm;codecs=vp8',
                'video/webm'
            ];

            if (typeof MediaRecorder !== 'undefined') {
                for (const m of candidates) {
                    if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) {
                        options = { mimeType: m };
                        break;
                    }
                }
            }

            try {
                this.mediaRecorder = new MediaRecorder(this.stream, options);
            } catch (err) {
                console.warn('[Camera] MediaRecorder with options failed, using browser default:', err);
                this.mediaRecorder = new MediaRecorder(this.stream);
            }

            this.mediaRecorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) {
                    this.recordedChunks.push(e.data);
                }
            };

            // Start with 1000ms timeslices so chunks accumulate every second
            try {
                this.mediaRecorder.start(1000);
            } catch (err) {
                this.mediaRecorder.start();
            }

            this.isRecordingVideo = true;
            console.log(`[Camera] Video recording started: ${this.mediaRecorder.mimeType || 'native'}`);
            return true;
        } catch (e) {
            console.error('[Camera] Failed to start MediaRecorder:', e);
            this.isRecordingVideo = false;
            return false;
        }
    }

    /**
     * Stop recording and return the video Blob
     */
    stopVideoRecording() {
        return new Promise((resolve) => {
            if (!this.mediaRecorder || this.mediaRecorder.state === 'inactive') {
                this.isRecordingVideo = false;
                const blob = (this.recordedChunks && this.recordedChunks.length > 0)
                    ? new Blob(this.recordedChunks, { type: 'video/mp4' })
                    : null;
                this.recordedChunks = [];
                resolve(blob && blob.size > 0 ? blob : null);
                return;
            }

            let resolved = false;
            const finalize = () => {
                if (resolved) return;
                resolved = true;
                const mimeType = (this.mediaRecorder && this.mediaRecorder.mimeType) || 'video/mp4';
                const blob = new Blob(this.recordedChunks, { type: mimeType });
                console.log(`[Camera] Video recording finished: ${(blob.size / 1024 / 1024).toFixed(2)} MB (${mimeType}, chunks: ${this.recordedChunks.length})`);
                this.recordedChunks = [];
                this.isRecordingVideo = false;
                resolve(blob.size > 0 ? blob : null);
            };

            this.mediaRecorder.onstop = () => {
                // Wait 250ms for WebKit to flush any remaining ondataavailable chunks into array
                setTimeout(finalize, 250);
            };

            // Safety timeout
            setTimeout(finalize, 3000);

            try {
                this.mediaRecorder.stop();
            } catch (e) {
                console.warn('[Camera] mediaRecorder.stop() error:', e);
                setTimeout(finalize, 150);
            }
        });
    }
}

// Export as global
window.CameraManager = CameraManager;
