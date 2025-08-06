#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Полный тестовый код для сервопривода ST3215
Включает все режимы работы и основные функции
"""

import sys
import os
import time

# Определение функции getch() для кроссплатформенности
if os.name == 'nt':
    import msvcrt
    def getch():
        return msvcrt.getch().decode()
else:
    import sys, tty, termios
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    def getch():
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

# Импорт библиотеки SCServo SDK
sys.path.append("..")
from scservo_sdk import *

# ==================== НАСТРОЙКИ ====================
SERVO_ID = 1                           # ID сервопривода
BAUDRATE = 115200                     # Скорость передачи данных
DEVICENAME = '/dev/servo'            # Порт (Windows: "COM1", Linux: "/dev/ttyUSB0")

# Параметры движения
MIN_POSITION = 0                       # Минимальная позиция
MAX_POSITION = 4095                    # Максимальная позиция (360 градусов)
MIDDLE_POSITION = 2047                 # Средняя позиция (180 градусов)
DEFAULT_SPEED = 2000                   # Скорость по умолчанию
DEFAULT_ACC = 100                      # Ускорение по умолчанию

class ST3215Controller:
    """Класс для управления сервоприводом ST3215"""
    
    def __init__(self, port_name, baudrate, servo_id):
        self.servo_id = servo_id
        self.portHandler = PortHandler(port_name)
        self.packetHandler = sms_sts(self.portHandler)
        
        # Открытие порта
        if not self.portHandler.openPort():
            raise Exception("Не удалось открыть порт")
        
        # Установка скорости передачи
        if not self.portHandler.setBaudRate(baudrate):
            raise Exception("Не удалось установить скорость передачи")
            
        print(f"✓ Подключение установлено: {port_name} @ {baudrate} bps")
        
    def __del__(self):
        """Закрытие порта при удалении объекта"""
        if hasattr(self, 'portHandler'):
            self.portHandler.closePort()
            print("✓ Порт закрыт")
    
    # ==================== БАЗОВЫЕ ФУНКЦИИ ====================
    
    def ping(self):
        """Проверка связи с сервоприводом"""
        model_number, comm_result, error = self.packetHandler.ping(self.servo_id)
        if comm_result == COMM_SUCCESS:
            print(f"✓ Сервопривод ID:{self.servo_id} найден. Модель: {model_number}")
            return True
        else:
            print(f"✗ Ошибка связи: {self.packetHandler.getTxRxResult(comm_result)}")
            return False
    
    def read_status(self):
        """Чтение полного статуса сервопривода"""
        print("\n=== СТАТУС СЕРВОПРИВОДА ===")
        
        # Чтение позиции и скорости
        pos, speed, comm_result, error = self.packetHandler.ReadPosSpeed(self.servo_id)
        if comm_result == COMM_SUCCESS:
            print(f"Позиция: {pos} ({pos*360//4095}°)")
            print(f"Скорость: {speed}")
        
        # Чтение напряжения
        voltage, comm_result, error = self.packetHandler.read1ByteTxRx(
            self.servo_id, SMS_STS_PRESENT_VOLTAGE)
        if comm_result == COMM_SUCCESS:
            print(f"Напряжение: {voltage/10:.1f}V")
        
        # Чтение температуры
        temp, comm_result, error = self.packetHandler.read1ByteTxRx(
            self.servo_id, SMS_STS_PRESENT_TEMPERATURE)
        if comm_result == COMM_SUCCESS:
            print(f"Температура: {temp}°C")
        
        # Чтение тока
        current, comm_result, error = self.packetHandler.read2ByteTxRx(
            self.servo_id, SMS_STS_PRESENT_CURRENT_L)
        if comm_result == COMM_SUCCESS:
            current = self.packetHandler.scs_tohost(current, 15)
            print(f"Ток: {current}мА")
        
        # Чтение нагрузки
        load, comm_result, error = self.packetHandler.read2ByteTxRx(
            self.servo_id, SMS_STS_PRESENT_LOAD_L)
        if comm_result == COMM_SUCCESS:
            load = self.packetHandler.scs_tohost(load, 10)
            print(f"Нагрузка: {load}")
        
        # Статус движения
        moving, comm_result, error = self.packetHandler.ReadMoving(self.servo_id)
        if comm_result == COMM_SUCCESS:
            print(f"В движении: {'Да' if moving else 'Нет'}")
    
    # ==================== РЕЖИМ ПОЗИЦИОНИРОВАНИЯ ====================
    
    def set_servo_mode(self):
        """Установка режима позиционирования (серво-режим)"""
        # Установка режима 0 (позиционирование)
        comm_result, error = self.packetHandler.write1ByteTxRx(
            self.servo_id, SMS_STS_MODE, 0)
        if comm_result == COMM_SUCCESS:
            print("✓ Режим позиционирования установлен")
            return True
        return False
    
    def move_to_position(self, position, speed=DEFAULT_SPEED, acc=DEFAULT_ACC):
        """Перемещение в заданную позицию"""
        comm_result, error = self.packetHandler.WritePosEx(
            self.servo_id, position, speed, acc)
        if comm_result == COMM_SUCCESS:
            print(f"→ Движение к позиции {position} ({position*360//4095}°)")
            return True
        return False
    
    def wait_for_movement(self):
        """Ожидание завершения движения"""
        while True:
            moving, comm_result, error = self.packetHandler.ReadMoving(self.servo_id)
            if comm_result == COMM_SUCCESS and moving == 0:
                break
            time.sleep(0.01)
        print("✓ Движение завершено")
    
    # ==================== РЕЖИМ НЕПРЕРЫВНОГО ВРАЩЕНИЯ ====================
    
    def set_wheel_mode(self):
        """Установка режима непрерывного вращения"""
        comm_result, error = self.packetHandler.WheelMode(self.servo_id)
        if comm_result == COMM_SUCCESS:
            print("✓ Режим непрерывного вращения установлен")
            return True
        return False
    
    def rotate_wheel(self, speed, acc=DEFAULT_ACC):
        """Вращение в режиме колеса"""
        comm_result, error = self.packetHandler.WriteSpec(
            self.servo_id, speed, acc)
        if comm_result == COMM_SUCCESS:
            direction = "по часовой" if speed > 0 else "против часовой"
            print(f"↻ Вращение {direction} со скоростью {abs(speed)}")
            return True
        return False
    
    def stop_wheel(self):
        """Остановка вращения"""
        return self.rotate_wheel(0, 50)
    
    # ==================== УПРАВЛЕНИЕ ПАРАМЕТРАМИ ====================
    
    def set_torque(self, enable):
        """Включение/выключение момента"""
        value = 1 if enable else 0
        comm_result, error = self.packetHandler.write1ByteTxRx(
            self.servo_id, SMS_STS_TORQUE_ENABLE, value)
        if comm_result == COMM_SUCCESS:
            status = "включен" if enable else "выключен"
            print(f"✓ Момент {status}")
            return True
        return False
    
    def set_angle_limits(self, min_angle, max_angle):
        """Установка ограничений угла поворота"""
        # Запись минимального угла
        comm_result, error = self.packetHandler.write2ByteTxRx(
            self.servo_id, SMS_STS_MIN_ANGLE_LIMIT_L, min_angle)
        if comm_result != COMM_SUCCESS:
            return False
        
        # Запись максимального угла
        comm_result, error = self.packetHandler.write2ByteTxRx(
            self.servo_id, SMS_STS_MAX_ANGLE_LIMIT_L, max_angle)
        if comm_result == COMM_SUCCESS:
            print(f"✓ Ограничения установлены: {min_angle}-{max_angle}")
            return True
        return False
    
    def calibrate_center(self):
        """Калибровка центрального положения"""
        current_pos, comm_result, error = self.packetHandler.ReadPos(self.servo_id)
        if comm_result == COMM_SUCCESS:
            offset = MIDDLE_POSITION - current_pos
            # Разблокировка EEPROM
            self.packetHandler.unLockEprom(self.servo_id)
            # Запись смещения
            comm_result, error = self.packetHandler.write2ByteTxRx(
                self.servo_id, SMS_STS_OFS_L, offset)
            # Блокировка EEPROM
            self.packetHandler.LockEprom(self.servo_id)
            if comm_result == COMM_SUCCESS:
                print(f"✓ Центр откалиброван. Смещение: {offset}")
                return True
        return False

# ==================== ГЛАВНОЕ МЕНЮ ====================

def print_menu():
    """Вывод главного меню"""
    print("\n" + "="*50)
    print("ТЕСТИРОВАНИЕ СЕРВОПРИВОДА ST3215")
    print("="*50)
    print("1. Проверка связи (Ping)")
    print("2. Показать статус")
    print("3. Режим позиционирования")
    print("4. Режим непрерывного вращения")
    print("5. Тест скорости и ускорения")
    print("6. Управление моментом")
    print("7. Установка ограничений")
    print("8. Калибровка центра")
    print("9. Полный тест всех режимов")
    print("0. Выход")
    print("-"*50)
    print("Выберите опцию: ", end='')

def position_mode_test(controller):
    """Тест режима позиционирования"""
    print("\n=== ТЕСТ РЕЖИМА ПОЗИЦИОНИРОВАНИЯ ===")
    controller.set_servo_mode()
    time.sleep(0.5)
    
    positions = [
        (MIN_POSITION, "Минимум (0°)"),
        (1023, "90°"),
        (MIDDLE_POSITION, "Центр (180°)"),
        (3071, "270°"),
        (MAX_POSITION, "Максимум (360°)")
    ]
    
    for pos, name in positions:
        print(f"\nПеремещение: {name}")
        controller.move_to_position(pos, speed=1500, acc=50)
        controller.wait_for_movement()
        time.sleep(0.5)

def wheel_mode_test(controller):
    """Тест режима непрерывного вращения"""
    print("\n=== ТЕСТ РЕЖИМА НЕПРЕРЫВНОГО ВРАЩЕНИЯ ===")
    controller.set_wheel_mode()
    time.sleep(0.5)
    
    speeds = [
        (1000, "Медленно вперед"),
        (2000, "Быстро вперед"),
        (0, "Стоп"),
        (-1000, "Медленно назад"),
        (-2000, "Быстро назад"),
        (0, "Стоп")
    ]
    
    for speed, description in speeds:
        print(f"\n{description}")
        controller.rotate_wheel(speed)
        time.sleep(2)

def speed_acc_test(controller):
    """Тест различных скоростей и ускорений"""
    print("\n=== ТЕСТ СКОРОСТИ И УСКОРЕНИЯ ===")
    controller.set_servo_mode()
    
    tests = [
        (500, 10, "Медленно с малым ускорением"),
        (2000, 50, "Средняя скорость"),
        (4000, 255, "Максимальная скорость")
    ]
    
    for speed, acc, description in tests:
        print(f"\n{description}: скорость={speed}, ускорение={acc}")
        controller.move_to_position(MIN_POSITION, speed, acc)
        controller.wait_for_movement()
        controller.move_to_position(MAX_POSITION, speed, acc)
        controller.wait_for_movement()

def full_test(controller):
    """Полный тест всех функций"""
    print("\n=== ПОЛНЫЙ ТЕСТ ВСЕХ РЕЖИМОВ ===")
    
    # 1. Проверка связи
    print("\n[1/6] Проверка связи...")
    controller.ping()
    time.sleep(1)
    
    # 2. Чтение статуса
    print("\n[2/6] Чтение статуса...")
    controller.read_status()
    time.sleep(1)
    
    # 3. Тест позиционирования
    print("\n[3/6] Тест позиционирования...")
    position_mode_test(controller)
    
    # 4. Тест вращения
    print("\n[4/6] Тест непрерывного вращения...")
    wheel_mode_test(controller)
    
    # 5. Возврат в режим позиционирования
    print("\n[5/6] Возврат в режим позиционирования...")
    controller.set_servo_mode()
    time.sleep(0.5)
    
    # 6. Центрирование
    print("\n[6/6] Центрирование...")
    controller.move_to_position(MIDDLE_POSITION)
    controller.wait_for_movement()
    
    print("\n✓ Полный тест завершен!")

# ==================== ГЛАВНАЯ ПРОГРАММА ====================

def main():
    """Главная функция программы"""
    try:
        # Создание контроллера
        controller = ST3215Controller(DEVICENAME, BAUDRATE, SERVO_ID)
        
        # Проверка связи
        if not controller.ping():
            print("Сервопривод не отвечает. Проверьте подключение.")
            return
        
        while True:
            print_menu()
            choice = getch()
            
            if choice == '1':
                controller.ping()
            
            elif choice == '2':
                controller.read_status()
            
            elif choice == '3':
                position_mode_test(controller)
            
            elif choice == '4':
                wheel_mode_test(controller)
            
            elif choice == '5':
                speed_acc_test(controller)
            
            elif choice == '6':
                print("\n=== УПРАВЛЕНИЕ МОМЕНТОМ ===")
                print("1. Включить момент")
                print("2. Выключить момент")
                subchoice = getch()
                if subchoice == '1':
                    controller.set_torque(True)
                elif subchoice == '2':
                    controller.set_torque(False)
            
            elif choice == '7':
                print("\n=== УСТАНОВКА ОГРАНИЧЕНИЙ ===")
                print("Установка ограничений 1000-3000")
                controller.set_angle_limits(1000, 3000)
            
            elif choice == '8':
                print("\n=== КАЛИБРОВКА ЦЕНТРА ===")
                controller.calibrate_center()
            
            elif choice == '9':
                full_test(controller)
            
            elif choice == '0' or choice == chr(0x1b):  # ESC
                print("\nВыход из программы...")
                break
            
            else:
                print("\nНеверный выбор!")
            
            print("\nНажмите любую клавишу для продолжения...")
            getch()
    
    except Exception as e:
        print(f"\n✗ Ошибка: {e}")
    
    finally:
        print("\nПрограмма завершена.")

if __name__ == "__main__":
    main()