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
        self.scan_results_file = "/tmp/antenna_scan_results.json"  # Новый файл для результатов
        
        self.running = True
        self.last_scan_timestamp = 0  # Отслеживаем последнее обновление результатов сканирования
        
        # Создаем файлы если их нет
        self.init_files()
        
        # Запускаем фоновый поток для чтения данных
        self.data_thread = threading.Thread(target=self.read_data_loop)
        self.data_thread.daemon = True
        self.data_thread.start()
        
        # Отдельный поток для мониторинга результатов сканирования
        self.scan_monitor_thread = threading.Thread(target=self.monitor_scan_results)
        self.scan_monitor_thread.daemon = True
        self.scan_monitor_thread.start()
        
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
            
            print(f"[INFO] Команда '{command}' отправлена")
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
    
    def read_scan_results(self):
        """Читает результаты сканирования"""
        try:
            if os.path.exists(self.scan_results_file) and os.path.getsize(self.scan_results_file) > 0:
                with open(self.scan_results_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        return json.loads(content)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"[ERROR] Ошибка чтения результатов сканирования: {e}")
        return None
    
    def monitor_scan_results(self):
        """Мониторит файл результатов сканирования и отправляет обновления"""
        while self.running:
            try:
                scan_results = self.read_scan_results()
                
                if scan_results and scan_results.get('scan_complete', False):
                    # Проверяем, новые ли это результаты
                    timestamp = scan_results.get('timestamp', 0)
                    
                    if timestamp > self.last_scan_timestamp:
                        self.last_scan_timestamp = timestamp
                        
                        print(f"[INFO] Новые результаты сканирования: лучший угол {scan_results.get('best_angle', 0)}°")
                        
                        # Отправляем результаты клиентам
                        socketio.emit('scan_complete', {
                            'success': True,
                            'best_angle': scan_results.get('best_angle', 0),
                            'data': scan_results.get('scan_data', []),
                            'message': f"Сканирование завершено. Оптимальный угол: {scan_results.get('best_angle', 0)}°"
                        })
                        
                time.sleep(1)  # Проверяем каждую секунду
                
            except Exception as e:
                print(f"[ERROR] Ошибка мониторинга результатов сканирования: {e}")
                time.sleep(5)
    
    def read_data_loop(self):
        """Основной цикл чтения данных"""
        no_data_counter = 0
        
        while self.running:
            try:
                status = self.read_status()
                
                if status:
                    no_data_counter = 0
                    
                    # Конвертируем позицию сервопривода в угол (0-146 градусов)
                    position = status.get('angle', 2047)
                    angle = ((position - 1100) / 11.0)  # Прямое преобразование в градусы
                    angle = max(0, min(146, angle))  # Ограничиваем диапазон
                    
                    # Определяем режим работы
                    current_mode = status.get('mode', 'manual')
                    scan_in_progress = status.get('scan_in_progress', False)
                    
                    telemetry_data = {
                        'rssi_a': status.get('rssi_a', 0),
                        'rssi_b': status.get('rssi_b', 0),
                        'angle': angle,
                        'auto_mode': status.get('auto_mode', False),
                        'mode': current_mode,
                        'scan_in_progress': scan_in_progress
                    }
                    
                    # Отправляем данные клиентам
                    socketio.emit('telemetry', telemetry_data)
                    
                    # Отправляем обновления статуса сканирования
                    if scan_in_progress:
                        socketio.emit('scan_status_update', {
                            'scanning': True,
                            'status': 'Сканирование в процессе...'
                        })
                    elif current_mode == 'scan_complete':
                        socketio.emit('scan_status_update', {
                            'scanning': False,
                            'status': 'Сканирование завершено'
                        })
                else:
                    no_data_counter += 1
                    
                    # Отправляем фиктивные данные для тестирования интерфейса
                    if no_data_counter > 10:  # После 2 секунд без данных
                        fake_data = {
                            'rssi_a': 4500 + (no_data_counter % 500),  # Диапазон 4500-5000
                            'rssi_b': 5200 + (no_data_counter % 500),  # Диапазон 5200-5700
                            'angle': (no_data_counter * 2) % 146,  # 0-146 градусов
                            'auto_mode': False,
                            'mode': 'manual',
                            'scan_in_progress': False
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
    print("[INFO] Клиент подключился")
    emit('connected', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    """Обработка отключения клиента"""
    print("[INFO] Клиент отключился")

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
        print("[INFO] Запрос на запуск сканирования")
        
        success = fpv_interface.send_command('scan')
        
        if success:
            emit('scan_started', {'success': True, 'message': 'Команда сканирования отправлена'})
        else:
            emit('scan_started', {'success': False, 'error': 'Ошибка отправки команды'})
        
    except Exception as e:
        print(f"[ERROR] Ошибка в start_angle_scan: {e}")
        emit('scan_started', {'success': False, 'error': str(e)})

@socketio.on('stop_angle_scan')
def handle_stop_scan():
    """Остановка сканирования"""
    try:
        print("[INFO] Запрос на остановку сканирования")
        
        # Отправляем команду перехода в ручной режим (прерывает сканирование)
        success = fpv_interface.send_command('manual')
        
        emit('scan_stopped', {'success': success, 'message': 'Сканирование остановлено'})
        
    except Exception as e:
        print(f"[ERROR] Ошибка в stop_angle_scan: {e}")
        emit('scan_stopped', {'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("Запуск FPV Interface сервера...")
    print("Убедитесь что antenna_tracker.py запущен!")
    print(f"Мониторинг файлов:")
    print(f"  Команды: {fpv_interface.command_file}")
    print(f"  Статус: {fpv_interface.status_file}")
    print(f"  Результаты сканирования: {fpv_interface.scan_results_file}")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)