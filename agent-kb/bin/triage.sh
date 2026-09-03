#!/usr/bin/env bash
# 主循环。对 inbox/ 里的每个事件：
#   0) 线程直达：这个线程之前路由过 → 不再问 triage
#   1) Triage 分拣：读正文 → 匹配 _topics.md → ROUTE_JSON
#   2) 专属会话在跑？是 → resume 它接手（热路径）；否 → 新开一任，先读 _progress.md 和交接段
#   3) 轻量写回 + git commit
#   4) 轮换判断：agent 自请 / 上下文过大 / 事件数达标 → 让它趁热写交接，下次换新一任
set -euo pipefail
. "$(dirname "$0")/lib.sh"
lock
shopt -s nullglob
for ev in inbox/*.md; do
  [ "$(basename "$ev")" = "README.md" ] && continue
  echo "== $ev"
  thread=$(event_field "$ev" thread || true)
  topic=""

  # 0) 线程直达
  if [ -n "$thread" ]; then topic=$(thread_get "$thread"); fi
  if [ -n "$topic" ] && [ -d "topics/$topic" ]; then
    echo "   → 线程已知，直达 $topic（不经 triage）"
    log_row "$(basename "$ev")" "$topic" "1.0" "线程直达 $thread"
  else
    # 1) Triage：每次新开，读 _topics.md 很便宜，分拣不需要记忆
    if ! out=$(run_claude .claude/skills/triage/SKILL.md "按 triage 步骤处理事件文件：$ev"); then
      echo "   triage 调用失败，跳过"; continue; fi
    route=$(printf '%s' "$out" | result_text | grep -o 'ROUTE_JSON: .*' | tail -1 | sed 's/^ROUTE_JSON: //')
    if [ -z "$route" ]; then echo "   triage 没有给出 ROUTE_JSON，跳过"; continue; fi
    topic=$(printf '%s' "$route" | jq -r '.topic'); conf=$(printf '%s' "$route" | jq -r '.confidence')
    echo "   → topic=$topic confidence=$conf"
    [ -d "topics/$topic" ] || { echo "   主题目录不存在，改路由到 _unsorted"; topic=_unsorted; }
    log_row "$(basename "$ev")" "$topic" "$conf" "$(printf '%s' "$route" | jq -r '.reason')"
    [ -n "$thread" ] && [ "$topic" != "_unsorted" ] && thread_set "$thread" "$topic"
  fi

  # 2) 专属会话
  sid=$(sess_get "$topic" session_id); upd=$(sess_get "$topic" updated); now=$(date +%s)
  if [ -n "$sid" ] && [ $(( now - ${upd:-0} )) -gt $(( ROTATE_IDLE_DAYS * 86400 )) ]; then
    handoff "$topic" "闲置超过 ${ROTATE_IDLE_DAYS} 天"; sid=""
  fi
  task="按 topic-work 步骤处理。主题：$topic，事件文件：$ev"
  out=""
  if [ -n "$sid" ]; then
    echo "   → 是：专属会话在跑，Session Handoff 给 $sid"
    if ! out=$(run_claude .claude/skills/topic-work/SKILL.md "$task" "$sid"); then
      echo "   恢复失败，改为新开一任"; sess_close "$topic"; sid=""; out=""
    fi
  fi
  if [ -z "$sid" ]; then
    echo "   → 否：无专属会话，新开一任"
    if ! out=$(run_claude .claude/skills/topic-work/SKILL.md "你是这个主题新接手的一任，先读 topics/$topic/_progress.md，若有「给下一任的交接」段先消化它。$task"); then
      echo "   topic-work 调用失败，事件留在 inbox 等下次"; continue; fi
  fi
  text=$(printf '%s' "$out" | result_text)
  printf '%s\n' "$text" | grep -E '^(DONE|ROTATE):' | sed 's/^/   /' || true

  # 3) 记录会话状态，兜底移走事件，提交
  new_sid=$(printf '%s' "$out" | result_sid); ctx=$(printf '%s' "$out" | result_ctx)
  if [ -n "$new_sid" ]; then
    if [ -z "$sid" ]; then
      gen=$(sess_get "$topic" generation); sess_set "$topic" generation $(( ${gen:-0} + 1 ))
      sess_set "$topic" started "$now"; sess_set "$topic" events 0
    fi
    n=$(sess_get "$topic" events)
    sess_set "$topic" session_id "\"$new_sid\""; sess_set "$topic" updated "$now"
    sess_set "$topic" events $(( ${n:-0} + 1 )); sess_set "$topic" ctx_tokens "${ctx:-0}"
  fi
  if [ -f "$ev" ]; then mkdir -p "topics/$topic/events"; mv "$ev" "topics/$topic/events/"; fi
  commit "kb: $topic <- $(basename "$ev")"

  # 4) 轮换判断（趁上下文还热，交接质量最好）
  reason=""
  n=$(sess_get "$topic" events); ctx=$(sess_get "$topic" ctx_tokens)
  if printf '%s\n' "$text" | grep -q '^ROTATE:'; then
    reason="agent 自请：$(printf '%s\n' "$text" | grep '^ROTATE:' | tail -1 | sed 's/^ROTATE:[[:space:]]*//')"
  elif [ "${ctx:-0}" -ge "$ROTATE_CTX_TOKENS" ]; then reason="上下文约 ${ctx} tokens，超过 ${ROTATE_CTX_TOKENS}"
  elif [ "${n:-0}" -ge "$ROTATE_MAX_EVENTS" ]; then reason="本任已处理 ${n} 个事件"; fi
  [ -n "$reason" ] && handoff "$topic" "$reason"
done
echo "done"
