// FPV Interface - простой и надежный клиент

class FPVInterface {
    constructor() {
        // API endpoints - теперь все на одном порту
        this.API_BASE = 'http://' + window.location.hostname + ':' + window.location.port;
        
        // Состояние
        this.isPlaying = false;
        this.updateInterval = null;
        this.lastMode = null;
        this.scanResultsCheckInterval = null;
        
        // Элементы интерфейса
        this.initElements();
        this.initChart();
        this.initMap();
        this.initEventHandlers();
        this.initVideo();
        
        // Начинаем обновление статуса
        this.startStatusUpdates();
        
        console.log('FPV Interface initialized');
        console.log('API Base:', this.API_BASE);
    }
    
    initElements() {
        // Данные телеметрии
        this.rssiA = document.getElementById('rssiA');
        this.rssiB = document.getElementById('rssiB');
        this.angle = document.getElementById('angle');
        this.statusIcon = document.getElementById('statusIcon');
        this.statusText = document.getElementById('statusText');
        
        // Кнопки управления
        this.leftBtn = document.getElementById('leftBtn');
        this.rightBtn = document.getElementById('rightBtn');
        this.homeBtn = document.getElementById('homeBtn');
        this.autoBtn = document.getElementById('autoBtn');
        this.scanBtn = document.getElementById('scanBtn');
        this.calibrateBtn = document.getElementById('calibrateBtn');
        
        // Видео
        this.playPauseBtn = document.getElementById('playPauseBtn');
        this.fullscreenBtn = document.getElementById('fullscreenBtn');
        this.videoElement = document.getElementById('videoElement');
        
        // Статус сканирования
        this.scanStatus = document.getElementById('scanStatus');
        this.maxAngle = document.getElementById('maxAngle');
        
        console.log('Elements initialized');
    }
    
