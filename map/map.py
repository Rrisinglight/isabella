from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import threading
import time
import math

app = Flask(__name__)
CORS(app)

# Глобальные переменные для хранения состояния
antenna_state = {
    'base_point': None,  # [lat, lng]
    'base_direction': None,  # направление в градусах (0-360)
    'current_angle': 73.0,  # текущий угол антенны (0-146, где 73 - центр)
    'min_angle': 0,
    'max_angle': 146,
    'range_km': 10  # дальность в километрах
}

# Блокировка для потокобезопасности
state_lock = threading.Lock()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/state', methods=['GET'])
def get_state():
    """Получить текущее состояние антенны"""
    with state_lock:
        return jsonify(antenna_state)

@app.route('/api/set_base', methods=['POST'])
def set_base():
    """Установить базовую точку и направление"""
    data = request.json
    with state_lock:
        antenna_state['base_point'] = data.get('base_point')
        antenna_state['base_direction'] = data.get('base_direction')
    return jsonify({'status': 'ok'})

@app.route('/api/update_angle', methods=['POST'])
def update_angle():
    """Обновить текущий угол антенны (0-146)"""
    data = request.json
    angle = data.get('angle', 73)
    
    with state_lock:
        # Ограничиваем угол в пределах 0-146
        antenna_state['current_angle'] = max(0, min(146, angle))
    
    return jsonify({'status': 'ok', 'angle': antenna_state['current_angle']})

@app.route('/api/simulate', methods=['POST'])
def simulate():
    """Запустить симуляцию движения антенны (для демонстрации)"""
    def simulate_movement():
        direction = 1
        while True:
            with state_lock:
                current = antenna_state['current_angle']
                current += direction * 5
                
                if current >= 146:
                    current = 146
                    direction = -1
                elif current <= 0:
                    current = 0
                    direction = 1
                    
                antenna_state['current_angle'] = current
            
            time.sleep(0.5)
    
    # Запускаем в отдельном потоке
    thread = threading.Thread(target=simulate_movement, daemon=True)
    thread.start()
    
    return jsonify({'status': 'simulation started'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)