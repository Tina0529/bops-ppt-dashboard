#!/usr/bin/env bash
# 定时入口：先采集各入口，再跑 triage。放进 cron / launchd，每 10 分钟一次即可。
#   */10 * * * * cd ~/kb && bin/tick.sh >> .tick.log 2>&1
set -uo pipefail
cd "$(dirname "$0")/.."
[ -n "${IMAP_HOST:-}" ]   && python3 bin/ingest_mail.py
[ -n "${MEETING_DIR:-}" ] && python3 bin/ingest_meeting.py
bin/triage.sh