    initChart() {
        const ctx = document.getElementById('scanChart').getContext('2d');
        this.scanChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'RSSI Total',
                    data: [],
                    borderColor: '#00aaff',
                    backgroundColor: 'rgba(0, 170, 255, 0.1)',
                    tension: 0.4,
                    fill: true,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { 
                    legend: { display: false },
                    title: {
                        display: true,
                        text: 'RSSI распределение по углам',
                        color: '#e0e0e0'
                    }
                },
                scales: {
                    x: {
                        title: { 
                            display: true, 
                            text: 'Угол (°)', 
                            color: '#e0e0e0' 
                        },
                        ticks: { color: '#e0e0e0' },
                        grid: { color: 'rgba(255, 255, 255, 0.1)' }
                    },
                    y: {
                        title: { 
                            display: true, 
                            text: 'RSSI (сумма A+B)', 
                            color: '#e0e0e0' 
                        },
                        ticks: { color: '#e0e0e0' },
                        grid: { color: 'rgba(255, 255, 255, 0.1)' }
                    }
                }
            }
        });
    }
    
    initMap() {
        // Простая карта на Bangalore
        this.map = L.map('map', {
            attributionControl: false
        }).setView([12.9716, 77.5946], 13);
        
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '',
            maxZoom: 19
        }).addTo(this.map);
        
        // Маркеры
        this.antennaMarker = L.marker([12.9716, 77.5946])
            .addTo(this.map)
            .bindPopup('Антенна');
            
        this.droneMarker = L.marker([12.9816, 77.6046])
            .addTo(this.map)
            .bindPopup('Дрон');
    }
    
    initEventHandlers() {
        // Кнопки управления антенной
        this.leftBtn.addEventListener('click', () => {
            console.log('Left button clicked');
            this.sendCommand('left');
        });
        
        this.rightBtn.addEventListener('click', () => {
            console.log('Right button clicked');
            this.sendCommand('right');
        });
        
        this.homeBtn.addEventListener('click', () => {
            console.log('Home button clicked');
            this.sendCommand('home');
        });
        
        // Кнопка Auto
        this.autoBtn.addEventListener('click', () => {
            const isActive = this.autoBtn.classList.contains('active');
            console.log('Auto button clicked, current state:', isActive);
            this.sendCommand(isActive ? 'manual' : 'auto');
        });
        
        // Кнопка сканирования
        this.scanBtn.addEventListener('click', () => {
            const isScanning = this.scanBtn.classList.contains('active');
            console.log('Scan button clicked, scanning:', isScanning);
            if (!isScanning) {
                this.sendCommand('scan');
                // Начинаем проверку результатов сканирования
                this.startScanResultsCheck();
            } else {
                this.sendCommand('manual'); // Прерываем сканирование
                this.stopScanResultsCheck();
            }
        });
        
        // Кнопка калибровки
        this.calibrateBtn.addEventListener('click', () => {
            console.log('Calibrate button clicked');
            this.startCalibration();
        });
        
        // Видео кнопки
        this.playPauseBtn.addEventListener('click', () => this.togglePlayPause());
        this.fullscreenBtn.addEventListener('click', () => this.toggleFullscreen());
    }
    
    initVideo() {
        // Поднимаем WebRTC (WHEP) плеер для MediaMTX
        this.webrtc = {
            pc: null,
            started: false
        };

        // Автовоспроизведение при загрузке
        this.startWebRTC().catch((err) => {
            console.error('WebRTC start error:', err);
            this.isPlaying = false;
            this.updatePlayButton();
        });
    }

    buildWhepUrl() {
        // Прокси на том же origin, формат пути как в примере: /<path>/whep
        return `${window.location.origin}/mystream/whep`;
    }

    async startWebRTC() {
        // Если уже запущено — ничего не делаем
        if (this.webrtc && this.webrtc.started) return;

        // Создаем RTCPeerConnection
        const pc = new RTCPeerConnection({
            // iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });

        // Примем и установим медиапоток на <video>
        pc.ontrack = (event) => {
            if (this.videoElement.srcObject !== event.streams[0]) {
                this.videoElement.srcObject = event.streams[0];
            }
        };

        pc.onconnectionstatechange = () => {
            const state = pc.connectionState;
            if (state === 'connected') {
                this.isPlaying = true;
                this.updatePlayButton();
            } else if (state === 'failed' || state === 'disconnected' || state === 'closed') {
                this.isPlaying = false;
                this.updatePlayButton();
            }
        };

        // Запрашиваем только прием потоков
        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.addTransceiver('audio', { direction: 'recvonly' });

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        // Дожидаемся завершения ICE-гатеринга перед отправкой (non-trickle)
        await new Promise((resolve) => {
            if (pc.iceGatheringState === 'complete') {
                resolve();
            } else {
                const check = () => {
                    if (pc.iceGatheringState === 'complete') {
                        pc.removeEventListener('icegatheringstatechange', check);
                        resolve();
                    }
                };
                pc.addEventListener('icegatheringstatechange', check);
                setTimeout(() => {
                    pc.removeEventListener('icegatheringstatechange', check);
                    resolve();
                }, 1500);
            }
        });

        const whepUrl = this.buildWhepUrl();

        // Основной путь: WHEP application/sdp
        let ok = false;
        try {
            const resp = await fetch(whepUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/sdp',
                    'Accept': 'application/sdp'
                },
                body: pc.localDescription && pc.localDescription.sdp ? pc.localDescription.sdp : offer.sdp
            });

            if (!resp.ok) throw new Error(`WHEP POST failed: ${resp.status}`);
            const answerSdp = await resp.text();
            await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });
            ok = true;
        } catch (e) {
            console.warn('WHEP application/sdp failed, trying legacy form body...', e);
        }

        // Резервный путь: form POST data=btoa(sdp)
        if (!ok) {
            const resp = await fetch(whepUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({ data: btoa(offer.sdp) })
            });
            if (!resp.ok) throw new Error(`Legacy WHEP POST failed: ${resp.status}`);
            const answerText = await resp.text();
            const answerSdp = atob(answerText);
            await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });
        }

        // Пытаемся запустить воспроизведение
        try {
            await this.videoElement.play();
        } catch (err) {
            console.log('Autoplay blocked, waiting for user gesture');
        }

        this.webrtc.pc = pc;
        this.webrtc.started = true;
        this.isPlaying = true;
        this.updatePlayButton();
        console.log('WebRTC started');
    }

    async stopWebRTC() {
        if (!this.webrtc || !this.webrtc.started) return;
        try {
            if (this.webrtc.pc) {
                this.webrtc.pc.getSenders().forEach(s => { try { s.track && s.track.stop(); } catch (_) {} });
                this.webrtc.pc.getReceivers().forEach(r => { try { r.track && r.track.stop(); } catch (_) {} });
                this.webrtc.pc.close();
            }
        } catch (e) {
            console.warn('Error stopping WebRTC:', e);
        }
        this.webrtc.pc = null;
        this.webrtc.started = false;
        if (this.videoElement) this.videoElement.srcObject = null;
        this.isPlaying = false;
        this.updatePlayButton();
        console.log('WebRTC stopped');
    }
    
    async sendCommand(command) {
        try {
            console.log(`Sending command: ${command}`);
            const response = await fetch(`${this.API_BASE}/command`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ command })
            });
            
            const result = await response.json();
            console.log('Command response:', result);
            
            if (!result.success) {
                console.error('Command failed:', result.error);
            }
        } catch (error) {
            console.error('Error sending command:', error);
        }
    }
    
    async getStatus() {
        try {
            const response = await fetch(`${this.API_BASE}/status`);
            if (!response.ok) throw new Error('Status request failed');
            
            const status = await response.json();
            this.updateUI(status);
            this.updateConnectionStatus('online');
        } catch (error) {
            console.error('Error getting status:', error);
            this.updateConnectionStatus('offline');
        }
    }
    
    async getScanResults() {
        try {
            const response = await fetch(`${this.API_BASE}/scan-results`);
            const results = await response.json();
            
            if (results && results.scan_complete) {
                console.log('Got scan results:', results);
                this.displayScanResults(results);
                this.stopScanResultsCheck();
            }
        } catch (error) {
            console.error('Error getting scan results:', error);
        }
    }
    
    updateUI(status) {
        if (!status) return;
        
        // Обновляем телеметрию
        this.rssiA.textContent = Math.round(status.rssi_a || 0);
        this.rssiB.textContent = Math.round(status.rssi_b || 0);
        
        // Используем уже рассчитанный угол
        const angle = status.angle_degrees || 0;
        this.angle.textContent = `${angle}°`;
        
        // Обновляем состояние кнопок и статус
        const mode = status.mode || 'manual';
        
        // Обновляем только если режим изменился
        if (mode !== this.lastMode) {
            console.log(`Mode changed: ${this.lastMode} -> ${mode}`);
            this.lastMode = mode;
            
            // Auto button
            if (mode === 'auto') {
                this.autoBtn.classList.add('active');
            } else {
                this.autoBtn.classList.remove('active');
            }
            
            // Scan button и статус
            if (mode === 'scan') {
                this.scanBtn.classList.add('active');
                this.scanBtn.querySelector('span:last-child').textContent = 'Stop Scan';
                this.scanStatus.textContent = 'Сканирование...';
                this.scanStatus.classList.add('active');
            } else {
                this.scanBtn.classList.remove('active');
                this.scanBtn.querySelector('span:last-child').textContent = 'Start Scan';
                
                if (mode === 'auto') {
                    this.scanStatus.textContent = 'Авто режим';
                    this.scanStatus.classList.remove('active');
                } else if (mode === 'calibrate_min' || mode === 'calibrate_max') {
                    this.scanStatus.textContent = 'Калибровка...';
                    this.scanStatus.classList.add('active');
                } else {
                    this.scanStatus.textContent = 'Ручной режим';
                    this.scanStatus.classList.remove('active');
                }
            }
            
            // Калибровка
            if (mode === 'calibrate_min' || mode === 'calibrate_max') {
                this.calibrateBtn.classList.add('active');
                this.calibrateBtn.querySelector('span:last-child').textContent = 'Калибровка...';
            } else {
                this.calibrateBtn.classList.remove('active');
                this.calibrateBtn.querySelector('span:last-child').textContent = 'Calibrate';
            }
        }
    }
    
    updateConnectionStatus(status) {
        this.statusIcon.classList.remove('online', 'offline', 'warning');
        this.statusText.classList.remove('online', 'offline', 'warning');
        
        this.statusIcon.classList.add(status);
        this.statusText.classList.add(status);
        
        if (status === 'online') {
            this.statusIcon.textContent = 'wifi';
            this.statusText.textContent = 'Online';
        } else {
            this.statusIcon.textContent = 'wifi_off';
            this.statusText.textContent = 'Offline';
        }
    }
    
    displayScanResults(results) {
        console.log('Displaying scan results');
        
        // Обновляем лучший угол
        if (results.best_angle !== undefined) {
            this.maxAngle.textContent = `${results.best_angle}°`;
        }
        
        // Очищаем и заполняем график
        this.scanChart.data.labels = [];
        this.scanChart.data.datasets[0].data = [];
        
        if (results.scan_data && results.scan_data.length > 0) {
            results.scan_data.forEach(point => {
                this.scanChart.data.labels.push(`${point.angle}°`);
                this.scanChart.data.datasets[0].data.push(point.rssi);
            });
            
            this.scanChart.update();
            console.log(`Chart updated with ${results.scan_data.length} points`);
        }
    }
    
    startScanResultsCheck() {
        // Проверяем результаты сканирования каждую секунду
        this.scanResultsCheckInterval = setInterval(() => {
            this.getScanResults();
        }, 1000);
    }
    
    stopScanResultsCheck() {
        if (this.scanResultsCheckInterval) {
            clearInterval(this.scanResultsCheckInterval);
            this.scanResultsCheckInterval = null;
        }
    }
    
    async startCalibration() {
        // Шаг 1: Калибровка минимума
        const step1 = confirm(
            'КАЛИБРОВКА - ШАГ 1: Минимум сигнала\n\n' +
            '1. Снимите обе антенны с приемников\n' +
            '2. Нажмите OK для начала калибровки минимума\n' +
            '3. Процесс займет ~8 секунд\n\n' +
            'Продолжить?'
        );
        
        if (!step1) return;
        
        // Запускаем калибровку минимума
        await this.sendCommand('calibrate');
        
        // Ждем завершения калибровки минимума
        await this.waitForCalibrationComplete();
        
        // Шаг 2: Калибровка максимума
        const step2 = confirm(
            'КАЛИБРОВКА - ШАГ 2: Максимум сигнала\n\n' +
            '1. Установите антенны обратно\n' +
            '2. Включите дрон и передатчик\n' +
            '3. Расположите дрон на расстоянии 1-2 метра\n' +
            '4. Нажмите OK для калибровки максимума\n\n' +
            'Продолжить?'
        );
        
        if (!step2) return;
        
        // Запускаем калибровку максимума
        await this.sendCommand('calibrate_max');
    }
    
    async waitForCalibrationComplete() {
        // Ждем пока калибровка не завершится
        return new Promise((resolve) => {
            const checkInterval = setInterval(async () => {
                try {
                    const response = await fetch(`${this.API_BASE}/status`);
                    const status = await response.json();
                    
                    if (status.mode !== 'calibrate_min' && status.mode !== 'calibrate_max') {
                        clearInterval(checkInterval);
                        resolve();
                    }
                } catch (error) {
                    console.error('Error checking calibration status:', error);
                }
            }, 1000);
        });
    }
    
    togglePlayPause() {
        if (!this.videoElement) return;

        if (this.isPlaying) {
            // Остановить WebRTC
            this.stopWebRTC();
        } else {
            // Запустить WebRTC
            this.startWebRTC().catch((err) => {
                console.error('Video play error:', err);
            });
        }
        // Мгновенное обновление UI
        this.updatePlayButton();
    }
    
    updatePlayButton() {
        const icon = this.playPauseBtn.querySelector('.material-icons');
        if (icon) {
            icon.textContent = this.isPlaying ? 'pause' : 'play_arrow';
        }
    }
    
    toggleFullscreen() {
        const container = this.videoElement.parentElement;
        
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else {
            container.requestFullscreen().catch(console.error);
        }
    }
    
    startStatusUpdates() {
        // Обновляем статус каждые 200мс
        this.updateInterval = setInterval(() => {
            this.getStatus();
        }, 200);
        
        // Сразу запрашиваем статус
        this.getStatus();
    }
    
    destroy() {
        // Очистка при уничтожении
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
        }
        if (this.scanResultsCheckInterval) {
            clearInterval(this.scanResultsCheckInterval);
        }
    }
}

// Инициализация при загрузке страницы
let fpvInterface = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, initializing FPV Interface...');
    fpvInterface = new FPVInterface();
});