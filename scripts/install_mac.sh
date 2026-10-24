#!/bin/bash
# Only the explicit installer downloads dependencies. Never copies user data.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.runtime/bin:$PATH:/opt/homebrew/bin:/usr/local/bin"
export npm_config_cache="$PWD/.runtime/npm-cache"
speech=false
open_page=true
check=false
system_install=true
for argument in "$@"; do
  case "$argument" in
    --speech) speech=true ;;
    --no-open) open_page=false ;;
    --check) check=true ;;
    --no-system-install) system_install=false ;;
    *) echo "未知参数：$argument"; exit 2 ;;
  esac
done
[[ "$(uname -s)" == Darwin ]] || { echo "当前安装入口仅支持 macOS。"; exit 1; }
if $check; then exec python3 scripts/doctor.py; fi
trap 'echo "安装未完成。请处理上方错误后重新运行 Install.command；已有归档保留。"' ERR
need_brew() {
  if ! $system_install; then
    echo "缺少 $1；本次指定不安装系统依赖。"; exit 1
  fi
  if ! command -v brew >/dev/null; then
    echo "缺少 $1。请先安装 Homebrew：https://brew.sh/ ，完成后重新双击 Install.command。"
    echo "也可自行安装 Python 3.10+（https://www.python.org/downloads/macos/）和 Node.js 20+（https://nodejs.org/）。"
    exit 1
  fi
}
python_ready=false
for candidate in "$(command -v python3 || true)" /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if [[ -n "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' 2>/dev/null; then
    selected_python="$candidate"; python_ready=true; break
  fi
done
if ! $python_ready; then
  need_brew 'Python 3.10+'
  brew install python@3.13
  selected_python="$(brew --prefix python@3.13)/libexec/bin/python3"
fi
if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)' 2>/dev/null || ! command -v npm >/dev/null; then
  need_brew 'Node.js 20+'
  brew install node@22
  export PATH="$(brew --prefix node@22)/bin:$PATH"
fi
mkdir -p .runtime/bin
# Remember custom/venv/nvm paths for Finder, whose PATH differs from Terminal.
for tool in python3 node npm; do
  source_path="$(command -v "$tool")"
  if [[ "$tool" == python3 ]]; then source_path="$selected_python"; fi
  destination="$PWD/.runtime/bin/$tool"
  if [[ "$source_path" != "$destination" ]]; then
    if [[ -e "$destination" && ! -L "$destination" ]]; then
      echo "为保留已有文件，拒绝覆盖 $destination"; exit 1
    fi
    ln -sf "$source_path" "$destination"
  fi
done
echo '安装固定版本的浏览器工具（需要联网）…'
npm ci --ignore-scripts --no-audit --no-fund
node node_modules/playwright/cli.js install chromium
"$selected_python" scripts/doctor.py
if $speech; then
  [[ "$(uname -m)" == arm64 ]] || { echo '语音转写仅支持 Apple Silicon Mac；基础功能可正常使用。'; exit 1; }
  if ! command -v ffmpeg >/dev/null; then need_brew FFmpeg; brew install ffmpeg; fi
  "$selected_python" scripts/install_speech.py
fi
if [[ -f helpers/login-assistant-mac.zip ]]; then
  "$selected_python" scripts/install_login_assistants.py --mac-zip helpers/login-assistant-mac.zip
else
  echo '缺少首次连接工具，请取得包含 helpers/login-assistant-mac.zip 的完整分发包。'; exit 1
fi
echo '安装检查通过。首次使用：连接 Discord → 配置频道与答疑人 → 保存一次 → 生成稿件。'
if $open_page; then "$selected_python" scripts/desktop_launcher.py; fi
