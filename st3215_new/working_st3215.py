#!/usr/bin/env python
#
# *********     Working ST3215 Code     *********
# Auto-generated with working parameters
#

import sys
import os
import time

sys.path.append("..")
from scservo_sdk import *

# Working parameters
SCS_ID = 1
BAUDRATE = 115200
DEVICENAME = '/dev/ttyUSB1'

# Initialize
portHandler = PortHandler(DEVICENAME)
packetHandler = sms_sts(portHandler)

def initialize():
    if not portHandler.openPort():
        print("❌ Failed to open port")
        return False
        
    if not portHandler.setBaudRate(BAUDRATE):
        print("❌ Failed to set baudrate") 
        return False
        
    print("✅ Connection established")
    return True

def ping_test():
    model_number, result, error = packetHandler.ping(SCS_ID)
    if result == COMM_SUCCESS:
        print(f"🎉 Ping successful! Model: {model_number}")
        return True
    else:
        print(f"❌ Ping failed: {packetHandler.getTxRxResult(result)}")
        return False

def circular_motion():
    """Simple circular motion"""
    print("🔄 Starting circular motion...")
    
    try:
        for angle in range(0, 361, 10):
            position = int((angle / 360) * 4095)
            
            if 'sms_sts' == 'sms_sts':
                # SMS/STS protocol
                result, error = packetHandler.WritePosEx(SCS_ID, position, 100, 0)
            else:
                # SCSCL protocol  
                result, error = packetHandler.WritePos(SCS_ID, position, 0, 100)
                
            if result == COMM_SUCCESS:
                print(f"🎯 Angle: {angle:3d}° Position: {position:4d}")
            else:
                print(f"❌ Move failed: {packetHandler.getTxRxResult(result)}")
                
            time.sleep(0.2)
            
    except KeyboardInterrupt:
        print("\n⏹️ Motion stopped")

def main():
    if not initialize():
        return
        
    if not ping_test():
        return
        
    try:
        circular_motion()
    finally:
        portHandler.closePort()
        print("✅ Done")

if __name__ == "__main__":
    main()
