#!/usr/bin/env python3
"""
Сервис автоматического слежения антенны за дроном
Работает независимо от веб-интерфейса
"""

import time
import threading
import os
from collections import deque
from st3215 import ST3215
import ADS1x15

class AntennaTracker:
    def __init__(self):
        # Настройки сервопривода
        self.servo = ST3215('/dev/ttyAMA2')
        self.servo_id = 1
        self.position = 2047  # Текущая позиция (центр)
        self.center_pos = 2047
        self.left_limit = 1100
        self.right_limit = 2700
        self.manual_step = 15
        
        # Настройки RSSI
        self.ads = ADS1x15.ADS1115(1, 0x48)
        self.ads.setGain(self.ads.PGA_2_048V)
        self.rssi_filter_size = 5  # Размер фильтра скользящего среднего
        self.left_rssi_buffer = deque(maxlen=self.rssi_filter_size)
        self.right_rssi_buffer = deque(maxlen=self.rssi_filter_size)
        self.rssi_threshold = 10  # Минимальная разница для движения
        
        # Режимы работы
        self.MODE_MANUAL = "manual"
        self.MODE_AUTO = "auto" 
        self.MODE_SCAN = "scan"
        self.current_mode = self.MODE_SCAN  # Начинаем со сканирования
        
        # Файлы для команд и статуса
        self.command_file = "/tmp/antenna_commands.txt"
        self.status_file = "/tmp/antenna_status.json"
        self.create_command_file()
        self.create_status_file()
        
        # Флаги и блокировки
        self.running = True
        self.position_lock = threading.Lock()
        
        print("Antenna Tracker инициализирован")
        print(f"Позиция: {self.position} (центр: {self.center_pos})")
        
    def create_status_file(self):
        """Создает файл статуса если его нет"""
        import json
        if not os.path.exists(self.status_file):
            with open(self.status_file, 'w') as f:
                json.dump({}, f)
        os.chmod(self.status_file, 0o666)
    
    def write_status(self, left_rssi, right_rssi):
        """Записывает текущий статус в файл"""
        import json
        try:
            status = {
                "rssi_a": left_rssi,
                "rssi_b": right_rssi, 
                "angle": self.position,
                "auto_mode": self.current_mode == self.MODE_AUTO,
                "mode": self.current_mode,
                "timestamp": time.time()
            }
            with open(self.status_file, 'w') as f:
                json.dump(status, f)
        except Exception as e:
            print(f"Ошибка записи статуса: {e}")
    
    def create_command_file(self):
        """Создает файл команд если его нет"""
        if not os.path.exists(self.command_file):
            with open(self.command_file, 'w') as f:
                f.write("")
        os.chmod(self.command_file, 0o666)
    
    def read_rssi(self):
        """Читает RSSI с обеих антенн и применяет фильтр"""
        try:
            # Читаем сырые значения (меняем местами левую и правую)
            left_raw = self.ads.readADC(0)   # Левая антенна теперь adc0
            right_raw = self.ads.readADC(1)  # Правая антенна теперь adc1
            
            # Добавляем в буферы
            self.left_rssi_buffer.append(left_raw)
            self.right_rssi_buffer.append(right_raw)
            
            # Вычисляем скользящее среднее
            left_rssi = sum(self.left_rssi_buffer) / len(self.left_rssi_buffer)
            right_rssi = sum(self.right_rssi_buffer) / len(self.right_rssi_buffer)
            
            return left_rssi, right_rssi
            
        except Exception as e:
            print(f"Ошибка чтения RSSI: {e}")
            return 0, 0
    
    def move_servo(self, new_position):
        """Перемещает сервопривод в новую позицию"""
        # Ограничиваем позицию
        new_position = max(self.left_limit, min(self.right_limit, new_position))
        
        with self.position_lock:
            if new_position != self.position:
                try:
                    self.servo.WritePosition(self.servo_id, new_position)
                    self.position = new_position
                    print(f"Позиция: {self.position}")
                except Exception as e:
                    print(f"Ошибка перемещения сервопривода: {e}")
    
    def scan_mode(self):
        """Режим сканирования - поиск оптимальной позиции"""
        print("Начинаем быстрое сканирование...")
        
        scan_data = []  # Список для хранения результатов: [(position, left_rssi, right_rssi, difference), ...]
        
        # Сканируем от левого края к правому с шагом 22 единицы (2 градуса)
        current_pos = self.left_limit
        while current_pos <= self.right_limit and self.current_mode == self.MODE_SCAN:
            # Перемещаем сервопривод
            self.move_servo(current_pos)
            time.sleep(0.1)  # Быстрее - ждем только 100мс
            
            # Читаем RSSI с обеих антенн
            left_rssi, right_rssi = self.read_rssi()
            
            # Вычисляем разность между антеннами
            difference = abs(left_rssi - right_rssi)
            
            # Сохраняем результат
            scan_data.append((current_pos, left_rssi, right_rssi, difference))
            
            print(f"Позиция {current_pos}: L={left_rssi:.0f}, R={right_rssi:.0f}, Разность={difference:.0f}")
            
            # Записываем статус для веб-интерфейса (для графика)
            self.write_status(left_rssi, right_rssi)
            
            # Двигаемся на следующую позицию (2 градуса = 22 единицы)
            current_pos += 22
            
            # Проверяем команды (для возможности остановки)
            self.check_commands()
        
        if len(scan_data) < 3:
            print("Недостаточно данных для анализа")
            self.current_mode = self.MODE_MANUAL
            return
        
        # Усредняем результаты по соседним точкам для устранения выбросов
        smoothed_data = []
        for i in range(len(scan_data)):
            # Берем текущую точку и соседние (окно размером 3)
            start_idx = max(0, i - 1)
            end_idx = min(len(scan_data), i + 2)
            
            # Усредняем разности в окне
            avg_difference = sum(data[3] for data in scan_data[start_idx:end_idx]) / (end_idx - start_idx)
            
            smoothed_data.append((scan_data[i][0], avg_difference))  # (position, smoothed_difference)
        
        # Находим позицию с минимальной усредненной разностью
        best_position, min_difference = min(smoothed_data, key=lambda x: x[1])
        
        print(f"Найдена оптимальная позиция: {best_position} (разность: {min_difference:.0f})")
        
        # Перемещаемся в оптимальную позицию
        self.move_servo(best_position)
        time.sleep(0.5)
        
        # Переходим в автоматический режим
        self.current_mode = self.MODE_AUTO
        print("Сканирование завершено, переход в автоматический режим")
    
    def auto_mode(self):
        """Автоматический режим слежения"""
        left_rssi, right_rssi = self.read_rssi()
        self.write_status(left_rssi, right_rssi)
        
        difference = left_rssi - right_rssi
        
        # Игнорируем небольшие различия
        if abs(difference) < self.rssi_threshold:
            return
        
        # Определяем направление движения - быстрый шаг 22 единицы (2 градуса)
        move_step = 22  # Увеличен шаг для быстрого слежения
        if difference > 0:  # Левая антенна сильнее - поворачиваем влево
            new_position = self.position - move_step
        else:  # Правая антенна сильнее - поворачиваем вправо
            new_position = self.position + move_step
        
        self.move_servo(new_position)
        print(f"AUTO: L={left_rssi:.1f}, R={right_rssi:.1f}, diff={difference:.1f}")
    
    def manual_move_left(self):
        """Движение влево в ручном режиме"""
        new_position = self.position - self.manual_step
        self.move_servo(new_position)
        print("MANUAL: Движение влево")
    
    def manual_move_right(self):
        """Движение вправо в ручном режиме"""
        new_position = self.position + self.manual_step
        self.move_servo(new_position)
        print("MANUAL: Движение вправо")
    
    def check_commands(self):
        """Проверяет файл команд и выполняет их"""
        try:
            if os.path.exists(self.command_file):
                with open(self.command_file, 'r') as f:
                    command = f.read().strip()
                
                if command:
                    # Очищаем файл команд СРАЗУ
                    with open(self.command_file, 'w') as f:
                        f.write("")
                    
                    # Выполняем команду
                    if command == "left":
                        self.current_mode = self.MODE_MANUAL
                        self.manual_move_left()
                    elif command == "right":
                        self.current_mode = self.MODE_MANUAL
                        self.manual_move_right()
                    elif command == "auto":
                        print("Переход в автоматический режим")
                        self.current_mode = self.MODE_AUTO
                    elif command == "manual":
                        print("Переход в ручной режим")
                        self.current_mode = self.MODE_MANUAL
                    elif command == "scan":
                        print("Запуск сканирования")
                        self.current_mode = self.MODE_SCAN
                    
        except Exception as e:
            print(f"Ошибка чтения команд: {e}")
    
    def run(self):
        """Основной цикл работы"""
        print("Запуск сервиса слежения антенны")
        
        # Устанавливаем начальную позицию
        self.move_servo(self.center_pos)
        time.sleep(1)
        
        try:
            while self.running:
                # Проверяем команды от веб-интерфейса
                self.check_commands()
                
                # Выполняем действия в зависимости от режима
                if self.current_mode == self.MODE_SCAN:
                    self.scan_mode()
                elif self.current_mode == self.MODE_AUTO:
                    self.auto_mode()
                else:  # В ручном режиме просто читаем и записываем статус
                    left_rssi, right_rssi = self.read_rssi()
                    self.write_status(left_rssi, right_rssi)
                
                time.sleep(0.1)  # Основная частота цикла
                
        except KeyboardInterrupt:
            print("\nОстановка сервиса...")
        except Exception as e:
            print(f"Ошибка в основном цикле: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Очистка ресурсов"""
        self.running = False
        print("Сервис остановлен")

# Функции для внешнего управления (для Flask)
def send_command(command):
    """Отправляет команду в сервис слежения"""
    command_file = "/tmp/antenna_commands.txt"
    try:
        with open(command_file, 'w') as f:
            f.write(command)
        return True
    except Exception as e:
        print(f"Ошибка отправки команды: {e}")
        return False

def get_status():
    """Возвращает статус устройства (можно расширить)"""
    # Здесь можно добавить чтение статуса из файла, если нужно
    return {"status": "running"}

if __name__ == "__main__":
    tracker = AntennaTracker()
    tracker.run()