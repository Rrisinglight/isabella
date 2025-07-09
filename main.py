import os
import time
import threading
import requests
from flask import Flask, Response, render_template
from flask_socketio import SocketIO, emit
from hardware import HardwareManager, MANUAL_SERVO_STEP, AUTO_SERVO_STEP, SERVO_MIN_POS, SERVO_MAX_POS

# --- Configuration ---
ENCODER_URL = "http://192.168.1.106/isabella"
FIRST_START_FLAG_FILE = 'first_start.flag'

# --- App Initialization ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='gevent')
hardware = HardwareManager()

# --- State Management ---
app_state = {
    "auto_mode": True,
    "current_angle": hardware.position_to_angle(SERVO_MIN_POS),
    "servo_position": SERVO_MIN_POS,
    "is_sweeping": False,
    "rssi_a": 0,
    "rssi_b": 0,
    "stop_thread": False,
    "lock": threading.Lock()
}

def telemetry_thread():
    """A background thread that reads sensor data and performs auto-pilot logic."""
    # --- First Start Logic ---
    is_first_start = not os.path.exists(FIRST_START_FLAG_FILE)
    if is_first_start:
        open(FIRST_START_FLAG_FILE, 'w').close()
        # Give a moment for the client to connect before starting the sweep
        time.sleep(2)
        socketio.start_background_task(hardware.startup_sweep, app_state, socketio)

    while not app_state["stop_thread"]:
        with app_state["lock"]:
            if app_state["is_sweeping"]:
                # The sweep function handles its own telemetry updates
                time.sleep(0.5)
                continue

            # --- Read RSSI ---
            rssi_a, rssi_b = hardware.read_rssi()
            app_state["rssi_a"] = rssi_a
            app_state["rssi_b"] = rssi_b

            # --- Auto-pilot logic ---
            if app_state["auto_mode"]:
                diff = rssi_a - rssi_b
                new_position = app_state["servo_position"]
                if abs(diff) > 500:
                    if diff > 0:
                        new_position -= AUTO_SERVO_STEP
                    else:
                        new_position += AUTO_SERVO_STEP
                
                new_position = max(SERVO_MIN_POS, min(SERVO_MAX_POS, new_position))
                if new_position != app_state["servo_position"]:
                    app_state["servo_position"] = new_position
                    hardware.set_servo_position(new_position)

            # --- Update current angle ---
            app_state["current_angle"] = hardware.position_to_angle(app_state["servo_position"])

            # --- Prepare data for frontend ---
            telemetry_data = {
                "rssi_a": app_state["rssi_a"],
                "rssi_b": app_state["rssi_b"],
                "angle": app_state["current_angle"],
                "auto_mode": app_state["auto_mode"]
            }

        socketio.emit('telemetry', telemetry_data)
        time.sleep(0.5)

# --- Flask Routes ---
@app.route('/')
def index():
    """Serve the main dashboard page."""
    return render_template('index.html')

@app.route('/live')
def live_stream():
    """Proxy the video stream from the encoder."""
    def generate():
        try:
            r = requests.get(ENCODER_URL, stream=True, timeout=5)
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=4096):
                yield chunk
        except requests.exceptions.RequestException as e:
            print(f"Stream error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred in stream: {e}")

    return Response(generate(),
                   mimetype='video/mp2t',
                   headers={'Cache-Control': 'no-cache'})

# --- SocketIO Events ---
@socketio.on('connect')
def on_connect():
    print('Client connected')
    with app_state["lock"]:
        if "telemetry_thread_obj" not in app.extensions:
            thread = threading.Thread(target=telemetry_thread)
            app.extensions["telemetry_thread_obj"] = thread
            thread.start()

@socketio.on('disconnect')
def on_disconnect():
    print('Client disconnected')

@socketio.on('set_mode')
def handle_set_mode(data):
    with app_state["lock"]:
        is_auto = data.get('auto', True)
        app_state["auto_mode"] = is_auto
        if not is_auto:
            app_state["is_sweeping"] = False # Stop sweep if switching to manual
        print(f"Mode set to {'auto' if is_auto else 'manual'}")
        socketio.emit('mode_update', {'auto_mode': is_auto})

@socketio.on('manual_rotate')
def handle_manual_rotate(data):
    direction = data.get('direction')
    print(f"Received 'manual_rotate' event for direction: {direction}")
    with app_state["lock"]:
        if app_state["auto_mode"]:
            app_state["auto_mode"] = False
            socketio.emit('mode_update', {'auto_mode': False})
            print("Auto mode disabled due to manual override.")
        
        app_state["is_sweeping"] = False

        new_position = app_state["servo_position"]
        if direction == 'left':
            new_position -= MANUAL_SERVO_STEP
        elif direction == 'right':
            new_position += MANUAL_SERVO_STEP

        app_state["servo_position"] = new_position
    
    hardware.set_servo_position(new_position)

if __name__ == '__main__':
    try:
        print("Starting Flask-SocketIO server...")
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    finally:
        print("Shutting down...")
        app_state["stop_thread"] = True
        if "telemetry_thread_obj" in app.extensions:
            app.extensions["telemetry_thread_obj"].join()
        print("Server stopped.")