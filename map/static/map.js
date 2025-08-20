// Инициализация карты
let map = L.map('map').setView([55.7558, 37.6173], 10); // Москва по умолчанию

// Спутниковые подложки
const baseLayers = {
    'OpenStreetMap': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }),
    'Спутник (ESRI)': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: '© Esri'
    }),
    'Гибрид': L.tileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', {
        attribution: '© Google'
    }),
    'Топографическая': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenTopoMap'
    })
};

// Добавляем подложку по умолчанию
baseLayers['Спутник (ESRI)'].addTo(map);

// Добавляем контроль слоёв
L.control.layers(baseLayers).addTo(map);

// Глобальные переменные
let baseMarker = null;
let directionLine = null;
let currentDirectionLine = null;
let leftBoundaryLine = null;
let rightBoundaryLine = null;
let coveragePolygon = null;
let tempLine = null;

let antennaState = {
    basePoint: null,
    baseDirection: null,
    currentAngle: 73,
    minAngle: 0,
    maxAngle: 146,
    rangeKm: 10
};

let isSettingDirection = false;
let updateInterval = null;

// Функция для вычисления конечной точки по направлению и расстоянию
function calculateEndpoint(lat, lng, bearing, distance) {
    const R = 6371; // Радиус Земли в км
    const lat1 = lat * Math.PI / 180;
    const lng1 = lng * Math.PI / 180;
    const bearingRad = bearing * Math.PI / 180;
    const d = distance / R;
    
    const lat2 = Math.asin(
        Math.sin(lat1) * Math.cos(d) +
        Math.cos(lat1) * Math.sin(d) * Math.cos(bearingRad)
    );
    
    const lng2 = lng1 + Math.atan2(
        Math.sin(bearingRad) * Math.sin(d) * Math.cos(lat1),
        Math.cos(d) - Math.sin(lat1) * Math.sin(lat2)
    );
    
    return [lat2 * 180 / Math.PI, lng2 * 180 / Math.PI];
}

// Функция для вычисления угла между двумя точками
function calculateBearing(lat1, lng1, lat2, lng2) {
    const dLng = (lng2 - lng1) * Math.PI / 180;
    const lat1Rad = lat1 * Math.PI / 180;
    const lat2Rad = lat2 * Math.PI / 180;
    
    const y = Math.sin(dLng) * Math.cos(lat2Rad);
    const x = Math.cos(lat1Rad) * Math.sin(lat2Rad) -
              Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(dLng);
    
    const bearing = Math.atan2(y, x) * 180 / Math.PI;
    return (bearing + 360) % 360;
}

// Функция отрисовки линий антенны
function drawAntennaLines() {
    if (!antennaState.basePoint || antennaState.baseDirection === null) return;
    
    // Удаляем старые линии
    if (currentDirectionLine) map.removeLayer(currentDirectionLine);
    if (leftBoundaryLine) map.removeLayer(leftBoundaryLine);
    if (rightBoundaryLine) map.removeLayer(rightBoundaryLine);
    if (coveragePolygon) map.removeLayer(coveragePolygon);
    
    const [baseLat, baseLng] = antennaState.basePoint;
    
    // Преобразуем угол антенны (0-146) в смещение от центра (-73 до +73)
    const angleOffset = antennaState.currentAngle - 73;
    
    // Вычисляем абсолютные направления
    const currentDirection = (antennaState.baseDirection + angleOffset + 360) % 360;
    const leftBoundary = (antennaState.baseDirection - 73 + 360) % 360;
    const rightBoundary = (antennaState.baseDirection + 73 + 360) % 360;
    
    // Вычисляем конечные точки
    const currentEnd = calculateEndpoint(baseLat, baseLng, currentDirection, antennaState.rangeKm);
    const leftEnd = calculateEndpoint(baseLat, baseLng, leftBoundary, antennaState.rangeKm);
    const rightEnd = calculateEndpoint(baseLat, baseLng, rightBoundary, antennaState.rangeKm);
    
    // Рисуем текущее направление (яркая бирюзовая линия)
    currentDirectionLine = L.polyline(
        [[baseLat, baseLng], currentEnd],
        {color: '#00aaff', weight: 3, opacity: 1}
    ).addTo(map);
    
    // Рисуем границы (полупрозрачные бирюзовые линии)
    leftBoundaryLine = L.polyline(
        [[baseLat, baseLng], leftEnd],
        {color: '#66d9ff', weight: 2, opacity: 0.6, dashArray: '5, 10'}
    ).addTo(map);
    
    rightBoundaryLine = L.polyline(
        [[baseLat, baseLng], rightEnd],
        {color: '#66d9ff', weight: 2, opacity: 0.6, dashArray: '5, 10'}
    ).addTo(map);
    
    // Создаём полигон зоны покрытия, учитывая возможный переход через 360°
    const polygonPoints = [[baseLat, baseLng]];
    const step = 4; // шаг в градусах для сглаживания дуги
    const addArcPoints = (startDeg, endDeg) => {
        for (let angle = startDeg; angle <= endDeg; angle += step) {
            const point = calculateEndpoint(baseLat, baseLng, angle % 360, antennaState.rangeKm);
            polygonPoints.push(point);
        }
        // точка на самом конце дуги
        const endPoint = calculateEndpoint(baseLat, baseLng, endDeg % 360, antennaState.rangeKm);
        polygonPoints.push(endPoint);
    };
    if (leftBoundary <= rightBoundary) {
        addArcPoints(leftBoundary, rightBoundary);
    } else {
        // дуга проходит через 360 → 0
        addArcPoints(leftBoundary, 360);
        addArcPoints(0, rightBoundary);
    }
    
    coveragePolygon = L.polygon(polygonPoints, {
        color: '#00aaff',
        fillColor: '#00aaff',
        fillOpacity: 0.12,
        weight: 1,
        opacity: 0.25
    }).addTo(map);
}

