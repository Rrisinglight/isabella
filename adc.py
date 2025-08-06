import os
import time
import ADS1x15

ADS = ADS1x15.ADS1115(1, 0x48)
#print(os.path.basename(file))
#print("ADS1X15_LIB_VERSION: {}".format(ADS1x15.version))
# set gain to 4.096V max
ADS.setGain(ADS.PGA_4_096V)
print("Voltage")
while True :
    raw = ADS.readADC(1)
    aw = ADS.readADC(0)
    print(raw, aw)
    time.sleep(1)