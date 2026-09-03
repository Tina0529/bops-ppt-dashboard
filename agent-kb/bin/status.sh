#!/usr/bin/env bash
# 看一眼各主题的会话状态。用法: bin/status.sh
set -euo pipefail
. "$(dirname "$0")/lib.sh"
now=$(date +%s)
printf '%-18s %-6s %-8s %-10s %-9s %s\n' "主题" "第几任" "事件数" "上下文tok" "闲置" "会话"
for d in topics/*/; do
  slug=$(basename "$d"); [ "$slug" = "_template_progress.md" ] && continue
  sid=$(sess_get "$slug" session_id); gen=$(sess_get "$slug" generation); n=$(sess_get "$slug" events)
  ctx=$(sess_get "$slug" ctx_tokens); upd=$(sess_get "$slug" updated)
  idle="-"; [ -n "$upd" ] && idle="$(( (now - upd) / 3600 ))h"
  printf '%-18s %-6s %-8s %-10s %-9s %s\n' "$slug" "${gen:-0}" "${n:-0}" "${ctx:-0}" "$idle" "${sid:-（无，下一事件新开）}"
done
echo; echo "轮换阈值：事件 ≥ $ROTATE_MAX_EVENTS 或 上下文 ≥ $ROTATE_CTX_TOKENS tok 或 闲置 > ${ROTATE_IDLE_DAYS} 天 或 agent 自请"
