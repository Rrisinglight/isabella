import time

# Mock hardware libraries for development if not on a Raspberry Pi
try:
    import ADS1x15
    from st3215 import ST3215
    ON_RASPBERRY_PI = True
except (ImportError, RuntimeError):
    print("WARNING: Could not import hardware libraries. Running in simulation mode.")
    ON_RASPBERRY_PI = False

# --- Configuration ---
SERVO_DEVICE = '/dev/ttyAMA2'
SERVO_ID = 1
# ST3215 Positions: 0-4095
SERVO_MIN_POS = 1100
SERVO_MAX_POS = 2700
SERVO_CENTER_POS = 2047
MANUAL_SERVO_STEP = 50  # Increased step for noticeable manual movement
AUTO_SERVO_STEP = 50

class HardwareManager:
    def __init__(self):
        self.ads = None
        self.servo = None
        if ON_RASPBERRY_PI:
            try:
                # Initialize ADC
                self.ads = ADS1x15.ADS1115(1, 0x48)
                self.ads.setGain(self.ads.PGA_4_096V)
                print("ADC Initialized.")
            except Exception as e:
                print(f"Error initializing ADC: {e}")
                self.ads = None

            try:
                # Initialize Servo
                self.servo = ST3215(SERVO_DEVICE)
                print("Servo Initialized.")
            except Exception as e:
                print(f"Error initializing Servo: {e}")
                self.servo = None
    
    def is_ready(self):
        return self.ads is not None and self.servo is not None

    def read_rssi(self):
        if self.is_ready():
            try:
                # adc1 is left antenna, adc0 is right antenna
                rssi_b = self.ads.readADC(0)
                rssi_a = self.ads.readADC(1)
                return rssi_a, rssi_b
            except Exception as e:
                print(f"Error reading ADC: {e}")
                return 0, 0
        else:
            # Simulate data
            return 15000 + time.time() % 100 * 10, 16000 - time.time() % 100 * 5

    def set_servo_position(self, position):
        # Clamp position to limits
        pos = max(SERVO_MIN_POS, min(SERVO_MAX_POS, int(position)))
        if self.is_ready():
            try:
                self.servo.WritePosition(SERVO_ID, pos)
                print(f"Servo moved to position: {pos}")
            except Exception as e:
                print(f"Error writing servo position: {e}")
        else:
             print(f"SIMULATED: Servo moved to position: {pos}")

    def startup_sweep(self, app_state, socketio):
        """Performs an initial sweep from left to right to find a signal."""
        print("Starting antenna sweep...")
        with app_state["lock"]:
            app_state["is_sweeping"] = True
        
        for pos in range(SERVO_MIN_POS, SERVO_MAX_POS + 1, AUTO_SERVO_STEP):
            if not app_state.get("is_sweeping", False):
                print("Sweep interrupted.")
                break

            self.set_servo_position(pos)
            with app_state["lock"]:
                app_state["servo_position"] = pos
                app_state["current_angle"] = self.position_to_angle(pos)
                rssi_a, rssi_b = self.read_rssi()
                app_state["rssi_a"] = rssi_a
                app_state["rssi_b"] = rssi_b
            
            socketio.emit('telemetry', {
                "rssi_a": rssi_a, "rssi_b": rssi_b,
                "angle": app_state["current_angle"],
                "auto_mode": app_state["auto_mode"]
            })
            
            # If a signal is found, stop sweeping
            if (rssi_a + rssi_b) > 20000: # Tune this threshold
                print("Signal found during sweep. Stopping sweep.")
                break
            
            time.sleep(0.1) # Small delay between steps

        with app_state["lock"]:
            app_state["is_sweeping"] = False
        print("Antenna sweep finished.")

    def position_to_angle(self, position):
        """Converts servo position (1100-2700) to angle (0-180)."""
        return round(((position - SERVO_MIN_POS) * 180) / (SERVO_MAX_POS - SERVO_MIN_POS)) 