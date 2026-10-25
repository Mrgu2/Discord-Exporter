#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[[ "$(uname -s)" == Linux ]] || { echo '此部署包用于 Linux，Mac 使用原生安装。'; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo '本次验收镜像仅支持 Linux amd64。'; exit 1; }
docker compose version >/dev/null
if [[ ! -f .env ]]; then
  umask 077
  printf 'ARCHIVE_IMAGE=discordarchive-linux:v2026.10.25.2\nARCHIVE_PORT=8765\n' > .env
fi
if ! docker image inspect discordarchive-linux:v2026.10.25.2 >/dev/null 2>&1; then
  [[ -f discordarchive-linux-amd64.tar.gz ]] || { echo '缺少离线镜像，请从同一 Release 下载 discordarchive-linux-amd64.tar.gz。'; exit 1; }
  sha256sum -c CHECKSUMS.sha256
  gzip -dc discordarchive-linux-amd64.tar.gz | docker load
fi
docker compose run --rm --no-deps --entrypoint python app docker/initialize.py
bash Start-Docker.sh
