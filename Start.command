#!/bin/bash
cd "$(dirname "$0")" || exit 1
export PATH="$PWD/.runtime/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! python3 scripts/doctor.py; then
  echo "请先双击 Install.command。"
  if [[ -t 0 ]]; then read -r -p "按回车关闭窗口…"; fi
  exit 1
fi
python3 scripts/desktop_launcher.py "$@"
