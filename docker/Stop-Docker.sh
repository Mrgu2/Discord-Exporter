#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# No -v: data, images, models and login survive a stop.
docker compose stop app
echo '部署已停止，资料卷保留；运行 Start-Docker.sh 恢复。'
