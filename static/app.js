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
        this.initVtxControls();
        this.vtxEditing = false;
        this.vtxEditingResetTimer = null;
        
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
        
        // Video scan
        this.videoScanBtn = document.getElementById('videoScanBtn');

        // Видео
        this.playPauseBtn = document.getElementById('playPauseBtn');
        this.fullscreenBtn = document.getElementById('fullscreenBtn');
        this.videoElement = document.getElementById('videoElement');

        // VTX controls
        this.bandSelect = document.getElementById('bandSelect');
        this.channelSelect = document.getElementById('channelSelect');
        this.setFreqBtn = document.getElementById('setFreqBtn');
        this.currentFreqEl = document.getElementById('currentFreq');
        this.currentBandChannelEl = document.getElementById('currentBandChannel');
        
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

        // VTX controls
        this.bandSelect.addEventListener('change', () => {
            this.startVtxEditing();
            this.populateChannelOptions();
            this.scheduleVtxEditingReset();
        });
        this.channelSelect.addEventListener('change', () => {
            this.startVtxEditing();
            this.scheduleVtxEditingReset();
        });

        // Mark editing on user interactions to prevent polling from overriding
        ['focus', 'mousedown', 'input'].forEach(ev => {
            this.bandSelect.addEventListener(ev, () => this.startVtxEditing());
            this.channelSelect.addEventListener(ev, () => this.startVtxEditing());
        });

        this.setFreqBtn.addEventListener('click', () => this.applySelectedVtx());

        // Video scan button
        this.videoScanBtn.addEventListener('click', () => this.startVideoScan());
    }

    initVtxControls() {
        // Frequency table
        this.freqTable = {
            A: [5865, 5845, 5825, 5805, 5785, 5765, 5745, 5725],
            B: [5733, 5752, 5771, 5790, 5809, 5828, 5847, 5866],
            E: [5705, 5685, 5665, 5645, 5885, 5905, 5925, 5945],
            F: [5740, 5760, 5780, 5800, 5820, 5840, 5860, 5880],
            R: [5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917],
            L: [5362, 5399, 5436, 5473, 5510, 5547, 5584, 5621]
        };

        // Populate default
        this.populateChannelOptions();

        // Build VTX grid structure
        this.buildVtxGrid();
    }

    buildVtxGrid() {
        const container = document.getElementById('vtxGrid');
        if (!container) return;
        const bands = ['A','B','E','F','R','L'];
        const table = document.createElement('table');
        const thead = document.createElement('thead');
        const headRow = document.createElement('tr');
        const th0 = document.createElement('th');
        th0.textContent = 'BAND/CH';
        headRow.appendChild(th0);
        for (let i = 1; i <= 8; i++) {
            const th = document.createElement('th');
            th.textContent = `CH ${i}`;
            headRow.appendChild(th);
        }
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        bands.forEach((b) => {
            const row = document.createElement('tr');
            const bandCell = document.createElement('th');
            bandCell.textContent = b;
            row.appendChild(bandCell);
            this.freqTable[b].forEach((mhz, idx) => {
                const td = document.createElement('td');
                td.className = 'cell';
                td.dataset.band = b;
                td.dataset.channel = String(idx + 1);
                td.textContent = `${mhz}`;
                row.appendChild(td);
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);

        // Clear and add
        container.innerHTML = '';
        container.appendChild(table);
    }

    populateChannelOptions() {
        const band = this.bandSelect.value;
        const freqs = this.freqTable[band] || [];
        this.channelSelect.innerHTML = '';
        freqs.forEach((mhz, idx) => {
            const opt = document.createElement('option');
            opt.value = String(idx + 1);
            opt.textContent = `CH ${idx + 1} — ${mhz} MHz`;
            this.channelSelect.appendChild(opt);
        });
    }

    async applySelectedVtx() {
        const band = this.bandSelect.value;
        const channel = parseInt(this.channelSelect.value || '1', 10);
        try {
            const resp = await fetch(`${this.API_BASE}/vtx`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ band, channel })
            });
            if (!resp.ok) throw new Error(`VTX set failed: ${resp.status}`);
            const data = await resp.json();
            if (data.success) {
                this.updateVtxUI(data.vtx || {});
                this.vtxEditing = false;
                if (this.vtxEditingResetTimer) {
                    clearTimeout(this.vtxEditingResetTimer);
                    this.vtxEditingResetTimer = null;
                }
            }
        } catch (e) {
            console.error('Error setting VTX:', e);
        }
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
        
        // VTX info
        if (status.vtx) {
            this.updateVtxUI(status.vtx);
        }

        // Update scan status label for video scan
        if (status.vtx_scan && typeof status.vtx_scan.in_progress === 'boolean') {
            if (status.vtx_scan.in_progress) {
                this.scanStatus.textContent = 'Video scanning...';
                this.scanStatus.classList.add('active');
            } else if (this.scanStatus.textContent === 'Video scanning...') {
                this.scanStatus.textContent = 'Video scan done';
                this.scanStatus.classList.remove('active');
            }
        }

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

    async startVideoScan() {
        try {
            // Clear any highlight
            const container = document.getElementById('vtxGrid');
            if (container) {
                container.querySelectorAll('.cell').forEach(c => c.classList.remove('active'));
            }
            const resp = await fetch(`${this.API_BASE}/vtx-scan`, { method: 'POST' });
            const data = await resp.json();
            if (!data.success) throw new Error('Failed to start VTX scan');
            this.scanStatus.textContent = 'Video scanning...';
            this.scanStatus.classList.add('active');
        } catch (e) {
            console.error('Video scan start error:', e);
        }
    }

    updateVtxUI(vtx) {
        const mhz = vtx.frequency_mhz || vtx.frequency || null;
        const band = vtx.band || '-';
        const ch = vtx.channel || '-';
        if (mhz) this.currentFreqEl.textContent = mhz;
        this.currentBandChannelEl.textContent = `Band: ${band} / CH: ${ch}`;
        // Avoid overriding user's selection while editing
        if (!this.vtxEditing) {
            if (this.bandSelect && typeof band === 'string' && this.bandSelect.value !== band) {
                this.bandSelect.value = band;
                this.populateChannelOptions();
            }
            if (this.channelSelect && (typeof ch === 'number' || (typeof ch === 'string' && ch !== '-'))) {
                this.channelSelect.value = String(ch);
            }
        }

        // Highlight active cell in the grid to reflect current active frequency
        try {
            const container = document.getElementById('vtxGrid');
            if (container && band && ch) {
                container.querySelectorAll('.cell').forEach(c => c.classList.remove('active'));
                const sel = `.cell[data-band="${band}"][data-channel="${String(ch)}"]`;
                const cur = container.querySelector(sel);
                if (cur) cur.classList.add('active');
            }
        } catch (e) {}
    }

    startVtxEditing() {
        this.vtxEditing = true;
        if (this.vtxEditingResetTimer) {
            clearTimeout(this.vtxEditingResetTimer);
            this.vtxEditingResetTimer = null;
        }
    }

    scheduleVtxEditingReset() {
        if (this.vtxEditingResetTimer) clearTimeout(this.vtxEditingResetTimer);
        this.vtxEditingResetTimer = setTimeout(() => {
            this.vtxEditing = false;
            this.vtxEditingResetTimer = null;
        }, 1500);
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