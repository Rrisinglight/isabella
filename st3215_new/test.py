#!/usr/bin/env python
#
# *********     ST3215 Enhanced Circular Motion     *********
#

import sys
import os
import time
import math

sys.path.append("..")
from scservo_sdk import *

# Рабочие параметры (найдены диагностикой)
SCS_ID = 1
BAUDRATE = 115200
DEVICENAME = '/dev/ttyUSB1'

# Параметры движения
SPEED = 100        # Скорость (0-1023)
ACCELERATION = 50  # Ускорение (0-254)

class ST3215Controller:
    def __init__(self):
        self.portHandler = PortHandler(DEVICENAME)
        self.packetHandler = sms_sts(self.portHandler)
        self.connected = False
        
    def connect(self):
        """Подключение к сервоприводу"""
        if not self.portHandler.openPort():
            print("❌ Failed to open port")
            return False
            
        if not self.portHandler.setBaudRate(BAUDRATE):
            print("❌ Failed to set baudrate")
            return False
            
        # Проверка подключения
        model_number, result, error = self.packetHandler.ping(SCS_ID)
        if result != COMM_SUCCESS:
            print(f"❌ Ping failed: {self.packetHandler.getTxRxResult(result)}")
            return False
            
        print(f"✅ Connected to ST3215 (Model: {model_number})")
        self.connected = True
        return True
        
    def disconnect(self):
        """Отключение"""
        if self.connected:
            self.portHandler.closePort()
            self.connected = False
            print("✅ Disconnected")
            
    def move_to_angle(self, angle_degrees, speed=None, acceleration=None):
        """Движение к углу в градусах (0-360°)"""
        if not self.connected:
            return False
            
        # Конвертация в позицию (0-4095 для 360°)
        position = int((angle_degrees % 360) / 360 * 4095)
        
        # Использование параметров по умолчанию
        spd = speed if speed is not None else SPEED
        acc = acceleration if acceleration is not None else ACCELERATION
        
        result, error = self.packetHandler.WritePosEx(SCS_ID, position, spd, acc)
        
        if result == COMM_SUCCESS:
            return True
        else:
            print(f"❌ Move failed: {self.packetHandler.getTxRxResult(result)}")
            return False
            
    def get_current_position(self):
        """Получение текущей позиции"""
        if not self.connected:
            return None
            
        position, result, error = self.packetHandler.ReadPos(SCS_ID)
        
        if result == COMM_SUCCESS:
            # Конвертация в градусы
            angle = (position / 4095) * 360
            return position, angle
        else:
            return None
            
    def is_moving(self):
        """Проверка движения"""
        if not self.connected:
            return False
            
        moving, result, error = self.packetHandler.ReadMoving(SCS_ID)
        return moving == 1 if result == COMM_SUCCESS else False
        
    def circular_motion_smooth(self, duration_seconds=10, steps_per_revolution=100):
        """Плавное круговое движение"""
        print(f"🌟 Starting smooth circular motion for {duration_seconds}s...")
        
        start_time = time.time()
        step = 0
        
        try:
            while (time.time() - start_time) < duration_seconds:
                # Вычисление угла
                angle = (step * 360 / steps_per_revolution) % 360
                
                # Движение
                if self.move_to_angle(angle, speed=150):
                    if step % 10 == 0:  # Печать каждого 10-го шага
                        current = self.get_current_position()
                        if current:
                            pos, curr_angle = current
                            print(f"🎯 Target: {angle:6.1f}° | Current: {curr_angle:6.1f}° | Step: {step}")
                
                step = (step + 1) % steps_per_revolution
                time.sleep(0.05)  # 50ms между шагами
                
        except KeyboardInterrupt:
            print("\n⏹️ Motion stopped by user")
            
    def circular_motion_stepwise(self, step_angle=10, step_delay=0.3):
        """Пошаговое круговое движение"""
        print(f"🔄 Starting stepwise circular motion ({step_angle}° steps)...")
        
        try:
            angle = 0
            while True:
                print(f"🎯 Moving to {angle}°")
                
                if self.move_to_angle(angle, speed=100):
                    # Ждем завершения движения
                    while self.is_moving():
                        time.sleep(0.1)
                        
                    current = self.get_current_position()
                    if current:
                        pos, curr_angle = current
                        print(f"   ✅ Reached {curr_angle:.1f}° (target: {angle}°)")
                
                angle = (angle + step_angle) % 360
                time.sleep(step_delay)
                
        except KeyboardInterrupt:
            print("\n⏹️ Motion stopped by user")
            
    def figure_eight(self, radius=45, duration=20):
        """Движение по восьмерке"""
        print(f"♾️ Starting figure-eight motion for {duration}s...")
        
        start_time = time.time()
        t = 0
        
        try:
            while (time.time() - start_time) < duration:
                # Параметрическое уравнение восьмерки
                angle = radius * math.sin(t) * math.cos(t) + 180
                angle = angle % 360
                
                if self.move_to_angle(angle, speed=120):
                    if int(t * 10) % 5 == 0:  # Печать каждые 0.5 секунды
                        print(f"♾️ Figure-8 angle: {angle:6.1f}°")
                
                t += 0.1
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n⏹️ Figure-eight stopped")

def main():
    print("🤖 ST3215 Advanced Motion Controller")
    print("=" * 40)
    
    # Создание контроллера
    controller = ST3215Controller()
    
    # Подключение
    if not controller.connect():
        return
        
    try:
        while True:
            print("\n📋 Motion Menu:")
            print("1. Smooth circular motion (10s)")
            print("2. Stepwise circular motion")
            print("3. Figure-eight motion")
            print("4. Manual angle input")
            print("5. Position status")
            print("6. Exit")
            
            choice = input("Enter choice (1-6): ").strip()
            
            if choice == '1':
                controller.circular_motion_smooth(duration_seconds=10)
            elif choice == '2':
                controller.circular_motion_stepwise()
            elif choice == '3':
                controller.figure_eight()
            elif choice == '4':
                try:
                    angle = float(input("Enter angle (0-360°): "))
                    controller.move_to_angle(angle)
                except ValueError:
                    print("❌ Invalid angle")
            elif choice == '5':
                current = controller.get_current_position()
                if current:
                    pos, angle = current
                    moving = controller.is_moving()
                    print(f"📍 Position: {pos} ({angle:.1f}°) {'🔄 Moving' if moving else '⏸️ Stopped'}")
            elif choice == '6':
                break
            else:
                print("❌ Invalid choice")
                
    except KeyboardInterrupt:
        print("\n⏹️ Program interrupted")
    finally:
        controller.disconnect()

if __name__ == "__main__":
    main()