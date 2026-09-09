import logging
import requests
from flask import Flask, Response, jsonify, request, send_from_directory
import paho.mqtt.publish as publish

app = Flask(__name__, static_folder="static")
logging.basicConfig(level=logging.INFO)

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "neolink/argus_pt/control/ptz"
PTZ_AMOUNT = 32.0
PTZ_DIRECTIONS = {"up", "down", "left", "right"}


@app.route("/")
def index():
    return send_from_directory("static", "test.html")


# @app.route("/video_feed")
# def video_feed():
#     def generate():
#         url = ""
#         try:
#             # 接続確立は5秒、データ受信(read)は無制限(None)に設定
#             with requests.get(url, stream=True, timeout=(5, None)) as r:
#                 for chunk in r.iter_content(chunk_size=1024):
#                     if chunk:
#                         yield chunk
#         except Exception as e:
#             app.logger.error("映像ストリームエラー: %s", e)

#     return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/ptz", methods=["GET", "POST"])
def ptz_control():
    body = request.get_json(silent=True) or {}
    direction = (request.args.get("dir") or body.get("dir") or "").lower()

    if direction not in PTZ_DIRECTIONS:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"未対応の方向: {direction or '(なし)'}",
                }
            ),
            400,
        )

    payload = f"{direction} {PTZ_AMOUNT}"
    app.logger.info("MQTT publish: %s -> %s", MQTT_TOPIC, payload)

    try:
        publish.single(
            MQTT_TOPIC, payload=payload, hostname=MQTT_BROKER, port=MQTT_PORT
        )
    except Exception as e:
        app.logger.error("MQTT 送信エラー: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "success", "sent": payload})


if __name__ == "__main__":
    # threaded=True を追加して並行処理を許可
    app.run(host="0.0.0.0", port=5000, threaded=True)