import logging
import os

from flask import Flask, jsonify, render_template, request
import paho.mqtt.publish as publish

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# 映像ストリーム: go2rtc の stream.html を ngrok 経由で公開した URL
# ngrok の URL は再起動ごとに変わるため、環境変数で上書きする
STREAM_URL = os.environ.get(
    "STREAM_URL",
    "https://sneezing-modify-observing.ngrok-free.dev/stream.html?src=argus_pt",
)

# MQTT ブローカー
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "neolink/argus_pt/control/ptz")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
MQTT_TLS = _env_flag("MQTT_TLS")

PTZ_AMOUNT = float(os.environ.get("PTZ_AMOUNT", "32.0"))
PTZ_DIRECTIONS = {"up", "down", "left", "right"}


@app.route("/")
def index():
    return render_template("test.html", stream_url=STREAM_URL)


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

    auth = None
    if MQTT_USERNAME:
        auth = {"username": MQTT_USERNAME, "password": MQTT_PASSWORD}

    try:
        publish.single(
            MQTT_TOPIC,
            payload=payload,
            hostname=MQTT_BROKER,
            port=MQTT_PORT,
            auth=auth,
            tls={} if MQTT_TLS else None,
        )
    except Exception as e:
        app.logger.error("MQTT 送信エラー (%s:%s): %s", MQTT_BROKER, MQTT_PORT, e)
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "success", "sent": payload})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), threaded=True)
