/**
 * Spatial Rhythm Observer — WebSocket Module
 * Handles real-time communication with the server.
 */

class WebSocketManager {
    constructor() {
        this.ws = null;
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 2000;  // ms
        this.reconnectTimer = null;

        // Callbacks
        this.onConnect = null;
        this.onDisconnect = null;
        this.onResult = null;    // Detection results
        this.onControl = null;   // Control messages
        this.onError = null;

        // Offline / Pending Control Message Queue
        this.messageQueue = [];

        // Stats
        this.messagesSent = 0;
        this.messagesReceived = 0;
        this.bytesSent = 0;
    }

    /**
     * Connect to the WebSocket server.
     */
    connect(url = null) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log('[WS] Already connected');
            return;
        }

        // Auto-detect server URL
        if (!url) {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const host = window.location.host;
            url = `${protocol}//${host}/ws/vision`;
        }

        console.log(`[WS] Connecting to ${url}...`);
        this._updateStatus('connecting');

        try {
            this.ws = new WebSocket(url);
            this.ws.binaryType = 'arraybuffer';

            this.ws.onopen = () => {
                this.isConnected = true;
                this.reconnectAttempts = 0;
                console.log('[WS] Connected');
                this._updateStatus('connected');

                // Flush any queued control messages (e.g. session_start, update_zones)
                while (this.messageQueue.length > 0) {
                    const queuedMsg = this.messageQueue.shift();
                    try {
                        console.log('[WS] Sending queued message:', queuedMsg.action);
                        this.ws.send(JSON.stringify(queuedMsg));
                    } catch (qe) {
                        console.warn('[WS] Error sending queued message:', qe);
                    }
                }

                if (this.onConnect) this.onConnect();
            };

            this.ws.onmessage = (event) => {
                this.messagesReceived++;
                this._handleMessage(event.data);
            };

            this.ws.onclose = (event) => {
                this.isConnected = false;
                console.log(`[WS] Disconnected (code: ${event.code})`);
                this._updateStatus('disconnected');

                if (this.onDisconnect) this.onDisconnect(event);

                // Auto-reconnect
                this._scheduleReconnect(url);
            };

            this.ws.onerror = (error) => {
                console.error('[WS] Error:', error);
                if (this.onError) this.onError(error);
            };

        } catch (error) {
            console.error('[WS] Connection failed:', error);
            this._updateStatus('disconnected');
            this._scheduleReconnect(url);
        }
    }

    /**
     * Disconnect from the server.
     */
    disconnect() {
        this._cancelReconnect();

        if (this.ws) {
            this.ws.onclose = null;  // Prevent reconnect
            this.ws.close();
            this.ws = null;
        }

        this.isConnected = false;
        this._updateStatus('disconnected');
    }

    /**
     * Get pending bytes in WebSocket buffer.
     */
    getBufferedAmount() {
        return (this.ws && this.ws.readyState === WebSocket.OPEN) ? this.ws.bufferedAmount : 0;
    }

    /**
     * Send a binary frame to the server.
     * Prevents bufferbloat: skips frame if network uplink is already saturated (>64KB buffered).
     */
    sendFrame(blob) {
        if (!this.isConnected || !this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
        
        // Skip frame if previous data is still queuing in network buffer
        if (this.ws.bufferedAmount > 65536) {
            return false;
        }

        blob.arrayBuffer().then(buffer => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                try {
                    this.ws.send(buffer);
                    this.messagesSent++;
                    this.bytesSent += buffer.byteLength;
                } catch (e) {
                    console.warn('[WS] Error sending binary frame:', e);
                }
            }
        }).catch(err => console.warn('[WS] arrayBuffer conversion error:', err));

        return true;
    }

    /**
     * Send a control message (JSON text).
     * If socket is not yet open, saves to messageQueue so it is not lost.
     */
    sendControl(data) {
        if (!this.isConnected || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
            console.log('[WS] Socket not open, queuing message:', data.action);
            this.messageQueue.push(data);
            return false;
        }

        try {
            this.ws.send(JSON.stringify(data));
            return true;
        } catch (e) {
            console.warn('[WS] Error sending control, queuing:', e);
            this.messageQueue.push(data);
            return false;
        }
    }

    /**
     * Reset the tracker state on the server.
     */
    resetTracking() {
        return this.sendControl({ action: 'reset' });
    }

    /**
     * Ping the server.
     */
    ping() {
        return this.sendControl({ action: 'ping' });
    }

    // ─── Private Methods ────────────────────────────────

    _handleMessage(data) {
        try {
            const message = JSON.parse(data);

            if (message.control) {
                // Control response
                if (this.onControl) this.onControl(message);
            } else if (message.persons !== undefined) {
                // Detection result
                if (this.onResult) this.onResult(message);
            }
        } catch (error) {
            console.warn('[WS] Failed to parse message:', error);
        }
    }

    _updateStatus(status) {
        const indicator = document.getElementById('connection-status');
        const text = indicator.querySelector('.status-text');

        indicator.className = `status-indicator ${status}`;

        switch (status) {
            case 'connected':
                text.textContent = 'Conectado';
                break;
            case 'connecting':
                text.textContent = 'Conectando...';
                break;
            case 'disconnected':
                text.textContent = 'Desconectado';
                break;
        }
    }

    _scheduleReconnect(url) {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('[WS] Max reconnection attempts reached');
            return;
        }

        this._cancelReconnect();

        const delay = this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts);
        this.reconnectAttempts++;

        console.log(`[WS] Reconnecting in ${Math.round(delay)}ms (attempt ${this.reconnectAttempts})`);

        this.reconnectTimer = setTimeout(() => {
            this.connect(url);
        }, delay);
    }

    _cancelReconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }
}

// Export as global
window.WebSocketManager = WebSocketManager;
