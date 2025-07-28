#!/usr/bin/env python
#
# *********     Simple Circle Motion      *********
#

import time
from scservo_sdk import *

# Settings
SCS_ID = 1
BAUDRATE = 115200
DEVICENAME = '/dev/ttyUSB0'
protocol_end = 1

# Control addresses
ADDR_SCS_TORQUE_ENABLE = 40
ADDR_SCS_GOAL_POSITION = 42
ADDR_SCS_GOAL_SPEED = 46

# Initialize
portHandler = PortHandler(DEVICENAME)
packetHandler = PacketHandler(protocol_end)

# Open port
if not portHandler.openPort():
    print("Failed to open port")
    exit()

if not portHandler.setBaudRate(BAUDRATE):
    print("Failed to set baudrate")
    exit()

print("🚀 Starting simple circular motion...")

try:
    # Enable torque
    packetHandler.write1ByteTxRx(portHandler, SCS_ID, ADDR_SCS_TORQUE_ENABLE, 1)
    
    # Set speed
    packetHandler.write2ByteTxRx(portHandler, SCS_ID, ADDR_SCS_GOAL_SPEED, 150)
    
    # Continuous circular motion
    while True:
        for angle in range(0, 361, 10):  # 0° to 360° in 10° steps
            position = int((angle / 360) * 4095)
            packetHandler.write2ByteTxRx(portHandler, SCS_ID, ADDR_SCS_GOAL_POSITION, position)
            print(f"🎯 Angle: {angle:3d}° | Position: {position:4d}")
            time.sleep(0.2)
            
except KeyboardInterrupt:
    print("\n⏹️ Stopping...")
finally:
    # Disable torque
    packetHandler.write1ByteTxRx(portHandler, SCS_ID, ADDR_SCS_TORQUE_ENABLE, 0)
    portHandler.closePort()
    print("✅ Done!")