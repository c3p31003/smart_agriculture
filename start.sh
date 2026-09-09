#!/usr/bin/env bash
set -euo pipefail

echo "== 1. Docker コンテナ =="
docker start neolink go2rtc
docker ps --format 'table {{.Names}}\t{{.Status}}'

echo
echo "== 2. Mosquitto =="
systemctl is-active --quiet mosquitto || sudo systemctl start mosquitto
echo "  mosquitto: $(systemctl is-active mosquitto)"

echo
echo "== 3. neolink の MQTT 接続確認 =="
sleep 3
docker logs --tail 30 neolink 2>&1 | grep -i mqtt \
  || echo "  ⚠ MQTT ログなし → neolink.toml の [mqtt] を確認"

echo
echo "== 4. ファイル確認 =="
[ -f ~/flask-app/static/test.html ] || echo "  ⚠ static/test.html がありません"

echo
echo "== 5. Flask 起動 =="
echo "  → http://192.168.1.197:5000/"
echo "  （停止は Ctrl+C）"
cd ~/flask-app && exec python3 app.py
