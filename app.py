#C:\ngrok\ngrok.exe ngrok config add-authtoken 397RHeBEars1aI97zIg8CaPwA1A_3Cuf7Q48782cDS2QUM461
#C:\ngrok\ngrok.exe http 5000

from flask import Flask, request, jsonify, render_template, Response
from ultralytics import YOLO
import cv2
import threading
import time
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
import requests  # untuk kirim perintah ke ESP
import json
last_target_temp = None

app = Flask(__name__)

# ===================== KONFIGURASI DATABASE =====================
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/smart_ac'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ===================== MODEL DATABASE =====================
class ACHistory(db.Model):
    __tablename__ = 'ac_history'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.String(50))
    detected_people = db.Column(db.Integer)
    temperature = db.Column(db.Float)
    humidity = db.Column(db.Float)
    ac_status = db.Column(db.String(10))
    target_temp = db.Column(db.Float)

# ===================== YOLO & VARIABEL GLOBAL =====================
model = YOLO("model/last.pt")

sensor_data = {"temperature": None, "humidity": None}
detected_people = 0
ac_status = "OFF"
target_temp = None

camera_index = 0
cap = None

# ===================== KONFIGURASI ESP =====================
ESP_IP = "192.168.1.27"  # IP ESP AC virtual
ESP_PORT = 5005           # port receiver ESP

# ===================== KAMERA =====================
def open_camera():
    """Buka kamera dan reconnect jika gagal"""
    global cap
    while True:
        cap = cv2.VideoCapture(camera_index)
        if cap.isOpened():
            print("✅ Kamera berhasil dibuka")
            return
        print("❌ Kamera tidak ditemukan, mencoba ulang dalam 2 detik...")
        time.sleep(2)

def generate_frames():
    """Stream kamera + deteksi YOLO"""
    global cap, detected_people
    while True:
        if cap is None or not cap.isOpened():
            open_camera()
        success, frame = cap.read()
        if not success:
            print("⚠️ Frame gagal dibaca, reconnecting...")
            open_camera()
            continue

        results = model(frame, verbose=False)
        annotated_frame = results[0].plot()

        # ✅ Hitung jumlah person yang terdeteksi (class id = 0)
        detected_people = sum(1 for box in results[0].boxes if int(box.cls[0]) == 0)

        # ✅ Tampilkan jumlah orang di video stream
        cv2.putText(
            annotated_frame,
            f"People: {detected_people}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )


        ret, buffer = cv2.imencode('.jpg', annotated_frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

# ===================== DATA DARI ESP =====================
@app.route("/update_sensor", methods=["POST"])
def update_sensor():
    global sensor_data
    data = request.get_json()
    sensor_data["temperature"] = data.get("temperature")
    sensor_data["humidity"] = data.get("humidity")

    print(f"✅ Data disimpan ke database: Suhu={sensor_data['temperature']}, Kelembapan={sensor_data['humidity']}")
    return jsonify({"message": "Data berhasil diterima"}), 200

@app.route('/target_temp', methods=['GET'])
def get_target_temp():
    """Kirim data target suhu untuk ESP"""
    global target_temp, ac_status
    return jsonify({
        "target_temp": target_temp,
        "ac_status": ac_status
    })

@app.route('/data')
def get_data():
    """Kirim semua data ke web"""
    global sensor_data, detected_people, ac_status, target_temp
    return jsonify({
        "temperature": sensor_data["temperature"],
        "humidity": sensor_data["humidity"],
        "detected_people": detected_people,  
        "ac_status": ac_status,
        "target_temp": target_temp
    })

# ===================== ROUTE BARU: KIRIM PERINTAH SUHU LANGSUNG KE ESP =====================
@app.route('/set_ac', methods=['POST'])
def set_ac():
    """
    Kirim perintah AC langsung ke ESP:
    JSON body:
    {
        "ac_status": "ON",
        "target_temp": 20
    }
    """
    data = request.get_json()
    ac_status_cmd = data.get("ac_status")
    target_temp_cmd = data.get("target_temp")

    if ac_status_cmd is None or target_temp_cmd is None:
        return jsonify({"error": "ac_status atau target_temp tidak diberikan"}), 400

    # Kirim perintah ke ESP
    try:
        url = f"http://{ESP_IP}:{ESP_PORT}"
        payload = {"ac_status": ac_status_cmd, "target_temp": target_temp_cmd}
        response = requests.post(url, json=payload, timeout=2)
        return jsonify({
            "message": "Perintah dikirim ke ESP",
            "esp_response": response.text
        })
    except Exception as e:
        return jsonify({"error": f"Gagal mengirim ke ESP: {e}"}), 500

# ===================== LOGIKA AC OTOMATIS =====================
def ac_control_loop():
    """Kontrol suhu otomatis berdasarkan jumlah orang"""
    global ac_status, target_temp, detected_people

    while True:
        if detected_people == 0:
            ac_status = "OFF"
            target_temp = 23
        elif 1 <= detected_people <= 5:
            ac_status = "ON"
            target_temp = 21
        elif 6 <= detected_people <= 10:
            ac_status = "ON"
            target_temp = 20
        elif 11 <= detected_people <= 15:
            ac_status = "ON"
            target_temp = 19
        elif 20 <= detected_people <= 50:
            ac_status = "ON"
            target_temp = 18
        else:
            ac_status = "ON"
            target_temp = 23

        print(f"👥 Orang terdeteksi: {detected_people} | Status AC: {ac_status} | Target Suhu: {target_temp}")

        # Kirim langsung ke ESP AC
        try:
            url = f"http://{ESP_IP}:{ESP_PORT}"
            payload = {"ac_status": ac_status, "target_temp": target_temp}
            requests.post(url, json=payload, timeout=2)
        except:
            pass

        time.sleep(5)
# Log History 
@app.route('/logs')
def logs():
    history = ACHistory.query.order_by(ACHistory.id.desc()).limit(500).all()
    return render_template('logs.html', history=history)

# ===================== SIMPAN DATA KE DATABASE =====================
def save_to_db():
    global detected_people, sensor_data, ac_status, target_temp, last_target_temp

    while True:
        try:
            # Jangan simpan jika target_temp belum ada
            if target_temp is None:
                time.sleep(0.5)
                continue

            # Simpan HANYA jika target_temp berubah
            if last_target_temp != target_temp:
                with app.app_context():
                    entry = ACHistory(
                        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        detected_people=detected_people,
                        temperature=sensor_data.get("temperature"),
                        humidity=sensor_data.get("humidity"),
                        ac_status=ac_status,
                        target_temp=target_temp
                    )
                    db.session.add(entry)
                    db.session.commit()

                print(
                    f"💾 DB SAVE | Target Suhu berubah: "
                    f"{last_target_temp} ➜ {target_temp}"
                )

                # Update nilai terakhir SETELAH commit
                last_target_temp = target_temp

        except Exception as e:
            with app.app_context():
                db.session.rollback()
            print("❌ Gagal menyimpan ke database:", e)

        time.sleep(0.5)  # cek ringan, bukan interval logging

# ===================== ROUTE WEB =====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ===================== MAIN =====================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    open_camera()
    threading.Thread(target=ac_control_loop, daemon=True).start()
    threading.Thread(target=save_to_db, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
