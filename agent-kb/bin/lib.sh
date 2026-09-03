#!/usr/bin/env bash
# 公共函数。被 triage.sh / rotate.sh / chat.sh / status.sh 以 source 方式加载。
KB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KB"
[ -f kb.conf ] && . ./kb.conf
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
CLAUDE_MODEL="${CLAUDE_MODEL:-}"
TOOLS="${TOOLS:-Read,Write,Edit,Glob,Grep,Bash(mv:*),Bash(mkdir:*),Bash(date:*),Bash(ls:*)}"
ROTATE_MAX_EVENTS="${ROTATE_MAX_EVENTS:-30}"
ROTATE_IDLE_DAYS="${ROTATE_IDLE_DAYS:-3}"
ROTATE_CTX_TOKENS="${ROTATE_CTX_TOKENS:-120000}"
SESSIONS="$KB/.sessions.json"    # slug -> {session_id, generation, started, updated, events, ctx_tokens}
THREADS="$KB/.threads.json"      # thread id -> slug（线程直达，跳过 triage）
[ -f "$SESSIONS" ] || echo '{}' > "$SESSIONS"
[ -f "$THREADS" ]  || echo '{}' > "$THREADS"
command -v jq >/dev/null || { echo "需要 jq（macOS: brew install jq）"; exit 1; }

new_uuid() { command -v uuidgen >/dev/null && uuidgen | tr 'A-Z' 'a-z' || python3 -c 'import uuid;print(uuid.uuid4())'; }

# run_claude <skill文件> <提示词> [session_id]  → stdout 为 claude 的 result JSON
# 新会话显式指定 --session-id，恢复会话用 --resume；两者都不会误用外层 Claude Code 会话（在交互式 Claude Code 里手动跑脚本时也安全）。
# stdin 接 /dev/null：cron 下没有 stdin，否则 claude 会等 3 秒。
run_claude() {
  local skill="$1" prompt="$2" sid="${3:-}"
  local args=(-p "$prompt" --output-format json --permission-mode acceptEdits
              --allowedTools "$TOOLS" --append-system-prompt "$(cat "$skill")")
  [ -n "$CLAUDE_MODEL" ] && args+=(--model "$CLAUDE_MODEL")
  if [ -n "$sid" ]; then args+=(--resume "$sid"); else args+=(--session-id "$(new_uuid)"); fi
  env -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_REMOTE_SESSION_ID -u CLAUDE_CODE_CONTAINER_ID \
    "$CLAUDE_BIN" "${args[@]}" < /dev/null
}
result_text() { jq -r '.result // empty'; }
result_sid()  { jq -r '.session_id // empty'; }
# 最近一次 API 调用的上下文大小 = 该次的 input + cache_read + cache_creation。result JSON 的 usage.iterations 里有逐次记录。
result_ctx()  { jq -r '(.usage.iterations // []) | if length > 0 then (.[-1] | ((.input_tokens // 0) + (.cache_read_input_tokens // 0) + (.cache_creation_input_tokens // 0))) else 0 end'; }

sess_get() { jq -r --arg t "$1" --arg k "$2" '.[$t][$k] // empty' "$SESSIONS"; }
sess_set() {  # slug key value（value 须是合法 JSON：数字直接给，字符串带引号）
  local tmp; tmp=$(mktemp)
  jq --arg t "$1" --arg k "$2" --argjson v "$3" '.[$t] = ((.[$t] // {}) + {($k): $v})' "$SESSIONS" > "$tmp" && mv "$tmp" "$SESSIONS"
}
sess_close() {  # 关闭会话但保留 generation 计数
  local tmp; tmp=$(mktemp)
  jq --arg t "$1" '.[$t] = {generation: ((.[$t].generation) // 0)}' "$SESSIONS" > "$tmp" && mv "$tmp" "$SESSIONS"
}
thread_get() { jq -r --arg th "$1" '.[$th] // empty' "$THREADS"; }
thread_set() { local tmp; tmp=$(mktemp); jq --arg th "$1" --arg t "$2" '.[$th] = $t' "$THREADS" > "$tmp" && mv "$tmp" "$THREADS"; }

event_field() { sed -n '2,/^---$/p' "$1" | grep -m1 "^$2:" | sed "s/^$2:[[:space:]]*//; s/^\"//; s/\"\$//"; }
log_row() { printf '| %s | %s | %s | %s | %s |\n' "$(date '+%F %T')" "$1" "$2" "$3" "$4" >> _log.md; }
commit() { git add -A >/dev/null 2>&1 || true; git commit -qm "$1" >/dev/null 2>&1 || true; }
lock() {
  if ! mkdir "$KB/.lock" 2>/dev/null; then echo "另一个 triage 正在运行，本次退出"; exit 0; fi
  trap 'rmdir "$KB/.lock" 2>/dev/null' EXIT
}

# handoff <slug> <原因>：让旧会话趁上下文还在，把只存在于它脑子里的东西写进 _progress.md，然后关闭会话
handoff() {
  local slug="$1" reason="$2" sid out
  sid=$(sess_get "$slug" session_id)
  [ -z "$sid" ] && return 0
  echo "   ↻ 轮换（$reason）：先让当前会话 $sid 写交接"
  if out=$(run_claude .claude/skills/handoff/SKILL.md "按 handoff 步骤交接。主题：$slug。轮换原因：$reason" "$sid"); then
    printf '%s' "$out" | result_text | grep -o 'HANDOFF_DONE: .*' | tail -1 | sed 's/^/   /'
  else
    echo "   旧会话无法恢复，跳过交接。下一任只能从 _progress.md 起步。"
  fi
  log_row "-" "$slug" "-" "轮换 #$(sess_get "$slug" generation)：$reason"
  sess_close "$slug"
  commit "kb: handoff $slug ($reason)"
}
