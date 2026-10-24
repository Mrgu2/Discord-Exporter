#!/usr/bin/env bash
# An isolated login display, reachable only through a loopback SSH tunnel.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
export DISPLAY=:99
export XAUTHORITY="$PWD/data/linux-xauthority"
mkdir -p data
[[ ! -e /tmp/.X99-lock ]] || { echo '显示 :99 已被占用，未更改现有显示。'; exit 1; }
cookie=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
touch "$XAUTHORITY"
xauth -f "$XAUTHORITY" add "$DISPLAY" . "$cookie"
children=()
finish() {
  for child in "${children[@]}"; do kill "$child" 2>/dev/null || true; done
  wait || true
}
trap finish EXIT
trap 'exit 0' TERM INT
Xvfb "$DISPLAY" -screen 0 1440x1000x24 -nolisten tcp -auth "$XAUTHORITY" &
children+=("$!")
for attempt in {1..50}; do
  if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then break; fi
  sleep .1
done
xdpyinfo -display "$DISPLAY" >/dev/null
x11vnc -display "$DISPLAY" -auth "$XAUTHORITY" -no6 -listen 127.0.0.1 -rfbport 5900 -rfbportv6 -1 -nopw -forever -shared &
children+=("$!")
websockify --web /usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900 &
children+=("$!")
wait -n "${children[@]}"
