#!/usr/bin/env bash
# BOPS PPT Dashboard サイト生成オーケストレータ（GitHub Pages 用）
#   自然週/自然月で当日分を集計し、docs/data/ に dashboard.json + detail.json を出力。
#   推移トレンドは docs/data/trend_*.csv に累積。最後に Lark へ図表カード通知。
#
# 必須 env:  BOPS_TOKEN（auth.py 自動ログインで取得）
# 任意 env:  BOPS_TOKEN_TYPE / LARK_WEBHOOK / DASHBOARD_URL / TARGET_DATE
set -euo pipefail
export LANG="${LANG:-C.UTF-8}" LC_ALL="${LC_ALL:-C.UTF-8}" 2>/dev/null || true

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
DATA_DIR="$ROOT/docs/data"
mkdir -p "$DATA_DIR"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

TARGET_DATE="${TARGET_DATE:-$(TZ=Asia/Tokyo python3 -c "from datetime import datetime;print(datetime.now().strftime('%Y-%m-%d'))")}"

read -r WK_START WK_PREV_START WK_PREV_END WK_LABEL MO_START MO_PREV_START MO_PREV_END MO_LABEL < <(python3 - "$TARGET_DATE" <<'PY'
import sys
from datetime import datetime, timedelta
d = datetime.strptime(sys.argv[1], '%Y-%m-%d')
wk_start = d - timedelta(days=d.weekday())
wk_prev_start = wk_start - timedelta(days=7)
wk_prev_end = d - timedelta(days=7)
mo_start = d.replace(day=1)
prev_last = mo_start - timedelta(days=1)
mo_prev_start = prev_last.replace(day=1)
mo_prev_end = prev_last.replace(day=min(d.day, prev_last.day))
print(wk_start.strftime('%Y-%m-%d'), wk_prev_start.strftime('%Y-%m-%d'), wk_prev_end.strftime('%Y-%m-%d'),
      wk_start.strftime('%m-%d週'), mo_start.strftime('%Y-%m-%d'), mo_prev_start.strftime('%Y-%m-%d'),
      mo_prev_end.strftime('%Y-%m-%d'), d.strftime('%Y-%m'))
PY
)

echo "[run_site] TARGET=${TARGET_DATE} / 本週 ${WK_START}〜${TARGET_DATE} / 本月 ${MO_START}〜${TARGET_DATE}"

F="$HERE/fetch_bops.py"
python3 "$F" --mode daily --date "$TARGET_DATE"            --out "$WORK/daily.tsv"
python3 "$F" --start "$WK_START"      --end "$TARGET_DATE"  --out "$WORK/weekly.tsv"
python3 "$F" --start "$WK_PREV_START" --end "$WK_PREV_END"  --out "$WORK/wprev.tsv"  || echo "[run_site] 週前期 取得失敗"
python3 "$F" --start "$MO_START"      --end "$TARGET_DATE"  --out "$WORK/monthly.tsv"
python3 "$F" --start "$MO_PREV_START" --end "$MO_PREV_END"  --out "$WORK/mprev.tsv"  || echo "[run_site] 月前期 取得失敗"

# 推移トレンド累積
TREND_W="$DATA_DIR/trend_weekly.csv"
TREND_M="$DATA_DIR/trend_monthly.csv"
python3 "$HERE/update_trend.py" "$WORK/weekly.tsv"  "$WK_LABEL" "$TREND_W"
python3 "$HERE/update_trend.py" "$WORK/monthly.tsv" "$MO_LABEL" "$TREND_M"

# サイト JSON 生成（前期/トレンドは存在すれば渡す）
WP=(); [ -s "$WORK/wprev.tsv" ] && WP=(--weekly-prev "$WORK/wprev.tsv")
MP=(); [ -s "$WORK/mprev.tsv" ] && MP=(--monthly-prev "$WORK/mprev.tsv")
python3 "$HERE/generate_site.py" --date "$TARGET_DATE" --out-dir "$DATA_DIR" \
  --daily   "$WORK/daily.tsv"   --daily-label   "${TARGET_DATE}（当日）" \
  --weekly  "$WORK/weekly.tsv"  ${WP[@]+"${WP[@]}"} --weekly-trend "$TREND_W" --weekly-label "${WK_START}〜${TARGET_DATE}（当週）" \
  --monthly "$WORK/monthly.tsv" ${MP[@]+"${MP[@]}"} --monthly-trend "$TREND_M" --monthly-label "${MO_LABEL}（当月）"

# Lark 図表カード（DASHBOARD_URL があれば footer にクリック可能リンク）
PREV="-"; [ -s "$WORK/wprev.tsv" ] && PREV="$WORK/wprev.tsv"
python3 "$HERE/make_summary.py" "$WORK/daily.tsv" "$WORK/weekly.tsv" "$PREV" "$TARGET_DATE" "$WORK/summary.json"
python3 "$HERE/lark_card.py" "$WORK/summary.json" "$TREND_W" "$TREND_M" || true

echo "[run_site] 完了: $DATA_DIR/dashboard.json + detail.json"
