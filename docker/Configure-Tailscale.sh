#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# The host owns Tailscale. No host control socket is mounted in the container.
command -v tailscale >/dev/null || { echo '先在宿主机安装并授权 Tailscale，见 README-Docker.md。'; exit 1; }
https_port=${ARCHIVE_HTTPS_PORT:-$(docker compose config --environment | awk -F= '$1=="ARCHIVE_HTTPS_PORT" {print $2; exit}')}
https_port=${https_port:-443}
[[ "$https_port" == 443 || "$https_port" == 8443 ]] || { echo 'HTTPS 端口仅支持 443 / 8443'; exit 1; }
status=$(tailscale status --json)
printf '%s' "$status" | docker compose exec -T app python docker/configure_tailscale.py --https-port "$https_port"
backend=$(docker compose exec -T app python docker/manage.py status | sed -n 's/.*"url": "\([^"]*\)".*/\1/p')
[[ "$backend" =~ ^http://127\.0\.0\.1:[0-9]+$ ]] || { echo '无法确认本部署端口，未修改转发。'; exit 1; }
existing=$(tailscale serve status --json)
# Automatic setup is allowed only when no Serve route exists. Existing routing is preserved.
if [[ "$existing" == '{}' || "$existing" == 'null' ]]; then
  sudo tailscale serve --bg --https="$https_port" "$backend"
else
  echo "已有 Tailscale Serve 配置，未覆盖。请核对后执行：sudo tailscale serve --bg --https=$https_port $backend"
fi
echo '配置保存后重启本应用以加载所有者设置：'
docker compose exec -T app python docker/restart.py
