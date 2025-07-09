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
        print(f"[DEBUG] Инициализация файлов...")
        
        # Создаем файл команд если его нет
        if not os.path.exists(self.command_file):
            with open(self.command_file, 'w') as f:
                f.write("")
            print(f"[DEBUG] Создан файл команд: {self.command_file}")
        
        # Создаем файл статуса если его нет
        if not os.path.exists(self.status_file):
            with open(self.status_file, 'w') as f:
                json.dump({}, f)
            print(f"[DEBUG] Создан файл статуса: {self.status_file}")
            
        print(f"[DEBUG] Файлы инициализированы")
        
    def send_command(self, command):
        """Отправляет команду в antenna_tracker"""
        try:
            print(f"[DEBUG] Отправка команды: {command}")
            with open(self.command_file, 'w') as f:
                f.write(command)
            print(f"[DEBUG] Команда {command} записана в {self.command_file}")
            return True
        except Exception as e:
            print(f"[ERROR] Ошибка отправки команды: {e}")
            return False
    
    def read_status(self):
        """Читает статус из antenna_tracker"""
        try:
            if os.path.exists(self.status_file):
                file_size = os.path.getsize(self.status_file)
                if file_size == 0:
                    print(f"[DEBUG] Файл статуса {self.status_file} пуст")
                    return None
                    
                with open(self.status_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        print(f"[DEBUG] Файл статуса содержит только пробелы")
                        return None
                        
                    data = json.loads(content)
                    print(f"[DEBUG] Статус прочитан: RSSI_A={data.get('rssi_a', 'N/A')}, RSSI_B={data.get('rssi_b', 'N/A')}, Angle={data.get('angle', 'N/A')}, Mode={data.get('mode', 'N/A')}")
                    return data
            else:
                print(f"[DEBUG] Файл статуса {self.status_file} не существует")
                return None
        except json.JSONDecodeError as e:
            print(f"[ERROR] Ошибка парсинга JSON: {e}")
            # Попробуем прочитать содержимое файла для отладки
            try:
                with open(self.status_file, 'r') as f:
                    content = f.read()
                    print(f"[DEBUG] Содержимое файла статуса: '{content}'")
            except:
                pass
            return None
        except Exception as e:
            print(f"[ERROR] Ошибка чтения статуса: {e}")
            return None
    
    def start_angle_scan(self):
        """Запускает сканирование углов"""
        if self.scan_in_progress:
            return False
            
        self.scan_in_progress = True
        self.scan_data = []
        
        # Запускаем сканирование в отдельном потоке
        scan_thread = threading.Thread(target=self.perform_angle_scan)
        scan_thread.daemon = True
        scan_thread.start()
        
        return True
    
    def perform_angle_scan(self):
        """Выполняет сканирование по углам"""
        print("Начинаем angle scan...")
        
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
        print("Angle scan завершен")
    
    def read_data_loop(self):
        """Основной цикл чтения данных"""
        print("[DEBUG] Запуск цикла чтения данных...")
        last_status_time = 0
        no_data_counter = 0
        
        while self.running:
            try:
                status = self.read_status()
                current_time = time.time()
                
                if status:
                    no_data_counter = 0
                    last_status_time = current_time
                    
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
                    
                    if no_data_counter % 25 == 0:  # Каждые 5 секунд
                        print(f"[DEBUG] Отправлена телеметрия: {telemetry_data}")
                else:
                    no_data_counter += 1
                    
                    # Если долго нет данных от antenna_tracker, создаем фиктивные
                    if current_time - last_status_time > 5:  # 5 секунд без данных
                        if no_data_counter % 25 == 0:  # Каждые 5 секунд
                            print(f"[WARNING] Нет данных от antenna_tracker уже {current_time - last_status_time:.1f} сек. Отправляем фиктивные данные.")
                        
                        # Фиктивные данные для тестирования интерфейса
                        fake_data = {
                            'rssi_a': 1500 + no_data_counter % 100,
                            'rssi_b': 1600 + no_data_counter % 100,
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
    print('[DEBUG] Клиент подключился')
    emit('connected', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    """Обработка отключения клиента"""
    print('[DEBUG] Клиент отключился')

@socketio.on('set_mode')
def handle_set_mode(data):
    """Обработка переключения режима Auto"""
    auto_mode = data.get('auto', False)
    print(f"[DEBUG] Получена команда set_mode: auto={auto_mode}")
    
    if auto_mode:
        success = fpv_interface.send_command('auto')
    else:
        success = fpv_interface.send_command('manual')
    
    print(f"[DEBUG] Результат команды set_mode: success={success}")
    emit('mode_update', {'auto_mode': auto_mode, 'success': success})

@socketio.on('manual_rotate')
def handle_manual_rotate(data):
    """Обработка ручного поворота"""
    direction = data.get('direction')
    print(f"[DEBUG] Получена команда manual_rotate: direction={direction}")
    
    if direction == 'left':
        success = fpv_interface.send_command('left')
    elif direction == 'right':
        success = fpv_interface.send_command('right')
    else:
        success = False
        print(f"[ERROR] Неизвестное направление: {direction}")
    
    print(f"[DEBUG] Результат команды manual_rotate: success={success}")
    emit('rotate_response', {'direction': direction, 'success': success})

@socketio.on('start_angle_scan')
def handle_angle_scan():
    """Обработка запуска angle scan"""
    print("[DEBUG] Получена команда start_angle_scan")
    success = fpv_interface.start_angle_scan()
    print(f"[DEBUG] Результат команды start_angle_scan: success={success}")
    emit('scan_started', {'success': success})

@socketio.on('stop_angle_scan')
def handle_stop_scan():
    """Остановка сканирования"""
    print("[DEBUG] Получена команда stop_angle_scan")
    fpv_interface.scan_in_progress = False
    emit('scan_stopped', {'success': True})

if __name__ == '__main__':
    print("Запуск FPV Interface сервера...")
    print("Убедитесь что antenna_tracker.py запущен!")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)