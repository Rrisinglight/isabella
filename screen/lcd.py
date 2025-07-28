# -*- coding: utf-8 -*-
import LCD_1in44
import time
from PIL import Image

def display_custom_image(image_path):
    """
    Функция для отображения пользовательской картинки на LCD дисплее
    
    Args:
        image_path (str): Путь к файлу изображения
    """
    
    # Инициализация LCD дисплея
    print("**********Инициализация LCD**********")
    LCD = LCD_1in44.LCD()
    
    # Установка направления сканирования (по умолчанию)
    Lcd_ScanDir = LCD_1in44.SCAN_DIR_DFT  # SCAN_DIR_DFT = D2U_L2R
    LCD.LCD_Init(Lcd_ScanDir)
    
    # Очистка экрана
    LCD.LCD_Clear()
    
    try:
        # Загрузка изображения
        print(f"Загрузка изображения: {image_path}")
        image = Image.open(image_path)
        
        # Получение размеров дисплея (128x128 пикселей)
        display_width = LCD.width   # 128
        display_height = LCD.height # 128
        
        print(f"Исходный размер изображения: {image.size}")
        print(f"Размер дисплея: {display_width}x{display_height}")
        
        # Изменение размера изображения под размер дисплея
        # Сохраняем пропорции и обрезаем лишнее
        image = image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        
        # Конвертируем в RGB режим (если изображение в другом формате)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        print("Отображение изображения на LCD...")
        
        # Отображение изображения на LCD
        LCD.LCD_ShowImage(image, 0, 0)
        
        print("Изображение успешно отображено!")
        
    except FileNotFoundError:
        print(f"ОШИБКА: Файл {image_path} не найден!")
    except Exception as e:
        print(f"ОШИБКА: {e}")
        # Очистка ресурсов в случае ошибки
        print("Завершение работы из-за ошибки...")
        LCD.module_exit()

def main():
    """
    Основная функция
    """
    image_path = "sirin.png"
    display_custom_image(image_path)
    
    # Бесконечный цикл для поддержания работы скрипта
    print("Скрипт запущен в бесконечном цикле. Нажмите Ctrl+C для выхода.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Получен сигнал KeyboardInterrupt. Завершение работы...")
        # При выходе из цикла (например, по Ctrl+C), корректно завершаем работу с дисплеем
        import LCD_1in44
        LCD = LCD_1in44.LCD()
        LCD.module_exit()
        print("Работа завершена.")

if __name__ == '__main__':
    main()