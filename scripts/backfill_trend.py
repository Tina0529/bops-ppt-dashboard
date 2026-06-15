#!/usr/bin/env python3
"""過去データを一括 fetch し、自然週/月でグルーピングして trend CSV を一括生成。

初回デプロイ時に推移トレンドの履歴を作る backfill。fetch_bops と同じ
net-time 口径（中断除外）で算出するので、以後の日次 cron と完全に整合する。

  BOPS_TOKEN=xxx python3 backfill_trend.py --end 2026-06-12 --days 70 --reports <dir>
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_bops import _post, compute_durations, LIST_API, DETAIL_API, _ts  # noqa: E402
from generate_xlsx import aggregate  # noqa: E402


def to_row(label, group):
    a = aggregate(group)
    return {'label': label, 'total': a['total'], 'generated': a['generated'],
            'completion': round(a['completion'], 4), 'avg_per_slide': round(a['avg_per_slide'], 1)}


def write_csv(path, rows):
    rows = sorted(rows, key=lambda r: r['label'])
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['label', 'total', 'generated', 'completion', 'avg_per_slide'])
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--end', required=True, help='基準日 YYYY-MM-DD')
    ap.add_argument('--days', type=int, default=70, help='何日前まで遡るか')
    ap.add_argument('--reports', required=True)
    ap.add_argument('--page-size', type=int, default=500)
    args = ap.parse_args()

    token = os.environ.get('BOPS_TOKEN')
    if not token:
        raise SystemExit('[backfill] BOPS_TOKEN 未設定')
    tt = os.environ.get('BOPS_TOKEN_TYPE', 'Bearer')
    headers = {'Content-Type': 'application/json', 'Authorization': f'{tt} {token}'}

    end = datetime.strptime(args.end, '%Y-%m-%d')
    start = end - timedelta(days=args.days)
    start_ts = _ts(start.strftime('%Y-%m-%d') + ' 00:00:00')
    end_ts = _ts(args.end + ' 23:59:59')

    data = _post(LIST_API, {'pageNum': 1, 'pageSize': args.page_size}, headers)
    plist = data.get('pptList', [])

    recs = []
    for p in plist:
        if not (start_ts <= _ts(p['createdAt']) <= end_ts):
            continue
        try:
            d = _post(DETAIL_API, {'bizId': p['bizId']}, headers)
            ppt = d.get('ppt') or {}
            logs = ppt.get('logs') or []
            dur = compute_durations(logs)
            actual = len(ppt['contents']) if ppt.get('contents') else p.get('slideCount', 0)
            recs.append({'company': p.get('companyName', ''), 'username': p.get('username', ''),
                         'status': p.get('status') or '', 'logsCount': len(logs),
                         'durationSec': dur['durationSec'], 'actualSlides': actual,
                         'breakCount': dur['breakCount'], 'createdAt': p['createdAt']})
        except Exception as e:
            print(f'  [warn] id={p.get("id")} 詳細取得失敗: {e}', file=sys.stderr)

    print(f'[backfill] {len(recs)} 件 ({start:%Y-%m-%d} ~ {args.end})', file=sys.stderr)

    wk = defaultdict(list)
    mo = defaultdict(list)
    for r in recs:
        dt = datetime.strptime(r['createdAt'][:10], '%Y-%m-%d')
        mon = dt - timedelta(days=dt.weekday())          # 自然週（月曜）
        wk[mon.strftime('%m-%d週')].append(r)
        mo[r['createdAt'][:7]].append(r)                  # 自然月 YYYY-MM

    write_csv(args.reports + '/trend_weekly.csv', [to_row(k, v) for k, v in wk.items()])
    write_csv(args.reports + '/trend_monthly.csv', [to_row(k, v) for k, v in mo.items()])
    print(f'[backfill] weekly {sorted(wk)} / monthly {sorted(mo)}', file=sys.stderr)


if __name__ == '__main__':
    main()
