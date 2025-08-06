#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Система автоматического наведения антенны БПЛА
Поддерживает авто и ручной режимы управления
"""

import sys
import time
import threading
from collections import deque
sys.path.append("..")
from scservo_sdk import *
import ADS1x15

# ==================== НАСТРОЙКИ ====================
SERVO_ID = 1
BAUDRATE = 115200
DEVICENAME = '/dev/servo'
ADC_ADDRESS = 0x48

# Параметры антенны
CENTER_POSITION = 2047          # 180° центральная позиция
ANGLE_RANGE = 120              # ±120° от центра
MIN_POSITION = CENTER_POSITION - (ANGLE_RANGE * 4095 // 360)
MAX_POSITION = CENTER_POSITION + (ANGLE_RANGE * 4095 // 360)

# Параметры управления
RSSI_THRESHOLD = 110          # Минимальная разница для движения
MAX_SPEED = 2000              # Максимальная скорость
MIN_SPEED = 200               # Минимальная скорость
ACCELERATION = 50             # Ускорение
RSSI_BUFFER_SIZE = 5         # Размер буфера усреднения
UPDATE_RATE = 0.1             # Частота обновления (сек)
MANUAL_STEP = 3               # Шаг в ручном режиме (градусы)

class AntennaController:
    """Контроллер автоматического наведения антенны"""
    
    def __init__(self):
        # Инициализация сервопривода
        self.portHandler = PortHandler(DEVICENAME)
        self.packetHandler = sms_sts(self.portHandler)
        
        if not self.portHandler.openPort():
            raise Exception("Не удалось открыть порт сервопривода")
        if not self.portHandler.setBaudRate(BAUDRATE):
            raise Exception("Не удалось установить скорость передачи")
            
        # Инициализация АЦП
        self.adc = ADS1x15.ADS1115(1, ADC_ADDRESS)
        self.adc.setGain(self.adc.PGA_2_048V)
        
        # Параметры состояния
        self.mode = 'manual'  # 'auto' или 'manual'
        self.running = False
        self.current_position = CENTER_POSITION
        self.min_limit = MIN_POSITION
        self.max_limit = MAX_POSITION
        self.center = CENTER_POSITION
        
        # Буферы для усреднения RSSI
        self.rssi_left_buffer = deque(maxlen=RSSI_BUFFER_SIZE)
        self.rssi_right_buffer = deque(maxlen=RSSI_BUFFER_SIZE)
        
        # Установка режима сервопривода
        self._set_servo_mode()
        self._update_position()
        
        print(f"✓ Антенна инициализирована. Позиция: {self.current_position} ({self._to_degrees(self.current_position)}°)")
    
    def __del__(self):
        """Безопасное завершение"""
        self.stop()
        if hasattr(self, 'portHandler'):
            self.portHandler.closePort()
    
    def _set_servo_mode(self):
        """Установка режима позиционирования"""
        self.packetHandler.write1ByteTxRx(SERVO_ID, SMS_STS_MODE, 0)
        time.sleep(0.1)
    
    def _to_degrees(self, position):
        """Преобразование позиции в градусы"""
        return position * 360 // 4095
    
    def _to_position(self, degrees):
        """Преобразование градусов в позицию"""
        return degrees * 4095 // 360
    
    def _update_position(self):
        """Чтение текущей позиции от сервопривода"""
        pos, comm_result, error = self.packetHandler.ReadPos(SERVO_ID)
        if comm_result == COMM_SUCCESS:
            self.current_position = pos
            return pos
        return self.current_position
    
    def _move_to(self, position, speed=None):
        """Движение к заданной позиции с проверкой границ"""
        # Проверка границ
        position = max(self.min_limit, min(self.max_limit, position))
        
        if speed is None:
            speed = MAX_SPEED // 2
            
        comm_result, error = self.packetHandler.WritePosEx(
            SERVO_ID, position, speed, ACCELERATION)
        
        if comm_result == COMM_SUCCESS:
            self.current_position = position
            return True
        return False
    
    def _read_rssi(self):
        """Чтение и усреднение значений RSSI"""
        try:
            right = self.adc.readADC(0)  # Правая антенна
            left = self.adc.readADC(1)   # Левая антенна
            
            # Добавление в буферы
            self.rssi_right_buffer.append(right)
            self.rssi_left_buffer.append(left)
            
            # Усреднение
            if len(self.rssi_right_buffer) > 0:
                avg_right = sum(self.rssi_right_buffer) / len(self.rssi_right_buffer)
                avg_left = sum(self.rssi_left_buffer) / len(self.rssi_left_buffer)
                return avg_left, avg_right
            return left, right
        except:
            return 0, 0
    
    def _auto_control_loop(self):
        """Основной цикл автоматического управления"""
        while self.running and self.mode == 'auto':
            # Чтение RSSI
            left_rssi, right_rssi = self._read_rssi()
            
            # Вычисление разности
            diff = right_rssi - left_rssi
            
            # Проверка порога
            if abs(diff) > RSSI_THRESHOLD:
                # Пропорциональный контроллер
                # Скорость пропорциональна разнице сигналов
                speed = min(MAX_SPEED, max(MIN_SPEED, abs(diff) * 2))
                
                # Вычисление новой позиции
                # Шаг пропорционален разнице, но ограничен
                step = min(100, abs(diff) // 50)  # Максимум 100 единиц за шаг
                
                self._update_position()
                
                if diff > 0:  # Правый сигнал сильнее - поворот вправо
                    new_position = self.current_position + step
                else:  # Левый сигнал сильнее - поворот влево
                    new_position = self.current_position - step
                
                # Движение с адаптивной скоростью
                self._move_to(new_position, int(speed))
                
                print(f"RSSI: L={left_rssi:.0f} R={right_rssi:.0f} Δ={diff:.0f} → "
                      f"Позиция: {self._to_degrees(new_position)}° Скорость: {speed}")
            
            time.sleep(UPDATE_RATE)
    
    # ==================== ПУБЛИЧНЫЕ МЕТОДЫ ====================
    
    def set_mode(self, mode):
        """Установка режима работы ('auto' или 'manual')"""
        if mode in ['auto', 'manual']:
            old_mode = self.mode
            self.mode = mode
            
            if mode == 'auto' and not self.running:
                self.start()
            
            print(f"✓ Режим изменен: {old_mode} → {mode}")
            return True
        return False
    
    def start(self):
        """Запуск автоматического режима"""
        if self.mode == 'auto' and not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._auto_control_loop)
            self.thread.daemon = True
            self.thread.start()
            print("✓ Автоматический режим запущен")
    
    def stop(self):
        """Остановка автоматического режима"""
        self.running = False
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1)
        print("✓ Автоматический режим остановлен")
    
    def manual_left(self):
        """Поворот влево на фиксированный шаг"""
        if self.mode == 'manual':
            self._update_position()
            step = self._to_position(MANUAL_STEP)
            new_pos = self.current_position - step
            self._move_to(new_pos, MAX_SPEED // 2)
            print(f"← Поворот влево: {self._to_degrees(new_pos)}°")
    
    def manual_right(self):
        """Поворот вправо на фиксированный шаг"""
        if self.mode == 'manual':
            self._update_position()
            step = self._to_position(MANUAL_STEP)
            new_pos = self.current_position + step
            self._move_to(new_pos, MAX_SPEED // 2)
            print(f"→ Поворот вправо: {self._to_degrees(new_pos)}°")
    
    def move_to_angle(self, degrees):
        """Перемещение на конкретный угол (относительно центра)"""
        if self.mode == 'manual':
            # Преобразование в абсолютную позицию
            position = self.center + self._to_position(degrees)
            self._move_to(position, MAX_SPEED)
            print(f"⟲ Перемещение к углу: {degrees}°")
    
    def set_center(self):
        """Установка текущей позиции как центр"""
        self._update_position()
        self.center = self.current_position
        # Пересчет границ относительно нового центра
        self.min_limit = self.center - (ANGLE_RANGE * 4095 // 360)
        self.max_limit = self.center + (ANGLE_RANGE * 4095 // 360)
        print(f"✓ Центр установлен: {self.center} ({self._to_degrees(self.center)}°)")
    
    def set_limits(self, left_degrees, right_degrees):
        """Установка пользовательских ограничений (в градусах от центра)"""
        self.min_limit = self.center - self._to_position(abs(left_degrees))
        self.max_limit = self.center + self._to_position(abs(right_degrees))
        print(f"✓ Ограничения установлены: -{abs(left_degrees)}° / +{abs(right_degrees)}°")
    
    def go_center(self):
        """Возврат в центральную позицию"""
        self._move_to(self.center, MAX_SPEED)
        print(f"⟲ Возврат в центр: {self._to_degrees(self.center)}°")
    
    def get_status(self):
        """Получение текущего статуса"""
        self._update_position()
        left_rssi, right_rssi = self._read_rssi()
        
        return {
            'mode': self.mode,
            'position': self.current_position,
            'angle': self._to_degrees(self.current_position),
            'rssi_left': left_rssi,
            'rssi_right': right_rssi,
            'rssi_diff': right_rssi - left_rssi,
            'limits': (self._to_degrees(self.min_limit), self._to_degrees(self.max_limit))
        }

# ==================== ПРИМЕР ИСПОЛЬЗОВАНИЯ ====================

def main():
    """Пример использования контроллера антенны"""
    try:
        antenna = AntennaController()
        
        # Командный интерфейс
        print("\n=== УПРАВЛЕНИЕ АНТЕННОЙ ===")
        print("Команды:")
        print("  a     - автоматический режим")
        print("  m     - ручной режим")
        print("  ←/→   - поворот влево/вправо (ручной)")
        print("  0-9   - угол в десятках градусов")
        print("  c     - установить центр")
        print("  h     - в центр")
        print("  s     - статус")
        print("  q     - выход")
        
        import termios, tty
        def getch():
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                return sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        
        while True:
            cmd = getch()
            
            if cmd == 'q':
                break
            elif cmd == 'a':
                antenna.set_mode('auto')
            elif cmd == 'm':
                antenna.set_mode('manual')
            elif cmd == '\x1b':  # Стрелки
                if getch() == '[':
                    arrow = getch()
                    if arrow == 'D':  # Влево
                        antenna.manual_left()
                    elif arrow == 'C':  # Вправо
                        antenna.manual_right()
            elif cmd.isdigit():
                angle = int(cmd) * 10
                antenna.move_to_angle(angle)
            elif cmd == 'c':
                antenna.set_center()
            elif cmd == 'h':
                antenna.go_center()
            elif cmd == 's':
                status = antenna.get_status()
                print(f"\nСтатус: Режим={status['mode']}, Угол={status['angle']}°, "
                      f"RSSI: L={status['rssi_left']:.0f} R={status['rssi_right']:.0f}")
    
    except Exception as e:
        print(f"Ошибка: {e}")
    finally:
        if 'antenna' in locals():
            antenna.stop()

if __name__ == "__main__":
    main()