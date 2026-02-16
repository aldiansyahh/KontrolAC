from flask import Flask, render_template, Response, jsonify
import requests
import time
from datetime import datetime

app = Flask(__name__)
ESP32_IP = "192.168.1.220"

@app.route('/')
def index():
    return render_template('cam.html')

# --- FUNGSI KAMERA (INI YANG TADI HILANG) ---
def gen_frames():
    while True:
        try:
            # Ambil gambar dari ESP32
            r = requests.get(f"http://{ESP32_IP}/capture", timeout=5)
            if r.status_code == 200:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + r.content + b'\r\n')
            time.sleep(0.1) # Jeda sedikit agar ESP32 tidak pingsan
        except:
            time.sleep(1)

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- FUNGSI SENSOR (SUDAH BENAR) ---
@app.route('/sensor_data')
def sensor_data():
    try:
        r = requests.get(f"http://{ESP32_IP}/data", timeout=3)
        data = r.json()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] SUHU: {data['temp']}°C | HUM: {data['hum']}%")
        
        return jsonify({
            "temperature": data['temp'],
            "humidity": data['hum'] if 'hum' in data else "--",
            "detected_people": 0,
            "ac_status": "MONITORING",
            "target_temp": 24
        })
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR SENSOR: {e}")
        return jsonify({"temperature": "--", "humidity": "--"})

if __name__ == '__main__':
    print(f"--- SERVER MONITORING + KAMERA AKTIF ---")
    app.run(host='0.0.0.0', port=5000, debug=False)