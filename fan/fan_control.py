import pigpio
import time
import sys

# Настройка пинов
FAN_PIN = 18
TACH_PIN = 23
PWM_FREQUENCY = 1000

# Инициализация pigpio
pi = pigpio.pi()
if not pi.connected:
    print("Failed to connect to pigpio daemon", file=sys.stderr)
    sys.exit(1)

# Настройка ШИМ для вентилятора
pi.set_PWM_frequency(FAN_PIN, PWM_FREQUENCY)
pi.set_PWM_range(FAN_PIN, 255)  # Диапазон 0-255

# Настройка пина тахометра с pull-up
pi.set_mode(TACH_PIN, pigpio.INPUT)
pi.set_pull_up_down(TACH_PIN, pigpio.PUD_UP)

# Счетчик импульсов
rpm_count = 0

def pulse_detected(gpio, level, tick):
    """Обработчик прерывания для подсчета импульсов тахометра"""
    global rpm_count
    if level == 0:  # Фронт спада (when_pressed в gpiozero)
        rpm_count += 1

# Настройка callback для обнаружения импульсов
# FALLING_EDGE эквивалентно when_pressed в gpiozero
cb = pi.callback(TACH_PIN, pigpio.FALLING_EDGE, pulse_detected)

try:
    while True:
        # Чтение температуры
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp = int(f.read()) / 1000

        # Плавное управление: 30°C = 30%, 75°C = 100%
        if temp <= 30:
            speed = 30
        elif temp >= 75:
            speed = 100
        else:
            # Линейная интерполяция: y = 30 + (temp - 30) * (70 / 45)
            speed = 30 + (temp - 30) * (70 / 45)

        # Установка скорости вентилятора (0-255 для pigpio)
        duty_cycle = int(speed * 255 / 100)
        pi.set_PWM_dutycycle(FAN_PIN, duty_cycle)

        # Измерение RPM за 3 секунды
        rpm_count = 0
        time.sleep(3)
        rpm = rpm_count * 10  # 60сек/3сек/2импульса = 10

        print(f"Temp: {temp:.1f}°C | Fan: {speed:.0f}% | RPM: {rpm:.0f}")

        # Проверка работоспособности
        if speed > 30 and rpm < 1000:
            print(f"WARNING: Fan may not be working properly", file=sys.stderr)

        time.sleep(2)  # Итого: 3+2=5 секунд между обновлениями

except KeyboardInterrupt:
    pass
finally:
    # Очистка ресурсов
    cb.cancel()  # Отключение callback
    pi.set_PWM_dutycycle(FAN_PIN, 0)  # Остановка вентилятора
    pi.stop()  # Закрытие соединения с pigpio