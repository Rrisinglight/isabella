#!/usr/bin/env python3
"""
FPV Antenna Tracker
Веб-интерфейс + API управления антенной + видео прокси
"""

import time
import threading
import json
import sys
import os
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, List

from flask import Flask, request, jsonify, render_template, Response, send_from_directory
from flask_cors import CORS
import requests
import base64
import ADS1x15
from vtx_service import VtxService

# Добавляем путь к библиотеке SCServo
sys.path.append("..")
from scservo_sdk import *


# ============= КОНФИГУРАЦИЯ =============

# URL видеопотока
ENCODER_URL = "http://192.168.1.106/isabella"

# URL видеопотока
CAMERA_URL = "rtsp://192.168.1.10:554/stream_1"

# Порт для веб-сервера
WEB_PORT = 5000


# ============= КЛАССЫ ANTENNA TRACKER =============

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
    baudrate: int = 115200
    id: int = 1
    center_pos: int = 2047
    left_limit: int = 1100
    right_limit: int = 2700
    # Преобразование: (2700-1100) = 1600 единиц на ~146 градусов
    # 1 градус = ~11 единиц
    step_degrees: int = 1  # Шаг в градусах для ручного режима
    step_units: int = 11  # 3 градуса * 11 единиц
    scan_step_units: int = 33  # Шаг сканирования
    
    # Параметры движения
    default_speed: int = 500  # Скорость по умолчанию
    default_acc: int = 50  # Ускорение по умолчанию
    auto_speed: int = 500  # Скорость для авторежима (плавнее)
    auto_acc: int = 30  # Ускорение для авторежима


