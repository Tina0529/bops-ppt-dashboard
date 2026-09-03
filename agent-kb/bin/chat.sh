#!/usr/bin/env bash
# 直接和某个主题的专属 agent 对话：恢复它正在跑的会话。用法: bin/chat.sh <slug>
# 没有会话时新开一个交互会话，先读 _progress.md。聊完后该会话继续接收这个主题的事件。
set -euo pipefail
. "$(dirname "$0")/lib.sh"
slug="${1:?用法: bin/chat.sh <slug>}"
sid=$(sess_get "$slug" session_id); now=$(date +%s)
sess_set "$slug" updated "$now"
if [ -n "$sid" ]; then
  exec env -u CLAUDE_CODE_SESSION_ID "$CLAUDE_BIN" --resume "$sid"
else
  # 新开一任并登记：聊完之后，这个主题的后续事件会继续发给这个会话
  sid=$(new_uuid); gen=$(sess_get "$slug" generation)
  sess_set "$slug" generation $(( ${gen:-0} + 1 )); sess_set "$slug" started "$now"; sess_set "$slug" events 0
  sess_set "$slug" session_id "\"$sid\""; sess_set "$slug" ctx_tokens 0
  echo "$slug 目前没有专属会话，新开第 $(( ${gen:-0} + 1 )) 任：$sid"
  exec env -u CLAUDE_CODE_SESSION_ID "$CLAUDE_BIN" --session-id "$sid" \
    --append-system-prompt "$(cat .claude/skills/topic-work/SKILL.md)" \
    "你是主题 $slug 新接手的一任。先读 topics/$slug/_progress.md，若有「给下一任的交接」段先消化它，然后等我指示。"
fi
