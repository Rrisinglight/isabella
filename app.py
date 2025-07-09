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
        """Запускает простое сканирование углов"""
        try:
            if self.scan_in_progress:
                print("[WARNING] Попытка запуска сканирования когда оно уже активно")
                return False
            
            self.scan_in_progress = True
            
            # Просто отправляем команду сканирования в antenna_tracker
            success = self.send_command('scan')
            
            if success:
                # Запускаем мониторинг сканирования в отдельном потоке
                monitor_thread = threading.Thread(target=self.monitor_scan)
                monitor_thread.daemon = True
                monitor_thread.start()
                return True
            else:
                self.scan_in_progress = False
                return False
            
        except Exception as e:
            print(f"[ERROR] Ошибка запуска сканирования: {e}")
            self.scan_in_progress = False
            return False
    
    def monitor_scan(self):
        """Мониторит процесс сканирования и отправляет данные для графика"""
        try:
            # Ждем пока antenna_tracker выполняет сканирование
            scan_start_time = time.time()
            max_scan_time = 60  # Максимум 60 секунд на сканирование
            last_position = None
            
            while self.scan_in_progress and (time.time() - scan_start_time) < max_scan_time:
                status = self.read_status()
                
                if status:
                    current_mode = status.get('mode', 'manual')
                    current_position = status.get('angle', 2047)
                    
                    # Если режим изменился с 'scan' на что-то другое, значит сканирование завершено
                    if current_mode != 'scan':
                        break
                    
                    # Отправляем данные для графика во время сканирования
                    if current_position != last_position:
                        # Конвертируем позицию в угол (0-146 градусов)
                        angle = ((current_position - 1100) / 11.0)
                        angle = max(0, min(146, angle))
                        
                        # Отправляем сумму RSSI для графика
                        total_rssi = status.get('rssi_a', 0) + status.get('rssi_b', 0)
                        
                        socketio.emit('scan_data_point', {
                            'angle': angle,
                            'rssi': total_rssi
                        })
                        
                        last_position = current_position
                
                time.sleep(0.2)  # Проверяем каждые 200мс
            
            # Сканирование завершено
            self.scan_in_progress = False
            
            # Отправляем сигнал о завершении
            socketio.emit('scan_complete', {
                'success': True,
                'message': 'Сканирование завершено'
            })
            
            print("Сканирование завершено")
            
        except Exception as e:
            print(f"[ERROR] Ошибка мониторинга сканирования: {e}")
            self.scan_in_progress = False
            socketio.emit('scan_complete', {
                'success': False,
                'error': str(e)
            })
    
    def read_data_loop(self):
        """Основной цикл чтения данных"""
        no_data_counter = 0
        
        while self.running:
            try:
                status = self.read_status()
                
                if status:
                    no_data_counter = 0
                    
                    # Конвертируем позицию сервопривода в угол (0-146 градусов)
                    # 11 единиц = 1 градус, диапазон 1100-2700 (1600 единиц = ~146 градусов)
                    position = status.get('angle', 2047)
                    angle = ((position - 1100) / 11.0)  # Прямое преобразование в градусы
                    angle = max(0, min(146, angle))  # Ограничиваем диапазон
                    
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
                            'rssi_a': 4500 + (no_data_counter % 500),  # Диапазон 4500-5000
                            'rssi_b': 5200 + (no_data_counter % 500),  # Диапазон 5200-5700
                            'angle': (no_data_counter * 2) % 146,  # 0-146 градусов
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