@dataclass
class ADCConfig:
    """Конфигурация АЦП"""
    address: int = 0x48
    bus: int = 1
    gain: Optional[int] = None  # Будет установлен в init
    left_channel: int = 3   # ADC канал для левой антенны
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
        self.actual_position = self.servo_config.center_pos
        self.running = True

        # VTX service (lazy init)
        self.vtx_service = VtxService()
        
        # Калибровка
        self.rssi_offset =-600  # Смещение для выравнивания каналов
        self.noise_floor_left = 0  # Уровень шума левого канала
        self.noise_floor_right = 0  # Уровень шума правого канала
        self.rssi_max_left = 4000  # Максимум левого канала
        self.rssi_max_right = 4000  # Максимум правого канала
        
        # Буферы для фильтрации
        self.rssi_filter_size = 1
        self.left_rssi_buffer = deque(maxlen=self.rssi_filter_size)
        self.right_rssi_buffer = deque(maxlen=self.rssi_filter_size)
        
        # Параметры автослежения
        self.rssi_threshold = 15  # Минимальная разница для движения
        self.auto_step_small = 11  # Малый шаг (1 градус) для точной подстройки
        self.auto_step_medium = 22  # Средний шаг (2 градуса)
        self.auto_step_large = 44  # Большой шаг (4 градуса) для быстрого наведения
        self.auto_deadband = 500  # Мертвая зона, где движение не требуется
        
        # Данные сканирования
        self.scan_data = []
        self.scan_position = self.servo_config.left_limit
        
        # Хранилище данных
        self.last_status = {}
        self.last_scan_results = {}
        
        # Блокировки
        self.position_lock = threading.Lock()
        
        # Таймер для авторежима
        self.last_auto_move_time = 0
        self.auto_move_cooldown = 0.1 # Минимальный интервал между движениями
        
        print("=== Antenna Tracker инициализирован ===")
        self._print_servo_info()

        # ========== VTX SCAN STATE ==========
        self.vtx_scan_in_progress = False
        self.vtx_scan_lock = threading.Lock()
        self.vtx_scan_thread: Optional[threading.Thread] = None
        self.vtx_scan_current = { 'band': None, 'channel': None }
        # grid: {band: [rssi_total for ch1..8]}
        self.vtx_scan_grid = { b: [None]*8 for b in ['A','B','E','F','R','L'] }
        self.vtx_scan_best = { 'band': None, 'channel': None, 'rssi': None }
    
    def _init_hardware(self):
        """Инициализация оборудования"""
        try:
            # Инициализация сервопривода
            self.portHandler = PortHandler(self.servo_config.port)
            self.packetHandler = sms_sts(self.portHandler)
            
            # Открытие порта
            if not self.portHandler.openPort():
                raise Exception(f"Не удалось открыть порт {self.servo_config.port}")
            
            # Установка скорости передачи
            if not self.portHandler.setBaudRate(self.servo_config.baudrate):
                raise Exception(f"Не удалось установить скорость {self.servo_config.baudrate}")
                
            print(f"✓ Сервопривод подключен: {self.servo_config.port} @ {self.servo_config.baudrate} bps")
            
            # Проверка связи с сервоприводом
            model_number, comm_result, error = self.packetHandler.ping(self.servo_config.id)
            if comm_result == COMM_SUCCESS:
                print(f"✓ Сервопривод ID:{self.servo_config.id} найден. Модель: {model_number}")
            else:
                raise Exception(f"Сервопривод ID:{self.servo_config.id} не отвечает")
            
            # Установка режима позиционирования
            comm_result, error = self.packetHandler.write1ByteTxRx(
                self.servo_config.id, SMS_STS_MODE, 0)
            if comm_result == COMM_SUCCESS:
                print("✓ Режим позиционирования установлен")
            
            # Включение момента
            comm_result, error = self.packetHandler.write1ByteTxRx(
                self.servo_config.id, SMS_STS_TORQUE_ENABLE, 1)
            if comm_result == COMM_SUCCESS:
                print("✓ Момент включен")
            
            # Чтение текущей позиции
            pos, comm_result, error = self.packetHandler.ReadPos(self.servo_config.id)
            if comm_result == COMM_SUCCESS:
                self.position = pos
                self.actual_position = pos
                print(f"✓ Текущая позиция: {pos} ({self.position_to_angle(pos)}°)")
            
            # Инициализация АЦП
            self.ads = ADS1x15.ADS1115(
                self.adc_config.bus, 
                self.adc_config.address
            )
            self.adc_config.gain = self.ads.PGA_2_048V
            self.ads.setGain(self.adc_config.gain)
            print(f"✓ АЦП подключен: адрес 0x{self.adc_config.address:02X}")

            #VTX инициализируется лениво в сервисе
            
        except Exception as e:
            print(f"✗ ОШИБКА инициализации оборудования: {e}")
            raise
    
    def _print_servo_info(self):
        """Вывод информации о конфигурации сервопривода"""
        print(f"Позиция: {self.position} (центр: {self.servo_config.center_pos})")
        print(f"Лимиты: {self.servo_config.left_limit} - {self.servo_config.right_limit}")
        print(f"Диапазон: {self.position_to_angle(self.servo_config.left_limit)}° - "
              f"{self.position_to_angle(self.servo_config.right_limit)}°")
        print(f"Шаг ручного режима: {self.servo_config.step_degrees}° ({self.servo_config.step_units} единиц)")
    
    def read_servo_status(self) -> dict:
        """Чтение полного статуса сервопривода"""
        status = {}
        
        try:
            # Позиция и скорость
            pos, speed, comm_result, error = self.packetHandler.ReadPosSpeed(self.servo_config.id)
            if comm_result == COMM_SUCCESS:
                status['position'] = pos
                status['angle'] = self.position_to_angle(pos)
                status['speed'] = speed
                self.actual_position = pos
            
            # Напряжение
            voltage, comm_result, error = self.packetHandler.read1ByteTxRx(
                self.servo_config.id, SMS_STS_PRESENT_VOLTAGE)
            if comm_result == COMM_SUCCESS:
                status['voltage'] = voltage / 10.0
            
            # Температура
            temp, comm_result, error = self.packetHandler.read1ByteTxRx(
                self.servo_config.id, SMS_STS_PRESENT_TEMPERATURE)
            if comm_result == COMM_SUCCESS:
                status['temperature'] = temp
            
            # Ток
            current, comm_result, error = self.packetHandler.read2ByteTxRx(
                self.servo_config.id, SMS_STS_PRESENT_CURRENT_L)
            if comm_result == COMM_SUCCESS:
                current = self.packetHandler.scs_tohost(current, 15)
                status['current'] = current
            
            # Статус движения
            moving, comm_result, error = self.packetHandler.ReadMoving(self.servo_config.id)
            if comm_result == COMM_SUCCESS:
                status['moving'] = bool(moving)
            
        except Exception as e:
            print(f"Ошибка чтения статуса сервопривода: {e}")
        
        return status
    
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
    
    def move_servo(self, new_position: int, speed: Optional[int] = None, 
                   acc: Optional[int] = None) -> bool:
        """Перемещает сервопривод в новую позицию"""
        # Ограничиваем позицию
        new_position = max(self.servo_config.left_limit, min(self.servo_config.right_limit, new_position))
        
        # Используем параметры по умолчанию если не заданы
        if speed is None:
            speed = self.servo_config.default_speed
        if acc is None:
            acc = self.servo_config.default_acc
        
        with self.position_lock:
            if abs(new_position - self.position) < 2:  # Игнорируем микро-движения
                return True
                
            try:
                comm_result, error = self.packetHandler.WritePosEx(
                    self.servo_config.id, new_position, speed, acc)
                
                if comm_result == COMM_SUCCESS:
                    self.position = new_position
                    angle = self.position_to_angle(new_position)
                    # print(f"→ Позиция: {new_position} ({angle:.1f}°)")
                    return True
                else:
                    print(f"Ошибка перемещения: {self.packetHandler.getTxRxResult(comm_result)}")
                    return False
                    
            except Exception as e:
                print(f"Ошибка перемещения сервопривода: {e}")
                return False
    
    def move_to_angle(self, angle_degrees: float) -> bool:
        """Перемещает сервопривод на заданный угол"""
        # Преобразуем угол в позицию
        position = self.angle_to_position(angle_degrees)
        return self.move_servo(position)
    
    def position_to_angle(self, position: int) -> float:
        """Преобразует позицию сервопривода в угол"""
        # Диапазон позиций от left_limit до right_limit соответствует углам 0-146 градусов
        range_units = self.servo_config.right_limit - self.servo_config.left_limit
        range_degrees = 146.0
        angle = ((position - self.servo_config.left_limit) / range_units) * range_degrees
        return round(angle, 1)
    
    def angle_to_position(self, angle_degrees: float) -> int:
        """Преобразует угол в позицию сервопривода"""
        # Ограничиваем угол
        angle_degrees = max(0, min(146, angle_degrees))
        
        range_units = self.servo_config.right_limit - self.servo_config.left_limit
        range_degrees = 146.0
        position = int(self.servo_config.left_limit + (angle_degrees / range_degrees) * range_units)
        return position
    
    def update_status(self, left_rssi: float, right_rssi: float):
        """Обновляет текущий статус"""
        # Читаем актуальную позицию из сервопривода
        servo_status = self.read_servo_status()
        
        self.last_status = {
            "rssi_a": round(left_rssi, 0),
            "rssi_b": round(right_rssi, 0),
            "angle": servo_status.get('position', self.position),
            "angle_degrees": servo_status.get('angle', self.position_to_angle(self.position)),
            "mode": self.current_mode.value,
            "auto_mode": self.current_mode == Mode.AUTO,
            "scan_in_progress": self.current_mode == Mode.SCAN,
            "servo_voltage": servo_status.get('voltage', 0),
            "servo_temperature": servo_status.get('temperature', 0),
            "servo_moving": servo_status.get('moving', False),
            "timestamp": time.time()
        }

        # Добавляем VTX статус
        # Добавляем VTX статус (даже если еще не инициализирован)
        try:
            self.last_status["vtx"] = self.vtx_service.get_status()
        except Exception as _:
            pass

        # Добавляем статус VTX-сканирования
        try:
            self.last_status["vtx_scan"] = self.get_vtx_scan_status()
        except Exception:
            pass
    
    def process_command(self, command: str, params: dict = None) -> bool:
        """Обрабатывает команду"""
        print(f"Команда: {command}, параметры: {params}")
        
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
                
            elif command == "set_angle":
                # Установка конкретного угла
                if params and 'angle' in params:
                    self.current_mode = Mode.MANUAL
                    angle = float(params['angle'])
                    print(f"Установка угла: {angle}°")
                    return self.move_to_angle(angle)
                return False
                
            elif command == "set_center":
                # Установка текущей позиции как центр
                pos, comm_result, error = self.packetHandler.ReadPos(self.servo_config.id)
                if comm_result == COMM_SUCCESS:
                    self.servo_config.center_pos = pos
                    print(f"Центр установлен: {pos} ({self.position_to_angle(pos)}°)")
                    return True
                return False
                
            elif command == "set_left_limit":
                # Установка текущей позиции как левый лимит
                pos, comm_result, error = self.packetHandler.ReadPos(self.servo_config.id)
                if comm_result == COMM_SUCCESS:
                    self.servo_config.left_limit = pos
                    print(f"Левый лимит установлен: {pos} ({self.position_to_angle(pos)}°)")
                    return True
                return False
                
            elif command == "set_right_limit":
                # Установка текущей позиции как правый лимит
                pos, comm_result, error = self.packetHandler.ReadPos(self.servo_config.id)
                if comm_result == COMM_SUCCESS:
                    self.servo_config.right_limit = pos
                    print(f"Правый лимит установлен: {pos} ({self.position_to_angle(pos)}°)")
                    return True
                return False
                
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

    def _get_frequency_mhz(self, band: str, channel: int) -> int:
        # Keep for compatibility where used elsewhere if any
        return self.vtx_service._get_frequency_mhz(band, channel)
    
    def start_scan(self):
        """Начинает сканирование"""
        print("\n=== НАЧАЛО СКАНИРОВАНИЯ ===")
        self.current_mode = Mode.SCAN
        self.scan_data = []
        self.last_scan_results = {}
        self.scan_position = self.servo_config.left_limit
        self.move_servo(self.scan_position, speed=1000, acc=50)
        time.sleep(0.5)
    
    def process_scan(self):
        """Выполняет один шаг сканирования"""
        # Проверяем, не вышли ли за пределы
        if self.scan_position > self.servo_config.right_limit:
            self.finish_scan()
            return
        
        # Ждем окончания движения
        self.wait_for_movement(timeout=0.5)
        
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
        self.move_servo(self.scan_position, speed=1000, acc=50)
    
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
        self.move_servo(best_position, speed=1500, acc=50)
        self.wait_for_movement()
        
        # Переходим в автоматический режим
        self.current_mode = Mode.AUTO
        print("Переход в автоматический режим")
    
    def process_auto_tracking(self):
        """Автоматическое слежение с плавным движением"""
        # Проверяем время с последнего движения
        current_time = time.time()
        if current_time - self.last_auto_move_time < self.auto_move_cooldown:
            # Слишком рано для следующего движения
            left_rssi, right_rssi = self.read_rssi()
            self.update_status(left_rssi, right_rssi)
            return
        
        # Читаем RSSI
        left_rssi, right_rssi = self.read_rssi()
        self.update_status(left_rssi, right_rssi)
        
        # Вычисляем разницу
        difference = left_rssi - right_rssi
        abs_difference = abs(difference)
        
        # Если разница в пределах мертвой зоны - не двигаемся
        if abs_difference < self.auto_deadband:
            return
        
        # Определяем размер шага в зависимости от разницы RSSI
        if abs_difference < self.rssi_threshold:
            # Малая разница - не двигаемся
            return
        elif abs_difference < self.rssi_threshold * 2:
            # Средняя разница - малый шаг
            step = self.auto_step_small
            speed = self.servo_config.auto_speed
        elif abs_difference < self.rssi_threshold * 4:
            # Большая разница - средний шаг
            step = self.auto_step_medium
            speed = self.servo_config.auto_speed + 200
        else:
            # Очень большая разница - большой шаг
            step = self.auto_step_large
            speed = self.servo_config.auto_speed + 400
        
        # Определяем направление
        if difference > 0:
            # Левая сильнее - поворачиваем влево
            new_position = self.position - step
        else:
            # Правая сильнее - поворачиваем вправо
            new_position = self.position + step
        
        # Двигаемся плавно
        if self.move_servo(new_position, speed=speed, acc=self.servo_config.auto_acc):
            self.last_auto_move_time = current_time
    
    def wait_for_movement(self, timeout: float = 2.0):
        """Ожидание завершения движения с таймаутом"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            moving, comm_result, error = self.packetHandler.ReadMoving(self.servo_config.id)
            if comm_result == COMM_SUCCESS and moving == 0:
                break
            time.sleep(0.01)
    
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
        self.move_servo(self.servo_config.center_pos, speed=1500, acc=50)
        self.wait_for_movement()
        
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
        
        # Выключаем момент перед закрытием
        try:
            self.packetHandler.write1ByteTxRx(
                self.servo_config.id, SMS_STS_TORQUE_ENABLE, 0)
            print("✓ Момент выключен")
        except:
            pass
        
        # Закрываем порт
        try:
            self.portHandler.closePort()
            print("✓ Порт закрыт")
        except:
            pass
        
        print("Сервис остановлен")

    # ================= VTX SCAN =================
    def start_vtx_scan(self, settle_ms: int = 700):
        """Старт сканирования по всем частотам VTX (не блокирующий)."""
        with self.vtx_scan_lock:
            if self.vtx_scan_in_progress:
                return False
            self.vtx_scan_in_progress = True
            self.vtx_scan_current = { 'band': None, 'channel': None }
            self.vtx_scan_grid = { b: [None]*8 for b in ['A','B','E','F','R','L'] }
            self.vtx_scan_best = { 'band': None, 'channel': None, 'rssi': None }

        def _worker():
            # Гарантируем минимум 700 мс на стабилизацию картинки
            min_settle_ms = 700 if settle_ms is None else max(700, int(settle_ms))
            try:
                order = ['A','B','E','F','R','L']
                for band in order:
                    for ch in range(1, 9):
                        # Обновляем текущую клетку
                        with self.vtx_scan_lock:
                            self.vtx_scan_current = { 'band': band, 'channel': ch }
                        # Устанавливаем частоту
                        try:
                            self.vtx_service.set_band_channel(band, ch)
                        except Exception as e:
                            print(f"[VTX-SCAN] set_channel error: {e}")
                            # Прерываем сканирование при ошибке
                            with self.vtx_scan_lock:
                                self.vtx_scan_in_progress = False
                            return

                        # Ждём стабилизации приёмника/картинки
                        time.sleep(min_settle_ms / 1000.0)

                        # Читаем RSSI (сумма A+B)
                        left, right = self.read_rssi()
                        total = (left or 0) + (right or 0)
                        with self.vtx_scan_lock:
                            self.vtx_scan_grid[band][ch-1] = total
                            # Обновляем best
                            if self.vtx_scan_best['rssi'] is None or total > self.vtx_scan_best['rssi']:
                                self.vtx_scan_best = { 'band': band, 'channel': ch, 'rssi': total }

                # После полного прохода — переключаемся на лучшую частоту
                with self.vtx_scan_lock:
                    best = self.vtx_scan_best.copy()
                if best['band'] and best['channel']:
                    try:
                        self.vtx_service.set_band_channel(best['band'], best['channel'])
                        print(f"[VTX-SCAN] Переключено на лучшую: {best['band']}{best['channel']} RSSI={best['rssi']:.0f}")
                    except Exception as e:
                        print(f"[VTX-SCAN] failed to set best channel: {e}")
            finally:
                with self.vtx_scan_lock:
                    self.vtx_scan_in_progress = False

        # Запускаем поток
        self.vtx_scan_thread = threading.Thread(target=_worker, daemon=True)
        self.vtx_scan_thread.start()
        return True

    def get_vtx_scan_status(self) -> dict:
        with self.vtx_scan_lock:
            return {
                'in_progress': self.vtx_scan_in_progress,
                'current': self.vtx_scan_current.copy(),
                'grid': { b: self.vtx_scan_grid[b][:] for b in self.vtx_scan_grid },
                'best': self.vtx_scan_best.copy()
            }
    
    def get_status(self) -> dict:
        """Возвращает текущий статус"""
        return self.last_status.copy()
    
    def get_scan_results(self) -> dict:
        """Возвращает результаты сканирования"""
        if self.last_scan_results.get('scan_complete'):
            results = self.last_scan_results.copy()
            return results
        return {}


# ============= FLASK ПРИЛОЖЕНИЕ =============

# Создаем Flask приложение
app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
CORS(app)  # Включаем CORS для всех маршрутов

# Глобальная переменная для трекера
tracker = None

# ======= Веб-интерфейс маршруты =======

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    """Отдача статических файлов"""
    return send_from_directory('static', filename)

@app.route('/live')
def live_stream():
    """Прокси для видеопотока"""
    def generate():
        try:
            r = requests.get(ENCODER_URL, stream=True, timeout=5)
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=4096):
                yield chunk
        except Exception as e:
            print(f"[ERROR] Ошибка видеопотока: {e}")
            yield b""

    return Response(generate(),
                   mimetype='video/mp2t',
                   headers={'Cache-Control': 'no-cache'})

@app.route('/whep/<path_name>', methods=['POST'])
def whep_proxy(path_name: str):
    """Прозрачный прокси для WHEP (WebRTC Receive), чтобы избежать CORS."""
    try:
        # MediaMTX слушает на 8889 согласно логам
        mediamtx_url = f"http://127.0.0.1:8889/whep/{path_name}"

        # Поддерживаем два варианта: application/sdp и urlencoded (legacy)
        content_type = request.headers.get('Content-Type', '')

        headers = {}
        data = None

        if 'application/sdp' in content_type:
            headers['Content-Type'] = 'application/sdp'
            data = request.data
        else:
            # Ожидаем поле data (base64 sdp)
            b64 = request.form.get('data', '')
            try:
                sdp = base64.b64decode(b64).decode('utf-8') if b64 else ''
            except Exception:
                sdp = ''
            headers['Content-Type'] = 'application/sdp'
            data = sdp

        print(f"[WHEP] proxy (prefix) -> {mediamtx_url}, ct={headers.get('Content-Type')}, bytes={len(data) if hasattr(data, '__len__') else 'unknown'}")
        # Явно укажем Accept
        headers['Accept'] = 'application/sdp'
        r = requests.post(mediamtx_url, headers=headers, data=data, timeout=10)
        print(f"[WHEP] proxy (prefix) <- status={r.status_code}, ct={r.headers.get('Content-Type')}")
        resp = Response(r.content, status=r.status_code)
        # Если MediaMTX вернул SDP, передаем соответствующий тип
        resp.headers['Content-Type'] = r.headers.get('Content-Type', 'application/sdp')
        return resp
    except Exception as e:
        print(f"[ERROR] WHEP proxy error: {e}")
        return Response("", status=502)

@app.route('/<path_name>/whep', methods=['POST'])
def whep_proxy_suffix(path_name: str):
    """Альтернативный путь прокси: /<path>/whep -> MediaMTX /<path>/whep"""
    try:
        mediamtx_url = f"http://127.0.0.1:8889/{path_name}/whep"
        content_type = request.headers.get('Content-Type', '')
        headers = {}
        data = None
        if 'application/sdp' in content_type:
            headers['Content-Type'] = 'application/sdp'
            data = request.data
        else:
            b64 = request.form.get('data', '')
            try:
                sdp = base64.b64decode(b64).decode('utf-8') if b64 else ''
            except Exception:
                sdp = ''
            headers['Content-Type'] = 'application/sdp'
            data = sdp
        print(f"[WHEP] proxy (suffix) -> {mediamtx_url}, ct={headers.get('Content-Type')}, bytes={len(data) if hasattr(data, '__len__') else 'unknown'}")
        headers['Accept'] = 'application/sdp'
        r = requests.post(mediamtx_url, headers=headers, data=data, timeout=10)
        print(f"[WHEP] proxy (suffix) <- status={r.status_code}, ct={r.headers.get('Content-Type')}")
        resp = Response(r.content, status=r.status_code)
        resp.headers['Content-Type'] = r.headers.get('Content-Type', 'application/sdp')
        return resp
    except Exception as e:
        print(f"[ERROR] WHEP proxy (suffix) error: {e}")
        return Response("", status=502)

# ======= API маршруты =======

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
    params = data.get('params', {})
    success = tracker.process_command(command, params)
    
    return jsonify({
        "success": success,
        "command_executed": command
    })


@app.route('/vtx', methods=['GET', 'POST'])
def vtx_endpoint():
    """Получить/установить частоту VTX"""
    if not tracker:
        return jsonify({"success": False, "error": "Tracker not initialized"}), 500

    # GET: вернуть текущее состояние
    if request.method == 'GET':
        return jsonify({"success": True, "vtx": tracker.vtx_service.get_status()})

    # POST: установить новую частоту
    data = request.get_json(force=True, silent=True) or {}
    cur = tracker.vtx_service.get_status()
    band = str(data.get('band', cur.get('band', 'A'))).upper()
    channel = int(data.get('channel', cur.get('channel', 1)))

    if band not in ['A','B','E','F','R','L'] or channel < 1 or channel > 8:
        return jsonify({"success": False, "error": "Invalid band/channel"}), 400

    try:
        tracker.vtx_service.set_band_channel(band, channel)
        return jsonify({"success": True, "vtx": tracker.vtx_service.get_status()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/vtx-scan', methods=['POST'])
def vtx_scan_start():
    """Запуск сканирования по всем частотам"""
    if not tracker:
        return jsonify({"success": False, "error": "Tracker not initialized"}), 500
    started = tracker.start_vtx_scan()
    return jsonify({"success": started})


@app.route('/vtx-scan/status', methods=['GET'])
def vtx_scan_status():
    if not tracker:
        return jsonify({"success": False, "error": "Tracker not initialized"}), 500
    status = tracker.get_vtx_scan_status()
    return jsonify({"success": True, **status})


# ============= ТОЧКА ВХОДА =============

def main():
    """Точка входа"""
    global tracker
    
    print("=" * 50)
    print("    FPV ANTENNA TRACKER - UNIFIED SERVICE")
    print("=" * 50)
    print("\nИнициализация...")
    
    try:
        # Создаем трекер
        tracker = AntennaTracker()
        
        # Запускаем основной цикл трекера в отдельном потоке
        tracker_thread = threading.Thread(target=tracker.run, daemon=True)
        tracker_thread.start()
        
        # Информация о сервисе
        print(f"\n{'='*50}")
        print(f"  СЕРВИС ЗАПУЩЕН")
        print(f"{'='*50}")
        print(f"\n📡 Веб-интерфейс: http://0.0.0.0:{WEB_PORT}")
        print(f"📹 Видеопоток: {ENCODER_URL}")
        print(f"\n🎮 Доступные команды через веб-интерфейс:")
        print("  • Left/Right - движение на 3°")
        print("  • Home - возврат в центр")
        print("  • Auto/Manual - смена режима")
        print("  • Scan - запуск сканирования")
        print("  • Calibrate - калибровка минимума/максимума")
        print(f"\n{'='*50}\n")
        
        # Запускаем Flask сервер
        app.run(host='0.0.0.0', port=WEB_PORT, debug=False)
        
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        if tracker:
            tracker.cleanup()


if __name__ == "__main__":
    main()