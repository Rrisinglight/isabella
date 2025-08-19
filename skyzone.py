#!/usr/bin/env python3

import RPi.GPIO as GPIO
import time

class SkyzoneVTX:
    def __init__(self, clk_pin=17, mosi_pin=27, cs_pin=22):
        """
        Инициализация VTX Skyzone X
        
        Args:
            clk_pin: GPIO пин для CLK (по умолчанию 27)
            mosi_pin: GPIO пин для MOSI/DAT (по умолчанию 17)
            cs_pin: GPIO пин для CS (по умолчанию 22)
        """
        self.clk_pin = clk_pin
        self.mosi_pin = mosi_pin
        self.cs_pin = cs_pin
        
        # Таблица частот для каналов
        self.frequency_table = {
            'L': [0x4C151, 0x4C391, 0x4D1F1, 0x4E031, 0x4E291, 0x4F0D1, 0x4F331, 0x50171],
            'R': [0x503B1, 0x51211, 0x52051, 0x522B1, 0x530F1, 0x53351, 0x54191, 0x543F1],
            'F': [0x520D1, 0x52211, 0x52351, 0x53091, 0x531D1, 0x53311, 0x54051, 0x54191],
            'E': [0x512B1, 0x51171, 0x51031, 0x502F1, 0x541F1, 0x54331, 0x55071, 0x551B1],
            'B': [0x52071, 0x52191, 0x522D1, 0x523F1, 0x53131, 0x53251, 0x53391, 0x540B1],
            'A': [0x540B1, 0x53371, 0x53231, 0x530F1, 0x523B1, 0x52271, 0x52131, 0x513F1]
        }
        
        # Настройка GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.clk_pin, GPIO.OUT)
        GPIO.setup(self.mosi_pin, GPIO.OUT)
        GPIO.setup(self.cs_pin, GPIO.OUT)
        
        # Начальное состояние пинов
        GPIO.output(self.clk_pin, GPIO.LOW)
        GPIO.output(self.mosi_pin, GPIO.LOW)
        GPIO.output(self.cs_pin, GPIO.HIGH)  # CS active low
        
        self.current_mode = 'mix'  # По умолчанию режим Mix
        
    def _send_bit(self, bit):
        """Отправка одного бита"""
        GPIO.output(self.mosi_pin, GPIO.HIGH if bit else GPIO.LOW)
        time.sleep(0.000001)  # 1us
        GPIO.output(self.clk_pin, GPIO.HIGH)
        time.sleep(0.000001)
        GPIO.output(self.clk_pin, GPIO.LOW)
        time.sleep(0.000001)
        
    def _send_25bit_lsb(self, data):
        """
        Отправка 25-битных данных LSB first
        
        Args:
            data: 25-битное значение для отправки
        """
        GPIO.output(self.cs_pin, GPIO.LOW)  # Активируем CS
        time.sleep(0.000001)
        
        # Отправляем 25 бит LSB first
        for i in range(25):
            bit = (data >> i) & 0x01
            self._send_bit(bit)
            
        time.sleep(0.000001)
        GPIO.output(self.cs_pin, GPIO.HIGH)  # Деактивируем CS
        
    def set_channel(self, band, channel):
        """
        Установка канала
        
        Args:
            band: Диапазон ('A', 'B', 'E', 'F', 'R', 'L')
            channel: Номер канала (1-8)
        """
        if band not in self.frequency_table:
            raise ValueError(f"Неверный диапазон: {band}")
        
        if channel < 1 or channel > 8:
            raise ValueError(f"Неверный канал: {channel}. Должен быть от 1 до 8")
            
        freq_value = self.frequency_table[band][channel - 1]
        
        # Отправляем команду установки Register A
        self._send_25bit_lsb(0x000110)
        time.sleep(0.0005)  # 500us задержка
        
        # Отправляем частоту (Register B)
        self._send_25bit_lsb(freq_value)
        
        print(f"Установлен канал {band}{channel} (0x{freq_value:05X})")
        
    def switch_to_diversity(self):
        """Переключение в режим Diversity"""
        if self.current_mode == 'diversity':
            print("Уже в режиме Diversity")
            return
            
        # Отправляем команду переключения
        self._send_25bit_lsb(0x000110)
        time.sleep(0.0005)  # 500us
        self._send_25bit_lsb(0x000110)
        
        self.current_mode = 'diversity'
        print("Переключено в режим Diversity")
        
    def switch_to_mix(self):
        """Переключение в режим Mix"""
        if self.current_mode == 'mix':
            print("Уже в режиме Mix")
            return
            
        # Специальная последовательность для Mix режима
        GPIO.output(self.cs_pin, GPIO.HIGH)
        GPIO.output(self.clk_pin, GPIO.HIGH)
        time.sleep(0.1)  # 100ms
        GPIO.output(self.clk_pin, GPIO.LOW)
        time.sleep(0.5)  # 500ms
        
        # Отправляем команду
        self._send_25bit_lsb(0x000110)
        time.sleep(0.0005)  # 500us
        self._send_25bit_lsb(0x000110)
        
        self.current_mode = 'mix'
        print("Переключено в режим Mix")
        
    def toggle_mode(self):
        """Переключение между режимами Mix и Diversity"""
        if self.current_mode == 'mix':
            self.switch_to_diversity()
        else:
            self.switch_to_mix()
            
    def band_scan(self, delay=0.5):
        """
        Сканирование всех каналов во всех диапазонах
        
        Args:
            delay: Задержка между переключениями каналов (в секундах)
        """
        print("Начинаем сканирование диапазонов...")
        
        for band in ['R', 'A', 'B', 'E', 'F', 'L']:
            print(f"\nСканирование диапазона {band}:")
            for channel in range(1, 9):
                self.set_channel(band, channel)
                time.sleep(delay)
                
        print("\nСканирование завершено")
        
    def cleanup(self):
        """Очистка GPIO"""
        GPIO.cleanup()


# Пример использования
if __name__ == "__main__":
    # Создаем объект VTX
    vtx = SkyzoneVTX()
    
    try:
        # Устанавливаем канал R1 (Raceband канал 1 - 5658MHz)
        # vtx.set_channel('A', 1)
        # time.sleep(4)
        
        # Переключаемся в режим Diversity
        #vtx.switch_to_diversity()
        #time.sleep(1)
        
        # Устанавливаем канал F4 (Fatshark канал 4 - 5800MHz)
        vtx.set_channel('A', 1)
        time.sleep(4)
        
        # Переключаемся обратно в режим Mix
        #vtx.switch_to_mix()
        #time.sleep(1)
        
        # Быстрое сканирование всех каналов
        #vtx.band_scan(delay=2   )
        
    except KeyboardInterrupt:
        print("\nПрерывание пользователем")
        
    finally:
        vtx.cleanup()
        print("GPIO очищены")