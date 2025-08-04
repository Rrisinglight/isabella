#!/usr/bin/env python3
"""
Сервис автоматического слежения антенны за дроном
Простой, надежный и поддерживаемый код
"""

import time
import threading
import json
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, List

from flask import Flask, request, jsonify
from flask_cors import CORS
from st3215 import ST3215
import ADS1x15


class Mode(Enum):
    """Режимы работы трекера"""
    MANUAL = "manual"
    AUTO = "auto"
    SCAN = "scan"
    CALIBRATE_MIN = "calibrate_min"
    CALIBRATE_MAX = "calibrate_max"


@dataclass
class ServoConfig:
    """Конфигурация сервопривода"""
    port: str = '/dev/servo'
    id: int = 1
    center_pos: int = 2047
    left_limit: int = 1100
    right_limit: int = 2700
    step_degrees: int = 3  # Шаг в градусах
    # Преобразование: (2700-1100) = 1600 единиц на 146 градусов
    # 1 градус = ~11 единиц
    step_units: int = 33  # 3 градуса * 11 единиц
    scan_step_units: int = 33  # Шаг сканирования тоже 3 градуса


@dataclass
class ADCConfig:
    """Конфигурация АЦП"""
    address: int = 0x48
    bus: int = 1
    gain: Optional[int] = None  # Будет установлен в init
    left_channel: int = 1   # ADC канал для левой антенны
    right_channel: int = 0  # ADC канал для правой антенны


