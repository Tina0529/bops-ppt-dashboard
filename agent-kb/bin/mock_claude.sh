#!/usr/bin/env bash
# 假的 claude：不花钱跑通脚本逻辑。用法: CLAUDE_BIN=bin/mock_claude.sh bin/triage.sh
# 行为：triage 一律路由到 agent-lecture；topic-work 把事件移走并在 _progress.md 记一行；resume 时沿用同一个 session id。
prompt=""; sid=""; skill=""
while [ $# -gt 0 ]; do case "$1" in
  -p) prompt="$2"; shift 2;; --resume|--session-id) sid="$2"; shift 2;; --append-system-prompt) skill="$2"; shift 2;;
  --output-format|--permission-mode|--allowedTools|--model) shift 2;; *) shift;; esac; done
[ -n "$sid" ] || sid="mock-$(date +%s%N | cut -c1-13)"
ev=$(printf '%s' "$prompt" | grep -o 'inbox/[^ ，,]*' | head -1)
slug=$(printf '%s' "$prompt" | grep -o '主题：[^，,。]*' | head -1 | sed 's/主题：//')
case "$skill" in
  *"name: triage"*)   text="分拣完成
ROUTE_JSON: {\"topic\": \"agent-lecture\", \"confidence\": 0.92, \"reason\": \"mock\", \"also\": []}";;
  *"name: handoff"*)  printf '\n## 给下一任的交接（%s）\n- mock 交接：上一任处理了若干事件\n' "$(date +%F)" >> "topics/$slug/_progress.md"
                      text="HANDOFF_DONE: mock 交接已写入";;
  *)                  [ -n "$ev" ] && [ -f "$ev" ] && { mkdir -p "topics/$slug/events"; mv "$ev" "topics/$slug/events/"; }
                      printf '| %s | mock | 处理了 %s | ok |\n' "$(date '+%F %H:%M')" "$(basename "${ev:-?}")" >> "topics/$slug/_progress.md"
                      text="DONE: mock 处理了 ${ev:-?}"
                      [ "${MOCK_ROTATE:-0}" = 1 ] && text="ROTATE: mock 阶段结束
$text";;
esac
n=${MOCK_CTX:-15000}
jq -n --arg t "$text" --arg s "$sid" --argjson n "$n" \
  '{type:"result", result:$t, session_id:$s, usage:{iterations:[{input_tokens:100, cache_read_input_tokens:$n, cache_creation_input_tokens:500}]}}'
