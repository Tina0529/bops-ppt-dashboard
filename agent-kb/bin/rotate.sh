#!/usr/bin/env bash
# 手动轮换某个主题的会话：让它写交接，下一个事件新开一任。用法: bin/rotate.sh <slug> [原因]
set -euo pipefail
. "$(dirname "$0")/lib.sh"
slug="${1:?用法: bin/rotate.sh <slug> [原因]}"
[ -n "$(sess_get "$slug" session_id)" ] || { echo "$slug 没有在跑的会话"; exit 0; }
handoff "$slug" "${2:-手动轮换}"
