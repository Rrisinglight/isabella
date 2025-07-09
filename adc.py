"""
read analog input
measure at x (connect to AIN0).
"""

import os
import time
import ADS1x15

# ADS = ADS1x15.ADS1013(1, 0x48)
# ADS = ADS1x15.ADS1014(1, 0x48)
# ADS = ADS1x15.ADS1015(1, 0x48)
# ADS = ADS1x15.ADS1113(1, 0x48)
# ADS = ADS1x15.ADS1114(1, 0x48)

ADS = ADS1x15.ADS1115(1, 0x48)

print(os.path.basename(__file__))
print("ADS1X15_LIB_VERSION: {}".format(ADS1x15.__version__))


ADS.setGain(ADS.PGA_2_048V)
print("Voltage")

while True :
    raw = ADS.readADC(0) # 
    raw2 = ADS.readADC(1) #
    print(raw2, raw) #левая антенна adc1, правая антенна adc0
    #print("{0:.3f} V".format(ADS.toVoltage(raw)))
    #print("{0:.3f} V".format(ADS.toVoltage(raw2)))
    time.sleep(1)