from st3215 import ST3215
import time

servo = ST3215('/dev/ttyAMA2')
servo_id = 1  # ID вашего сервопривода

# Крайние положения для ST3215: 0 и 4095
servo.WritePosition(servo_id, 4095)
time.sleep(3)
#servo.WritePosition(servo_id, 2047)