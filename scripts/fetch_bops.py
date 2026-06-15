#!/usr/bin/env python3
"""
BOPS PPT データ取得スクリプト（Python 版・自動化用）

ブラウザ版 fetch_bops.js と同じ API を叩き、純所要時間（中断除外）を計算して
generate_xlsx.py が読む 17 列 TSV を出力する。CI / cron から非対話で実行できる。

認証:
  BOPS の bearer token を環境変数 BOPS_TOKEN（必須）/ BOPS_TOKEN_TYPE（既定 Bearer）で渡す。
  token はブラウザの devtools Console で `copy(localStorage.getItem('token'))` で取得。
  ※ BOPS の token は対話ログインで発行される短期トークン。CI 化する場合は
    CLOUD_DEPLOY.md の「認証の制約」を必ず読むこと。

使い方:
  # 日次（指定日 1 日分）
  BOPS_TOKEN=xxx python3 fetch_bops.py --mode daily --date 2026-06-12 --out day.tsv

  # 週次（指定終了日から過去 7 日 = 滚动7日）
  BOPS_TOKEN=xxx python3 fetch_bops.py --mode weekly --end 2026-06-12 --out week.tsv

  # 明示的な期間指定
  BOPS_TOKEN=xxx python3 fetch_bops.py --start 2026-06-06 --end 2026-06-12 --out week.tsv
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta

LIST_API = 'https://bops-api.gbase.ai/business/ppt/pageQuery'
DETAIL_API = 'https://bops-api.gbase.ai/business/ppt/get'
GAP_THRESHOLD = 3600  # 1 時間以上の log gap は中断（純所要から除外）

HEADER = ['id', 'topic', 'username', 'companyName', 'themePresetId', 'strategyName',
          'status', 'slideCount', 'actualSlides', 'createdAt', 'startTime', 'endTime',
          'durationSec', 'logsCount', 'originalDurationSec', 'breakCount', 'maxGapSec']


def _post(url, body, headers, retries=3):
    data = json.dumps(body).encode('utf-8')
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode('utf-8', 'ignore')[:200]
            if e.code == 401:
                raise SystemExit('[fetch_bops] 401 Unauthorized — BOPS_TOKEN が失効しています。'
                                 'ブラウザで再ログインし token を取り直してください。')
            last_err = f'HTTP {e.code}: {body_txt}'
        except Exception as e:
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f'[fetch_bops] API 呼び出しに失敗: {url}\n  {last_err}')


def _ts(s):
    return datetime.strptime(s.replace(' ', 'T')[:19], '%Y-%m-%dT%H:%M:%S').timestamp()


def compute_durations(logs):
    """logs から純所要時間（中断除外）等を計算。"""
    if not logs:
        return {'startTime': None, 'endTime': None, 'durationSec': 0,
                'originalDurationSec': 0, 'breakCount': 0, 'maxGapSec': 0}
    sorted_logs = sorted(logs, key=lambda x: x['createdAt'])
    start, end = sorted_logs[0]['createdAt'], sorted_logs[-1]['createdAt']
    original = round(_ts(end) - _ts(start))
    net, breaks, max_gap = 0, 0, 0
    for i in range(1, len(sorted_logs)):
        gap = round(_ts(sorted_logs[i]['createdAt']) - _ts(sorted_logs[i - 1]['createdAt']))
        max_gap = max(max_gap, gap)
        if gap >= GAP_THRESHOLD:
            breaks += 1
        else:
            net += gap
    return {'startTime': start, 'endTime': end, 'durationSec': net,
            'originalDurationSec': original, 'breakCount': breaks, 'maxGapSec': max_gap}


def resolve_range(args):
    """--mode / --date / --start / --end から (start_date, end_date) を決める。"""
    if args.start and args.end:
        return args.start, args.end
    if args.mode == 'daily':
        d = args.date or args.end
        if not d:
            raise SystemExit('[fetch_bops] daily モードは --date が必要です')
        return d, d
    if args.mode == 'weekly':
        if not args.end:
            raise SystemExit('[fetch_bops] weekly モードは --end が必要です')
        end_dt = datetime.strptime(args.end, '%Y-%m-%d')
        start_dt = end_dt - timedelta(days=6)  # 滚动7日（終了日含む過去7日）
        return start_dt.strftime('%Y-%m-%d'), args.end
    raise SystemExit('[fetch_bops] 期間を決定できません（--start/--end か --mode+--date/--end）')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['daily', 'weekly'], default='weekly')
    ap.add_argument('--date', help='daily モードの対象日 YYYY-MM-DD')
    ap.add_argument('--start', help='期間開始 YYYY-MM-DD')
    ap.add_argument('--end', help='期間終了 YYYY-MM-DD')
    ap.add_argument('--out', required=True, help='出力 TSV パス')
    ap.add_argument('--page-size', type=int, default=300)
    args = ap.parse_args()

    token = os.environ.get('BOPS_TOKEN')
    if not token:
        raise SystemExit('[fetch_bops] 環境変数 BOPS_TOKEN が未設定です')
    token_type = os.environ.get('BOPS_TOKEN_TYPE', 'Bearer')
    headers = {'Content-Type': 'application/json',
               'Authorization': f'{token_type} {token}'}

    start_date, end_date = resolve_range(args)
    start_ts = _ts(start_date + ' 00:00:00')
    end_ts = _ts(end_date + ' 23:59:59')

    list_data = _post(LIST_API, {'pageNum': 1, 'pageSize': args.page_size}, headers)
    ppt_list = list_data.get('pptList', [])
    filtered = [p for p in ppt_list if start_ts <= _ts(p['createdAt']) <= end_ts]
    print(f'[fetch_bops] {len(filtered)} 件 ({start_date} ~ {end_date}, mode={args.mode})')

    rows = [HEADER]
    for p in filtered:
        try:
            d = _post(DETAIL_API, {'bizId': p['bizId']}, headers)
            ppt = d.get('ppt') or {}
            logs = ppt.get('logs') or []
            dur = compute_durations(logs)
            actual_slides = len(ppt['contents']) if ppt.get('contents') else p.get('slideCount', 0)
            rows.append([
                p.get('id', ''), p.get('topic', ''), p.get('username', ''),
                p.get('companyName', ''), p.get('themePresetId') or '-', p.get('strategyName', ''),
                p.get('status') or '', p.get('slideCount', 0), actual_slides,
                p.get('createdAt', ''), dur['startTime'] or p.get('createdAt', ''),
                dur['endTime'] or p.get('createdAt', ''), dur['durationSec'], len(logs),
                dur['originalDurationSec'], dur['breakCount'], dur['maxGapSec'],
            ])
        except SystemExit:
            raise
        except Exception as e:
            print(f'  [warn] id={p.get("id")} の詳細取得に失敗: {e}', file=sys.stderr)

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join('\t'.join(str(c) for c in r) for r in rows))
    print(f'[fetch_bops] 書き出し: {args.out}（{len(rows) - 1} 件）')
    # 期間メタを stdout 最終行に（呼び出し側が拾えるよう）
    print(f'RANGE\t{start_date}\t{end_date}')


if __name__ == '__main__':
    main()
