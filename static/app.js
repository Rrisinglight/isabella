// FPV Interface JavaScript

class FPVInterface {
    constructor() {
        this.socket = io();
        this.scanInProgress = false;
        this.isConnected = false;
        this.lastDataTime = Date.now();
        this.isPlaying = false;
        
        this.initElements();
        this.initMap();
        this.initChart();
        this.initSocketEvents();
        this.initButtonEvents();
        this.initVideo();
        
        // Status check interval
        setInterval(() => this.checkConnectionStatus(), 1000);
        
        console.log('FPV Interface initialized');
    }

    initElements() {
        // Data elements
        this.rssiA = document.getElementById('rssiA');
        this.rssiB = document.getElementById('rssiB');
        this.angle = document.getElementById('angle');
        this.statusIcon = document.getElementById('statusIcon');
        this.statusText = document.getElementById('statusText');
        
        // Control buttons
        this.autoBtn = document.getElementById('autoBtn');
        this.leftBtn = document.getElementById('leftBtn');
        this.rightBtn = document.getElementById('rightBtn');
        this.scanBtn = document.getElementById('scanBtn');
        
        // Video controls
        this.playPauseBtn = document.getElementById('playPauseBtn');
        this.fullscreenBtn = document.getElementById('fullscreenBtn');
        this.videoElement = document.getElementById('videoElement');
        
        // Scan elements
        this.scanStatus = document.getElementById('scanStatus');
        this.maxAngle = document.getElementById('maxAngle');
        
        // Verify elements exist
        if (!this.autoBtn || !this.leftBtn || !this.rightBtn) {
            console.error('CRITICAL: Control buttons not found!');
            console.error('Auto button:', this.autoBtn);
            console.error('Left button:', this.leftBtn);  
            console.error('Right button:', this.rightBtn);
            
            // Try to show user-friendly error
            setTimeout(() => {
                if (!this.autoBtn) {
                    alert('Error: Control buttons not found. Please refresh the page.');
                }
            }, 2000);
        }
        
        console.log('Elements initialized:', {
            autoBtn: !!this.autoBtn,
            leftBtn: !!this.leftBtn,
            rightBtn: !!this.rightBtn,
            scanBtn: !!this.scanBtn,
            videoElement: !!this.videoElement
        });
    }

    initMap() {
        // Dark themed map centered on Bangalore
        this.map = L.map('map').setView([12.9716, 77.5946], 13);
        
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap &copy; CARTO',
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(this.map);

        // Markers
        this.antennaMarker = L.marker([12.9716, 77.5946])
            .addTo(this.map)
            .bindPopup('Antenna Tracker - Bangalore');
            
        this.droneMarker = L.marker([12.9816, 77.6046])
            .addTo(this.map)
            .bindPopup('Drone Position');
    }

