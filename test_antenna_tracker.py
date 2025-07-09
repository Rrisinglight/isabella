#!/usr/bin/env python3
"""
Тестовый симулятор antenna_tracker для отладки
Запускайте этот файл если настоящий antenna_tracker.py не работает
"""

import time
import json
import os
import threading
import random

class TestAntennaTracker:
    def __init__(self):
        self.command_file = "/tmp/antenna_commands.txt"
        self.status_file = "/tmp/antenna_status.json"
        
        # Симулированные значения
        self.position = 2047  # Центральная позиция
        self.left_rssi = 1500
        self.right_rssi = 1600
        self.mode = "manual"
        self.auto_mode = False
        
        self.running = True
        
        print("[TEST] Запуск тестового antenna_tracker...")
        print(f"[TEST] Файл команд: {self.command_file}")
        print(f"[TEST] Файл статуса: {self.status_file}")
        
        # Создаем файлы
        self.create_files()
        
        # Запускаем потоки
        self.command_thread = threading.Thread(target=self.command_loop)
        self.command_thread.daemon = True
        self.command_thread.start()
        
        self.status_thread = threading.Thread(target=self.status_loop)
        self.status_thread.daemon = True
        self.status_thread.start()
    
    def create_files(self):
        """Создает необходимые файлы"""
        if not os.path.exists(self.command_file):
            with open(self.command_file, 'w') as f:
                f.write("")
        
        if not os.path.exists(self.status_file):
            with open(self.status_file, 'w') as f:
                json.dump({}, f)
        
        print("[TEST] Файлы созданы")
    
    def write_status(self):
        """Записывает статус в файл"""
        try:
            status = {
                "rssi_a": self.left_rssi,
                "rssi_b": self.right_rssi,
                "angle": self.position,
                "auto_mode": self.auto_mode,
                "mode": self.mode,
                "timestamp": time.time()
            }
            
            with open(self.status_file, 'w') as f:
                json.dump(status, f)
                
        except Exception as e:
            print(f"[TEST ERROR] Ошибка записи статуса: {e}")
    
    def read_commands(self):
        """Читает команды из файла"""
        try:
            if os.path.exists(self.command_file):
                with open(self.command_file, 'r') as f:
                    command = f.read().strip()
                
                if command:
                    # Очищаем файл команд
                    with open(self.command_file, 'w') as f:
                        f.write("")
                    
                    return command
        except Exception as e:
            print(f"[TEST ERROR] Ошибка чтения команд: {e}")
        
        return None
    
    def execute_command(self, command):
        """Выполняет команду"""
        print(f"[TEST] Выполняем команду: {command}")
        
        if command == "left":
            self.mode = "manual"
            self.auto_mode = False
            self.position = max(1100, self.position - 15)
            print(f"[TEST] Поворот влево, позиция: {self.position}")
            
        elif command == "right":
            self.mode = "manual" 
            self.auto_mode = False
            self.position = min(2700, self.position + 15)
            print(f"[TEST] Поворот вправо, позиция: {self.position}")
            
        elif command == "auto":
            self.mode = "auto"
            self.auto_mode = True
            print(f"[TEST] Включен автоматический режим")
            
        elif command == "manual":
            self.mode = "manual"
            self.auto_mode = False
            print(f"[TEST] Включен ручной режим")
            
        elif command == "scan":
            self.mode = "scan"
            self.auto_mode = False
            print(f"[TEST] Запуск сканирования")
            self.simulate_scan()
    
    def simulate_scan(self):
        """Симулирует процесс сканирования"""
        print("[TEST] Симуляция сканирования...")
        
        # Сканируем от края до края
        for pos in range(1100, 2700, 50):
            self.position = pos
            # Симулируем изменение RSSI в зависимости от позиции
            # Максимум около позиции 2000
            distance_from_optimal = abs(pos - 2000)
            self.left_rssi = max(800, 2000 - distance_from_optimal // 2)
            self.right_rssi = max(800, 2000 - distance_from_optimal // 2)
            
            time.sleep(0.1)
        
        # После сканирования переходим в автоматический режим
        self.mode = "auto"
        self.auto_mode = True
        self.position = 2000  # Оптимальная позиция
        print("[TEST] Сканирование завершено, переход в авто режим")
    
    def simulate_auto_mode(self):
        """Симулирует автоматическое слежение"""
        if self.auto_mode:
            # Симулируем небольшие изменения позиции
            self.position += random.randint(-2, 2)
            self.position = max(1100, min(2700, self.position))
            
            # Симулируем изменения RSSI
            self.left_rssi += random.randint(-10, 10)
            self.right_rssi += random.randint(-10, 10)
            self.left_rssi = max(800, min(2500, self.left_rssi))
            self.right_rssi = max(800, min(2500, self.right_rssi))
    
    def command_loop(self):
        """Основной цикл обработки команд"""
        while self.running:
            try:
                command = self.read_commands()
                if command:
                    self.execute_command(command)
                
                time.sleep(0.1)
            except Exception as e:
                print(f"[TEST ERROR] Ошибка в цикле команд: {e}")
                time.sleep(1)
    
    def status_loop(self):
        """Цикл записи статуса"""
        while self.running:
            try:
                # Симулируем автоматический режим
                self.simulate_auto_mode()
                
                # Записываем статус
                self.write_status()
                
                time.sleep(0.2)  # 5 раз в секунду
            except Exception as e:
                print(f"[TEST ERROR] Ошибка в цикле статуса: {e}")
                time.sleep(1)

if __name__ == "__main__":
    print("=" * 50)
    print("ТЕСТОВЫЙ ANTENNA TRACKER")
    print("Используйте только для отладки!")
    print("=" * 50)
    
    test_tracker = TestAntennaTracker()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[TEST] Остановка тестового tracker...")
        test_tracker.running = False