class AntennaTracker:
    """Основной класс управления антенной"""
    
    def __init__(self):
        # Конфигурация
        self.servo_config = ServoConfig()
        self.adc_config = ADCConfig()
        
        # Инициализация железа
        self._init_hardware()
        
        # Состояние
        self.current_mode = Mode.MANUAL
        self.position = self.servo_config.center_pos
        self.running = True
        
        # Калибровка
        self.rssi_offset = 0  # Смещение для выравнивания каналов
        self.noise_floor_left = 0  # Уровень шума левого канала
        self.noise_floor_right = 0  # Уровень шума правого канала
        self.rssi_max_left = 4000  # Максимум левого канала
        self.rssi_max_right = 4000  # Максимум правого канала
        
        # Буферы для фильтрации
        self.rssi_filter_size = 5
        self.left_rssi_buffer = deque(maxlen=self.rssi_filter_size)
        self.right_rssi_buffer = deque(maxlen=self.rssi_filter_size)
        
        # Параметры автослежения
        self.rssi_threshold = 10  # Минимальная разница для движения
        self.auto_step = self.servo_config.step_units  # Шаг автослежения
        
        # Данные сканирования
        self.scan_data = []
        self.scan_position = self.servo_config.left_limit
        
        # Хранилище данных
        self.last_status = {}
        self.last_scan_results = {}
        
        # Блокировки
        self.position_lock = threading.Lock()
        
        print("=== Antenna Tracker инициализирован ===")
        print(f"Позиция: {self.position} (центр: {self.servo_config.center_pos})")
        print(f"Лимиты: {self.servo_config.left_limit} - {self.servo_config.right_limit}")
        print(f"Шаг поворота: {self.servo_config.step_degrees}° ({self.servo_config.step_units} единиц)")
    
    def _init_hardware(self):
        """Инициализация оборудования"""
        try:
            # Сервопривод
            self.servo = ST3215(self.servo_config.port)
            print(f"Сервопривод подключен: {self.servo_config.port}")
            
            # АЦП
            self.ads = ADS1x15.ADS1115(
                self.adc_config.bus, 
                self.adc_config.address
            )
            self.adc_config.gain = self.ads.PGA_2_048V
            self.ads.setGain(self.adc_config.gain)
            print(f"АЦП подключен: адрес 0x{self.adc_config.address:02X}")
            
        except Exception as e:
            print(f"ОШИБКА инициализации оборудования: {e}")
            raise
    
    def read_rssi(self) -> Tuple[float, float]:
        """Читает RSSI с обеих антенн"""
        try:
            # Читаем сырые значения
            left_raw = self.ads.readADC(self.adc_config.left_channel)
            right_raw = self.ads.readADC(self.adc_config.right_channel)
            
            # Применяем калибровку
            left_calibrated = left_raw - self.noise_floor_left
            right_calibrated = right_raw - self.noise_floor_right + self.rssi_offset
            
            # Добавляем в буферы
            self.left_rssi_buffer.append(left_calibrated)
            self.right_rssi_buffer.append(right_calibrated)
            
            # Возвращаем отфильтрованные значения
            if len(self.left_rssi_buffer) > 0:
                left_filtered = sum(self.left_rssi_buffer) / len(self.left_rssi_buffer)
                right_filtered = sum(self.right_rssi_buffer) / len(self.right_rssi_buffer)
                return left_filtered, right_filtered
            
            return left_calibrated, right_calibrated
            
        except Exception as e:
            print(f"Ошибка чтения RSSI: {e}")
            return 0, 0
    
    def move_servo(self, new_position: int) -> bool:
        """Перемещает сервопривод в новую позицию"""
        # Ограничиваем позицию
        new_position = max(
            self.servo_config.left_limit,
            min(self.servo_config.right_limit, new_position)
        )
        
        with self.position_lock:
            if new_position != self.position:
                try:
                    self.servo.WritePosition(self.servo_config.id, new_position)
                    self.position = new_position
                    angle = self.position_to_angle(self.position)
                    print(f"Позиция: {self.position} ({angle}°)")
                    return True
                except Exception as e:
                    print(f"Ошибка перемещения сервопривода: {e}")
                    return False
        return True
    
    def position_to_angle(self, position: int) -> float:
        """Преобразует позицию сервопривода в угол"""
        range_units = self.servo_config.right_limit - self.servo_config.left_limit
        range_degrees = 146.0
        angle = ((position - self.servo_config.left_limit) / range_units) * range_degrees
        return round(angle, 1)
    
    def update_status(self, left_rssi: float, right_rssi: float):
        """Обновляет текущий статус"""
        self.last_status = {
            "rssi_a": round(left_rssi, 0),
            "rssi_b": round(right_rssi, 0),
            "angle": self.position,
            "angle_degrees": self.position_to_angle(self.position),
            "mode": self.current_mode.value,
            "auto_mode": self.current_mode == Mode.AUTO,
            "scan_in_progress": self.current_mode == Mode.SCAN,
            "timestamp": time.time()
        }
    
    def process_command(self, command: str) -> bool:
        """Обрабатывает команду"""
        print(f"Команда: {command}")
        
        try:
            if command == "left":
                self.current_mode = Mode.MANUAL
                new_pos = self.position - self.servo_config.step_units
                return self.move_servo(new_pos)
                
            elif command == "right":
                self.current_mode = Mode.MANUAL
                new_pos = self.position + self.servo_config.step_units
                return self.move_servo(new_pos)
                
            elif command == "home":
                self.current_mode = Mode.MANUAL
                return self.move_servo(self.servo_config.center_pos)
                
            elif command == "auto":
                self.current_mode = Mode.AUTO
                print("Режим: автоматическое слежение")
                return True
                
            elif command == "manual":
                self.current_mode = Mode.MANUAL
                print("Режим: ручное управление")
                return True
                
            elif command == "scan":
                if self.current_mode != Mode.SCAN:
                    self.start_scan()
                return True
                
            elif command == "calibrate":
                if self.current_mode != Mode.CALIBRATE_MIN:
                    self.current_mode = Mode.CALIBRATE_MIN
                return True
                
            elif command == "calibrate_max":
                if self.current_mode != Mode.CALIBRATE_MAX:
                    self.current_mode = Mode.CALIBRATE_MAX
                return True
                
            else:
                print(f"Неизвестная команда: {command}")
                return False
                
        except Exception as e:
            print(f"Ошибка выполнения команды: {e}")
            return False
    
    def start_scan(self):
        """Начинает сканирование"""
        print("\n=== НАЧАЛО СКАНИРОВАНИЯ ===")
        self.current_mode = Mode.SCAN
        self.scan_data = []
        self.last_scan_results = {}  # Очищаем старые результаты
        self.scan_position = self.servo_config.left_limit
        self.move_servo(self.scan_position)
        time.sleep(0.5)  # Даем время на перемещение
    
    def process_scan(self):
        """Выполняет один шаг сканирования"""
        # Проверяем, не вышли ли за пределы
        if self.scan_position > self.servo_config.right_limit:
            self.finish_scan()
            return
        
        # Читаем RSSI несколько раз для усреднения
        readings = []
        for _ in range(5):
            left, right = self.read_rssi()
            readings.append((left, right))
            time.sleep(0.05)
        
        # Усредняем
        avg_left = sum(r[0] for r in readings) / len(readings)
        avg_right = sum(r[1] for r in readings) / len(readings)
        total_rssi = avg_left + avg_right
        
        # Сохраняем данные
        angle = self.position_to_angle(self.scan_position)
        self.scan_data.append({
            'position': self.scan_position,
            'angle': angle,
            'left_rssi': avg_left,
            'right_rssi': avg_right,
            'total_rssi': total_rssi,
            'difference': abs(avg_left - avg_right)
        })
        
        print(f"Скан {angle:5.1f}°: L={avg_left:4.0f} R={avg_right:4.0f} Σ={total_rssi:4.0f}")
        
        # Обновляем статус
        self.update_status(avg_left, avg_right)
        
        # Двигаемся дальше
        self.scan_position += self.servo_config.scan_step_units
        self.move_servo(self.scan_position)
        time.sleep(0.1)  # Небольшая пауза между шагами
    
    def finish_scan(self):
        """Завершает сканирование и анализирует результаты"""
        print("\n=== АНАЛИЗ РЕЗУЛЬТАТОВ ===")
        
        if len(self.scan_data) < 3:
            print("Недостаточно данных для анализа")
            self.current_mode = Mode.MANUAL
            return
        
        # Находим позицию с минимальной разницей RSSI
        best_data = min(self.scan_data, key=lambda x: x['difference'])
        best_position = best_data['position']
        best_angle = best_data['angle']
        min_difference = best_data['difference']
        
        print(f"Лучшая позиция: {best_position} ({best_angle}°)")
        print(f"Минимальная разница: {min_difference:.0f}")
        
        # Сохраняем результаты
        self.last_scan_results = {
            'scan_complete': True,
            'timestamp': time.time(),
            'best_position': best_position,
            'best_angle': best_angle,
            'min_difference': min_difference,
            'scan_data': [
                {
                    'angle': d['angle'],
                    'rssi': d['total_rssi'],
                    'left_rssi': d['left_rssi'],
                    'right_rssi': d['right_rssi'],
                    'difference': d['difference']
                }
                for d in self.scan_data
            ]
        }
        
        # Перемещаемся в лучшую позицию
        print("Перемещение в оптимальную позицию...")
        self.move_servo(best_position)
        time.sleep(1)
        
        # Переходим в автоматический режим
        self.current_mode = Mode.AUTO
        print("Переход в автоматический режим")
    
    def process_auto_tracking(self):
        """Автоматическое слежение"""
        left_rssi, right_rssi = self.read_rssi()
        self.update_status(left_rssi, right_rssi)
        
        difference = left_rssi - right_rssi
        
        # Игнорируем малые различия
        if abs(difference) < self.rssi_threshold:
            return
        
        # Определяем направление
        if difference > 0:
            # Левая сильнее - поворачиваем влево
            new_position = self.position - self.auto_step
        else:
            # Правая сильнее - поворачиваем вправо
            new_position = self.position + self.auto_step
        
        self.move_servo(new_position)
    
    def calibrate_minimum(self):
        """Калибровка минимума (без антенн)"""
        print("\n=== КАЛИБРОВКА МИНИМУМА ===")
        print("Убедитесь, что антенны СНЯТЫ!")
        
        samples = []
        duration = 8  # секунд
        rate = 10  # измерений в секунду
        total = duration * rate
        
        for i in range(total):
            if self.current_mode != Mode.CALIBRATE_MIN:
                print("Калибровка прервана")
                return
            
            # Читаем сырые значения
            left_raw = self.ads.readADC(self.adc_config.left_channel)
            right_raw = self.ads.readADC(self.adc_config.right_channel)
            samples.append((left_raw, right_raw))
            
            # Прогресс
            if i % rate == 0:
                print(f"Прогресс: {i//rate}/{duration} сек")
            
            # Обновляем статус
            self.update_status(left_raw, right_raw)
            
            time.sleep(1.0 / rate)
        
        # Анализ
        avg_left = sum(s[0] for s in samples) / len(samples)
        avg_right = sum(s[1] for s in samples) / len(samples)
        
        # Сохраняем уровень шума
        self.noise_floor_left = avg_left
        self.noise_floor_right = avg_right
        
        # Вычисляем смещение для выравнивания каналов
        self.rssi_offset = avg_left - avg_right
        
        print(f"\nРезультаты калибровки минимума:")
        print(f"  Шум левого канала:  {avg_left:.0f}")
        print(f"  Шум правого канала: {avg_right:.0f}")
        print(f"  Смещение каналов:   {self.rssi_offset:.0f}")
        
        self.current_mode = Mode.MANUAL
        print("Калибровка минимума завершена")
    
    def calibrate_maximum(self):
        """Калибровка максимума (с антеннами и дроном)"""
        print("\n=== КАЛИБРОВКА МАКСИМУМА ===")
        print("Убедитесь что:")
        print("1. Антенны установлены")
        print("2. Дрон включен и находится на расстоянии 1-2 метра")
        print("3. Антенны направлены на дрон")
        
        samples = []
        duration = 8  # секунд
        rate = 10  # измерений в секунду
        total = duration * rate
        
        for i in range(total):
            if self.current_mode != Mode.CALIBRATE_MAX:
                print("Калибровка прервана")
                return
            
            # Читаем значения с применением калибровки минимума
            left_rssi, right_rssi = self.read_rssi()
            samples.append((left_rssi, right_rssi))
            
            # Прогресс
            if i % rate == 0:
                print(f"Прогресс: {i//rate}/{duration} сек")
            
            # Обновляем статус
            self.update_status(left_rssi, right_rssi)
            
            time.sleep(1.0 / rate)
        
        # Анализ
        avg_left = sum(s[0] for s in samples) / len(samples)
        avg_right = sum(s[1] for s in samples) / len(samples)
        
        # Сохраняем максимумы
        self.rssi_max_left = avg_left
        self.rssi_max_right = avg_right
        
        # Динамический диапазон
        range_left = self.rssi_max_left - self.noise_floor_left
        range_right = self.rssi_max_right - self.noise_floor_right
        
        print(f"\nРезультаты калибровки максимума:")
        print(f"  Максимум левого:  {self.rssi_max_left:.0f}")
        print(f"  Максимум правого: {self.rssi_max_right:.0f}")
        print(f"  Динамический диапазон:")
        print(f"    Левый:  {range_left:.0f}")
        print(f"    Правый: {range_right:.0f}")
        
        self.current_mode = Mode.MANUAL
        print("Калибровка максимума завершена")
    
    def run(self):
        """Основной цикл"""
        print("\n=== ЗАПУСК СЕРВИСА ===")
        
        # Начальная позиция
        self.move_servo(self.servo_config.center_pos)
        time.sleep(1)
        
        # Автоматический запуск сканирования
        print("Автозапуск сканирования...")
        self.start_scan()
        
        try:
            while self.running:
                try:
                    # Выполняем действия в зависимости от режима
                    if self.current_mode == Mode.SCAN:
                        self.process_scan()
                        
                    elif self.current_mode == Mode.AUTO:
                        self.process_auto_tracking()
                        
                    elif self.current_mode == Mode.CALIBRATE_MIN:
                        self.calibrate_minimum()
                        
                    elif self.current_mode == Mode.CALIBRATE_MAX:
                        self.calibrate_maximum()
                        
                    else:  # MANUAL
                        # В ручном режиме просто обновляем статус
                        left_rssi, right_rssi = self.read_rssi()
                        self.update_status(left_rssi, right_rssi)
                    
                    time.sleep(0.1)
                    
                except Exception as e:
                    print(f"ОШИБКА в основном цикле: {e}")
                    self.current_mode = Mode.MANUAL
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            print("\nОстановка по Ctrl+C")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Очистка ресурсов"""
        self.running = False
        print("Сервис остановлен")
    
    def get_status(self) -> dict:
        """Возвращает текущий статус"""
        return self.last_status.copy()
    
    def get_scan_results(self) -> dict:
        """Возвращает результаты сканирования"""
        if self.last_scan_results.get('scan_complete'):
            results = self.last_scan_results.copy()
            # НЕ очищаем результаты после чтения, чтобы клиент мог получить их повторно
            return results
        return {}


# Flask API
app = Flask(__name__)
CORS(app)  # Включаем CORS для всех маршрутов

tracker = None

@app.route('/status', methods=['GET'])
def get_status():
    """Получить текущий статус"""
    if tracker:
        return jsonify(tracker.get_status())
    return jsonify({"error": "Tracker not initialized"}), 500

@app.route('/scan-results', methods=['GET'])
def get_scan_results():
    """Получить результаты сканирования"""
    if tracker:
        return jsonify(tracker.get_scan_results())
    return jsonify({}), 200

@app.route('/command', methods=['POST'])
def send_command():
    """Отправить команду трекеру"""
    if not tracker:
        return jsonify({"success": False, "error": "Tracker not initialized"}), 500
    
    data = request.get_json()
    if not data or 'command' not in data:
        return jsonify({"success": False, "error": "No command provided"}), 400
    
    command = data['command']
    success = tracker.process_command(command)
    
    return jsonify({
        "success": success,
        "command_executed": command
    })


def main():
    """Точка входа"""
    global tracker
    
    print("=== FPV Antenna Tracker ===")
    print("Инициализация...")
    
    try:
        # Создаем трекер
        tracker = AntennaTracker()
        
        # Запускаем основной цикл в отдельном потоке
        tracker_thread = threading.Thread(target=tracker.run, daemon=True)
        tracker_thread.start()
        
        # Запускаем API сервер
        print(f"\nAPI сервер: http://0.0.0.0:5001")
        app.run(host='0.0.0.0', port=5001, debug=False)
        
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        if tracker:
            tracker.cleanup()


if __name__ == "__main__":
    main()