    initChart() {
        const ctx = document.getElementById('scanChart').getContext('2d');
        this.scanChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'RSSI',
                    data: [],
                    borderColor: '#00aaff',
                    backgroundColor: 'rgba(0, 170, 255, 0.1)',
                    tension: 0.4,
                    fill: true,
                    pointRadius: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        title: { display: true, text: 'Angle (°)', color: '#e0e0e0' },
                        ticks: { color: '#e0e0e0', maxTicksLimit: 6 },
                        grid: { color: 'rgba(255, 255, 255, 0.1)' }
                    },
                    y: {
                        title: { display: true, text: 'RSSI', color: '#e0e0e0' },
                        ticks: { color: '#e0e0e0' },
                        grid: { color: 'rgba(255, 255, 255, 0.1)' }
                    }
                }
            }
        });
    }

    initSocketEvents() {
        this.socket.on('connect', () => {
            console.log('Socket connected');
            this.isConnected = true;
            this.updateStatus('warning', 'Connected');
        });

        this.socket.on('disconnect', () => {
            console.log('Socket disconnected');
            this.isConnected = false;
            this.updateStatus('offline', 'Offline');
        });

        this.socket.on('telemetry', (data) => {
            this.lastDataTime = Date.now();
            this.updateTelemetry(data);
            this.updateStatus('online', 'Online');
        });

        this.socket.on('mode_update', (data) => {
            console.log('Mode update received:', data);
            this.updateAutoButton(data.auto_mode);
        });

        this.socket.on('rotate_response', (data) => {
            console.log('Rotate response:', data);
        });

        this.socket.on('scan_started', (data) => {
            console.log('Scan started:', data);
            if (data.success) {
                this.startScan();
            }
        });

        this.socket.on('scan_data_point', (data) => {
            this.addScanPoint(data);
        });

        this.socket.on('scan_complete', (data) => {
            this.completeScan(data);
        });

        this.socket.on('scan_stopped', (data) => {
            console.log('Scan stopped:', data);
            this.stopScan();
        });
    }

    initButtonEvents() {
        // Auto button
        if (this.autoBtn) {
            this.autoBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('Auto button clicked');
                
                const isActive = this.autoBtn.classList.contains('active');
                console.log('Current auto state:', isActive, 'Setting to:', !isActive);
                
                this.socket.emit('set_mode', { auto: !isActive });
            });
        }

        // Left button
        if (this.leftBtn) {
            this.leftBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('Left button clicked');
                
                if (!this.autoBtn.classList.contains('active')) {
                    console.log('Sending left command');
                    this.socket.emit('manual_rotate', { direction: 'left' });
                } else {
                    console.log('Auto mode active, ignoring left');
                }
            });
        }

        // Right button
        if (this.rightBtn) {
            this.rightBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('Right button clicked');
                
                if (!this.autoBtn.classList.contains('active')) {
                    console.log('Sending right command');
                    this.socket.emit('manual_rotate', { direction: 'right' });
                } else {
                    console.log('Auto mode active, ignoring right');
                }
            });
        }

        // Scan button
        if (this.scanBtn) {
            this.scanBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('Scan button clicked, scanInProgress:', this.scanInProgress);
                
                if (this.scanInProgress) {
                    console.log('Stopping scan');
                    this.socket.emit('stop_angle_scan');
                } else {
                    console.log('Starting scan');
                    this.socket.emit('start_angle_scan');
                }
            });
        }

        // Video controls
        if (this.playPauseBtn) {
            this.playPauseBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.togglePlayPause();
            });
        }

        if (this.fullscreenBtn) {
            this.fullscreenBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleFullscreen();
            });
        }
    }

    initVideo() {
        if (typeof mpegts !== 'undefined' && mpegts.isSupported()) {
            const player = mpegts.createPlayer({
                type: 'mse',
                isLive: true,
                url: '/live'
            });
            player.attachMediaElement(this.videoElement);
            player.load();
            this.videoElement.muted = true;
            this.videoPlayer = player;
        }
    }

    updateTelemetry(data) {
        if (this.rssiA) this.rssiA.textContent = Math.round(data.rssi_a);
        if (this.rssiB) this.rssiB.textContent = Math.round(data.rssi_b);
        if (this.angle) this.angle.textContent = `${data.angle.toFixed(1)}°`;
        this.updateAutoButton(data.auto_mode);
    }

    updateAutoButton(isActive) {
        if (!this.autoBtn) return;
        
        if (isActive) {
            this.autoBtn.classList.add('active');
        } else {
            this.autoBtn.classList.remove('active');
        }
        
        console.log('Auto button updated, active:', isActive);
    }

    updateStatus(level, text) {
        if (!this.statusIcon || !this.statusText) return;
        
        // Remove all status classes
        this.statusIcon.classList.remove('online', 'warning', 'offline');
        this.statusText.classList.remove('online', 'warning', 'offline');
        
        // Add current status
        this.statusIcon.classList.add(level);
        this.statusText.classList.add(level);
        
        // Update text and icon
        this.statusText.textContent = text;
        
        switch(level) {
            case 'online':
                this.statusIcon.textContent = 'wifi';
                break;
            case 'warning':
                this.statusIcon.textContent = 'wifi_tethering';
                break;
            case 'offline':
                this.statusIcon.textContent = 'wifi_off';
                break;
        }
    }

    checkConnectionStatus() {
        if (this.isConnected && Date.now() - this.lastDataTime > 5000) {
            this.updateStatus('warning', 'No Data');
        }
    }

    startScan() {
        this.scanInProgress = true;
        if (this.scanStatus) this.scanStatus.textContent = 'Scanning...';
        if (this.scanStatus) this.scanStatus.classList.add('active');
        if (this.scanBtn) {
            this.scanBtn.classList.add('active');
            this.scanBtn.querySelector('span:last-child').textContent = 'Stop Scan';
        }
        
        // Clear chart
        this.scanChart.data.labels = [];
        this.scanChart.data.datasets[0].data = [];
        this.scanChart.update();
    }

    addScanPoint(data) {
        this.scanChart.data.labels.push(data.angle.toFixed(0) + '°');
        this.scanChart.data.datasets[0].data.push(data.rssi);
        
        // Limit points
        if (this.scanChart.data.labels.length > 50) {
            this.scanChart.data.labels.shift();
            this.scanChart.data.datasets[0].data.shift();
        }
        
        this.scanChart.update('none');
    }

    completeScan(data) {
        this.stopScan();
        
        // Find max RSSI angle
        if (data.data && data.data.length > 0) {
            let maxRssi = 0;
            let maxAngleValue = 0;
            
            data.data.forEach(point => {
                if (point.rssi > maxRssi) {
                    maxRssi = point.rssi;
                    maxAngleValue = point.angle;
                }
            });
            
            if (this.maxAngle) {
                this.maxAngle.textContent = `${maxAngleValue.toFixed(0)}°`;
            }
        }
        
        if (this.scanStatus) this.scanStatus.textContent = 'Complete';
        
        // Reset status after delay
        setTimeout(() => {
            if (this.scanStatus) this.scanStatus.textContent = 'Idle';
        }, 3000);
    }

    stopScan() {
        this.scanInProgress = false;
        if (this.scanStatus) this.scanStatus.classList.remove('active');
        if (this.scanBtn) {
            this.scanBtn.classList.remove('active');
            this.scanBtn.querySelector('span:last-child').textContent = 'Start Scan';
        }
    }

    toggleFullscreen() {
        const container = this.videoElement.parentElement;
        
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else {
            container.requestFullscreen().catch(err => {
                console.error('Fullscreen error:', err);
            });
        }
    }

    togglePlayPause() {
        if (!this.videoElement || !this.playPauseBtn) return;
        
        const icon = this.playPauseBtn.querySelector('.material-icons');
        
        if (this.isPlaying) {
            // Currently playing, pause it
            this.videoElement.pause();
            this.isPlaying = false;
            icon.textContent = 'play_arrow';
            console.log('Video paused');
        } else {
            // Currently paused, play it
            if (this.videoPlayer) {
                this.videoPlayer.play();
            } else {
                this.videoElement.play();
            }
            this.isPlaying = true;
            icon.textContent = 'pause';
            console.log('Video playing');
        }
    }
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, initializing FPV Interface');
    new FPVInterface();
});