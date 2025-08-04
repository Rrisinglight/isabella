from gpiozero import PWMLED, Button
import time
import sys

fan = PWMLED(18, frequency=1000)
tach = Button(23, pull_up=True, bounce_time=0.001)

rpm_count = 0

def pulse_detected():
    global rpm_count
    rpm_count += 1

tach.when_pressed = pulse_detected

try:
    while True:
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

        fan.value = speed / 100.0

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
    fan.close()
    tach.close()