// Обработка кликов на карте
map.on('click', function(e) {
    if (!antennaState.basePoint) {
        // Первый клик - установка базовой точки
        antennaState.basePoint = [e.latlng.lat, e.latlng.lng];
        
        // Удаляем старый маркер если есть
        if (baseMarker) map.removeLayer(baseMarker);
        
        // Создаём маркер
        baseMarker = L.marker([e.latlng.lat, e.latlng.lng], {
            icon: L.divIcon({
                className: 'custom-div-icon',
                html: '<div style="background-color: #00aaff; width: 12px; height: 12px; border-radius: 50%; border: 2px solid rgba(255,255,255,0.8);"></div>',
                iconSize: [16, 16],
                iconAnchor: [8, 8]
            })
        }).addTo(map);
        
        isSettingDirection = true;
        
    } else if (isSettingDirection) {
        // Второй клик - установка направления
        const bearing = calculateBearing(
            antennaState.basePoint[0], 
            antennaState.basePoint[1],
            e.latlng.lat, 
            e.latlng.lng
        );
        
        antennaState.baseDirection = bearing;
        isSettingDirection = false;
        
        // Удаляем временную линию
        if (tempLine) {
            map.removeLayer(tempLine);
            tempLine = null;
        }
        
        // Отправляем на сервер
        fetch('/api/set_base', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                base_point: antennaState.basePoint,
                base_direction: antennaState.baseDirection
            })
        });
        
        // Рисуем линии
        drawAntennaLines();
        
        // Запускаем автообновление
        startAutoUpdate();
    }
});

// Отображение временной линии при движении мыши
map.on('mousemove', function(e) {
    if (isSettingDirection && antennaState.basePoint) {
        if (tempLine) map.removeLayer(tempLine);
        
        tempLine = L.polyline(
            [antennaState.basePoint, [e.latlng.lat, e.latlng.lng]],
            {color: '#00aaff', weight: 2, opacity: 0.5, dashArray: '5, 5'}
        ).addTo(map);
    }
});

// Функция автообновления
function startAutoUpdate() {
    if (updateInterval) clearInterval(updateInterval);
    
    updateInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/state');
            const state = await response.json();
            
            if (state.base_point && state.base_direction !== null) {
                // Обновляем локальное состояние из ответа сервера
                antennaState.basePoint = state.base_point;
                antennaState.baseDirection = state.base_direction;
                antennaState.currentAngle = state.current_angle;
                if (typeof state.range_km === 'number') {
                    antennaState.rangeKm = state.range_km;
                }
                drawAntennaLines();
            }
        } catch (error) {
            console.error('Ошибка обновления:', error);
        }
    }, 1000); // Обновление каждую секунду
}

// Симуляция и ручная установка угла не требуются

// Функция сброса
function resetAntenna() {
    // Очищаем карту
    if (baseMarker) map.removeLayer(baseMarker);
    if (currentDirectionLine) map.removeLayer(currentDirectionLine);
    if (leftBoundaryLine) map.removeLayer(leftBoundaryLine);
    if (rightBoundaryLine) map.removeLayer(rightBoundaryLine);
    if (coveragePolygon) map.removeLayer(coveragePolygon);
    if (tempLine) map.removeLayer(tempLine);
    
    // Сбрасываем состояние
    antennaState = {
        basePoint: null,
        baseDirection: null,
        currentAngle: 73,
        minAngle: 0,
        maxAngle: 146,
        rangeKm: 10
    };
    
    isSettingDirection = false;
    
    // Останавливаем обновление
    if (updateInterval) {
        clearInterval(updateInterval);
        updateInterval = null;
    }
    
}

// Инициализация при загрузке
document.addEventListener('DOMContentLoaded', function() {
    // Можно добавить начальную загрузку состояния с сервера
    fetch('/api/state')
        .then(response => response.json())
        .then(state => {
            if (state.base_point && state.base_direction !== null) {
                antennaState.basePoint = state.base_point;
                antennaState.baseDirection = state.base_direction;
                if (typeof state.current_angle === 'number') {
                    antennaState.currentAngle = state.current_angle;
                }
                if (typeof state.range_km === 'number') {
                    antennaState.rangeKm = state.range_km;
                }
                // Восстанавливаем маркер
                if (baseMarker) map.removeLayer(baseMarker);
                baseMarker = L.marker(antennaState.basePoint, {
                    icon: L.divIcon({
                        className: 'custom-div-icon',
                        html: '<div style="background-color: #00aaff; width: 12px; height: 12px; border-radius: 50%; border: 2px solid rgba(255,255,255,0.8);"></div>',
                        iconSize: [16, 16],
                        iconAnchor: [8, 8]
                    })
                }).addTo(map);
                // Рисуем и запускаем автообновление
                drawAntennaLines();
                startAutoUpdate();
            }
        })
        .catch(error => console.error('Ошибка загрузки состояния:', error));
});