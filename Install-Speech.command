#!/bin/bash
cd "$(dirname "$0")" || exit 1
/bin/bash scripts/install_mac.sh --speech --no-open
result=$?
if [[ -t 0 ]]; then read -r -p "按回车关闭窗口…"; fi
exit "$result"
