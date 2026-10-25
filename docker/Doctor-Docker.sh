#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
docker compose version >/dev/null
[[ -f .env ]] || { echo '缺少 .env，请先运行 Install-Docker.sh。'; exit 1; }
docker compose config --quiet
docker compose ps
# Status contains only this application's PID, URL and startup preference.
docker compose exec -T app python docker/manage.py status
docker compose exec -T app python docker/manage.py health
echo '容器配置与健康检查通过。请用实际工作台地址核对访问。'
