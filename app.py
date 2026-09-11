import logging
import os
import socket

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

def _parse_broker(raw, default_port):
    """MQTT_BROKER を (host, port) に分解する。

    ngrok は 'tcp://0.tcp.ngrok.io:12345' 形式で表示するため、そのまま
    貼り付けられても動くようにスキーム / ポートを取り除く。
    ポートが含まれていればそちらを優先する。
    """
    host = (raw or "").strip()
    port = default_port

    for scheme in ("tcp://", "mqtt://", "mqtts://", "ssl://"):
        if host.lower().startswith(scheme):
            host = host[len(scheme):]
            break

    host = host.rstrip("/")

    # host:port (IPv6 の '[::1]:1883' も考慮)
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            rest = host[end + 1:]
            hostpart = host[1:end]
            if rest.startswith(":") and rest[1:].isdigit():
                return hostpart, int(rest[1:])
            return hostpart, port
    elif host.count(":") == 1:
        hostpart, _, portpart = host.partition(":")
        if portpart.isdigit():
            return hostpart, int(portpart)

    return host, port


# MQTT ブローカー
# 注意: Render 等のクラウドから使う場合、localhost / 192.168.x.x は到達できない。
# 公開ブローカー (HiveMQ Cloud 等) か ngrok TCP トンネルのホスト名を指定すること。
MQTT_BROKER, MQTT_PORT = _parse_broker(
    os.environ.get("MQTT_BROKER", "localhost"),
    int(os.environ.get("MQTT_PORT", "1883")),
)
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "neolink/argus_pt/control/ptz")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
MQTT_TLS = _env_flag("MQTT_TLS")
MQTT_TIMEOUT = float(os.environ.get("MQTT_TIMEOUT", "5.0"))

PTZ_AMOUNT = float(os.environ.get("PTZ_AMOUNT", "32.0"))
PTZ_MOVES = {"up", "down", "left", "right"}
PTZ_DIRECTIONS = PTZ_MOVES | {"stop"}


def _is_private_host(host):
    """localhost / プライベート IP かどうか (クラウドから到達不可の可能性が高い)"""
    try:
        addr = socket.gethostbyname(host)
    except OSError:
        return False
    parts = addr.split(".")
    if parts[0] == "127" or parts[0] == "10":
        return True
    if parts[0] == "192" and parts[1] == "168":
        return True
    if parts[0] == "172" and 16 <= int(parts[1]) <= 31:
        return True
    return False


@app.route("/")
def index():
    return render_template("test.html", stream_url=STREAM_URL)


@app.route("/health")
def health():
    """設定の確認用。パスワードは返さない。"""
    reachable = None
    detail = None
    try:
        with socket.create_connection((MQTT_BROKER, MQTT_PORT), timeout=MQTT_TIMEOUT):
            reachable = True
    except OSError as e:
        reachable = False
        detail = str(e)

    return jsonify(
        {
            "mqtt_broker": MQTT_BROKER,
            "mqtt_port": MQTT_PORT,
            "mqtt_topic": MQTT_TOPIC,
            "mqtt_tls": MQTT_TLS,
            "mqtt_auth": bool(MQTT_USERNAME),
            "broker_reachable": reachable,
            "broker_error": detail,
            "broker_looks_private": _is_private_host(MQTT_BROKER),
        }
    )


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

    payload = direction if direction == "stop" else f"{direction} {PTZ_AMOUNT}"
    app.logger.info("MQTT publish: %s -> %s", MQTT_TOPIC, payload)

    auth = None
    if MQTT_USERNAME:
        auth = {"username": MQTT_USERNAME, "password": MQTT_PASSWORD}

    # ブローカーに到達できない場合、publish.single は長時間ブロックすることがある。
    # 先に短いタイムアウトで TCP 接続を確認し、原因が分かるエラーを返す。
    try:
        with socket.create_connection((MQTT_BROKER, MQTT_PORT), timeout=MQTT_TIMEOUT):
            pass
    except OSError as e:
        hint = ""
        if _is_private_host(MQTT_BROKER):
            hint = (
                " MQTT_BROKER がプライベートアドレスです。"
                "クラウド (Render 等) からは LAN 内のブローカーに接続できません。"
                "公開ブローカーか ngrok TCP トンネルを設定してください。"
            )
        msg = f"MQTT ブローカーに接続できません ({MQTT_BROKER}:{MQTT_PORT}): {e}.{hint}"
        app.logger.error(msg)
        return jsonify({"status": "error", "message": msg}), 502

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
        return jsonify({"status": "error", "message": str(e)}), 502

    return jsonify({"status": "success", "sent": payload})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), threaded=True)
