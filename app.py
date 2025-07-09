#!/usr/bin/env python3
"""
FPV Pilot Interface - Flask приложение с WebSocket поддержкой
Интегрируется с antenna_tracker.py
"""

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import time
import json
import os
import math

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fpv_antenna_tracker_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

class FPVInterface:
    def __init__(self):
        self.command_file = "/tmp/antenna_commands.txt"
        self.status_file = "/tmp/antenna_status.json"
        self.scan_data_file = "/tmp/angle_scan_data.json"
        
        # Данные для angle scan
        self.scan_in_progress = False
        self.scan_data = []
        
        self.running = True
        
        # Создаем файлы если их нет
        self.init_files()
        
        # Запускаем фоновый поток для чтения данных
        self.data_thread = threading.Thread(target=self.read_data_loop)
        self.data_thread.daemon = True
        self.data_thread.start()
        
    def init_files(self):
        """Инициализация файлов"""
        # Создаем файл команд если его нет
        if not os.path.exists(self.command_file):
            with open(self.command_file, 'w') as f:
                f.write("")
        
        # Создаем файл статуса если его нет
        if not os.path.exists(self.status_file):
            with open(self.status_file, 'w') as f:
                json.dump({}, f)
        
    def send_command(self, command):
        """Отправляет команду в antenna_tracker с защитой"""
        try:
            # Проверяем валидность команды
            valid_commands = ['left', 'right', 'auto', 'manual', 'scan']
            if command not in valid_commands:
                print(f"[ERROR] Недопустимая команда: {command}")
                return False
            
            # Защита от переполнения файла команд
            if os.path.exists(self.command_file):
                file_size = os.path.getsize(self.command_file)
                if file_size > 1000:  # Больше 1KB - что-то не так
                    print(f"[WARNING] Файл команд слишком большой: {file_size} байт")
                    # Очищаем файл
                    with open(self.command_file, 'w') as f:
                        f.write("")
            
            # Записываем команду
            with open(self.command_file, 'w') as f:
                f.write(command)
            
            # Проверяем что команда записалась
            with open(self.command_file, 'r') as f:
                written_command = f.read().strip()
                if written_command != command:
                    print(f"[ERROR] Команда записалась неправильно: {written_command} != {command}")
                    return False
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Ошибка отправки команды '{command}': {e}")
            return False
    
    def read_status(self):
        """Читает статус из antenna_tracker"""
        try:
            if os.path.exists(self.status_file) and os.path.getsize(self.status_file) > 0:
                with open(self.status_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        return json.loads(content)
        except json.JSONDecodeError:
            pass  # Игнорируем ошибки парсинга
        except Exception as e:
            print(f"[ERROR] Ошибка чтения статуса: {e}")
        return None
    
    def start_angle_scan(self):
        """Запускает сканирование углов с защитой"""
        try:
            if self.scan_in_progress:
                print("[WARNING] Попытка запуска сканирования когда оно уже активно")
                return False
            
            # Проверяем что antenna_tracker работает
            if not self.read_status():
                print("[WARNING] Нет данных от antenna_tracker, сканирование может не работать")
                # Все равно пытаемся запустить для тестирования
            
            self.scan_in_progress = True
            self.scan_data = []
            
            # Запускаем сканирование в отдельном потоке
            scan_thread = threading.Thread(target=self.perform_angle_scan_safe)
            scan_thread.daemon = True
            scan_thread.start()
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Ошибка запуска сканирования: {e}")
            self.scan_in_progress = False
            return False
    
    def perform_angle_scan_safe(self):
        """Безопасное выполнение сканирования с обработкой ошибок"""
        try:
            self.perform_angle_scan()
        except Exception as e:
            print(f"[ERROR] Ошибка в процессе сканирования: {e}")
            self.scan_in_progress = False
            socketio.emit('scan_complete', {'data': [], 'error': str(e)})
    
    def perform_angle_scan(self):
        """Выполняет сканирование по углам"""
        # Сначала отправляем команду сканирования
        self.send_command("scan")
        time.sleep(0.5)
        
        # Ждем завершения основного сканирования
        time.sleep(6)
        
        # Теперь делаем детальное сканирование для графика
        start_pos = 1100  # Левый предел
        end_pos = 2700    # Правый предел
        step = 50         # Шаг сканирования
        
        current_pos = start_pos
        while current_pos <= end_pos and self.scan_in_progress:
            # Вычисляем угол (0-360 градусов)
            angle = ((current_pos - start_pos) / (end_pos - start_pos)) * 360
            
            # Читаем текущие RSSI значения
            status = self.read_status()
            if status:
                # Используем сумму RSSI как общую силу сигнала
                total_rssi = status.get('rssi_a', 0) + status.get('rssi_b', 0)
                
                self.scan_data.append({
                    'angle': angle,
                    'rssi': total_rssi,
                    'position': current_pos
                })
                
                # Отправляем данные в real-time
                socketio.emit('scan_data_point', {
                    'angle': angle,
                    'rssi': total_rssi
                })
            
            current_pos += step
            time.sleep(0.3)  # Пауза между измерениями
        
        # Сохраняем данные сканирования
        try:
            with open(self.scan_data_file, 'w') as f:
                json.dump(self.scan_data, f)
        except:
            pass
        
        self.scan_in_progress = False
        socketio.emit('scan_complete', {'data': self.scan_data})
    
    def read_data_loop(self):
        """Основной цикл чтения данных"""
        no_data_counter = 0
        
        while self.running:
            try:
                status = self.read_status()
                
                if status:
                    no_data_counter = 0
                    
                    # Конвертируем позицию сервопривода в угол (0-360)
                    position = status.get('angle', 2047)
                    angle = ((position - 1100) / (2700 - 1100)) * 360
                    
                    telemetry_data = {
                        'rssi_a': status.get('rssi_a', 0),
                        'rssi_b': status.get('rssi_b', 0),
                        'angle': angle,
                        'auto_mode': status.get('auto_mode', False),
                        'mode': status.get('mode', 'manual')
                    }
                    
                    # Отправляем данные клиентам
                    socketio.emit('telemetry', telemetry_data)
                else:
                    no_data_counter += 1
                    
                    # Отправляем фиктивные данные для тестирования интерфейса
                    if no_data_counter > 10:  # После 2 секунд без данных
                        fake_data = {
                            'rssi_a': 1500 + (no_data_counter % 100),
                            'rssi_b': 1600 + (no_data_counter % 100),
                            'angle': (no_data_counter * 2) % 360,
                            'auto_mode': False,
                            'mode': 'manual'
                        }
                        socketio.emit('telemetry', fake_data)
                
                time.sleep(0.2)  # Обновляем 5 раз в секунду
            except Exception as e:
                print(f"[ERROR] Ошибка в цикле чтения данных: {e}")
                time.sleep(1)

# Создаем экземпляр интерфейса
fpv_interface = FPVInterface()

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/live')
def live_stream():
    """Эндпоинт для видео потока (заглушка)"""
    # Здесь должен быть ваш видео поток
    return "Video stream endpoint"

@socketio.on('connect')
def handle_connect():
    """Обработка подключения клиента"""
    emit('connected', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    """Обработка отключения клиента"""
    pass

@socketio.on('set_mode')
def handle_set_mode(data):
    """Обработка переключения режима Auto"""
    try:
        auto_mode = bool(data.get('auto', False))
        
        if auto_mode:
            success = fpv_interface.send_command('auto')
        else:
            success = fpv_interface.send_command('manual')
        
        emit('mode_update', {'auto_mode': auto_mode, 'success': success})
        
    except Exception as e:
        print(f"[ERROR] Ошибка в set_mode: {e}")
        emit('mode_update', {'auto_mode': False, 'success': False, 'error': str(e)})

@socketio.on('manual_rotate')
def handle_manual_rotate(data):
    """Обработка ручного поворота"""
    try:
        direction = str(data.get('direction', '')).lower()
        
        # Проверяем валидное направление
        if direction not in ['left', 'right']:
            emit('rotate_response', {'direction': direction, 'success': False, 'error': 'Invalid direction'})
            return
        
        success = fpv_interface.send_command(direction)
        emit('rotate_response', {'direction': direction, 'success': success})
        
    except Exception as e:
        print(f"[ERROR] Ошибка в manual_rotate: {e}")
        emit('rotate_response', {'direction': 'unknown', 'success': False, 'error': str(e)})

@socketio.on('start_angle_scan')
def handle_angle_scan():
    """Обработка запуска angle scan"""
    try:
        # Проверяем что сканирование не активно
        if fpv_interface.scan_in_progress:
            emit('scan_started', {'success': False, 'error': 'Scan already active'})
            return
        
        success = fpv_interface.start_angle_scan()
        emit('scan_started', {'success': success})
        
    except Exception as e:
        print(f"[ERROR] Ошибка в start_angle_scan: {e}")
        emit('scan_started', {'success': False, 'error': str(e)})

@socketio.on('stop_angle_scan')
def handle_stop_scan():
    """Остановка сканирования"""
    try:
        fpv_interface.scan_in_progress = False
        emit('scan_stopped', {'success': True})
        
    except Exception as e:
        print(f"[ERROR] Ошибка в stop_angle_scan: {e}")
        emit('scan_stopped', {'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("Запуск FPV Interface сервера...")
    print("Убедитесь что antenna_tracker.py запущен!")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)