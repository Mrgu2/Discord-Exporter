#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[[ "$(uname -s)" == Linux ]] || { echo '此部署包用于 Linux；Mac 请保留原生安装。'; exit 1; }
docker compose version >/dev/null
[[ -f .env ]] || { echo '请先运行 Install-Docker.sh。'; exit 1; }
docker compose up -d --no-build
docker compose exec -T app python docker/manage.py start
for attempt in $(seq 1 120); do
  if docker compose exec -T app python docker/manage.py health >/dev/null 2>&1; then
    docker compose exec -T app python docker/manage.py status
    echo '应用已就绪。首次或远程访问运行 Configure-Tailscale.sh；不要开放公网端口。'
    exit 0
  fi
  sleep 1
done
echo '应用未就绪，请检查 docker compose logs --tail 80。已有资料保留。'; exit 1
