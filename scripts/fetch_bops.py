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
import calendar
import hashlib
import io
import re
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
import urllib.error
from datetime import datetime, timedelta

LIST_API = 'https://bops-api.gbase.ai/business/ppt/pageQuery'
DETAIL_API = 'https://bops-api.gbase.ai/business/ppt/get'
# 2026-10-20 以降の新フロー（gbase-pptx-svg skill）は会話内で PPTX を生成し、PPT 一覧に登録されない。
# 会話の成果物（outputs/ 配下の .pptx）を chat cacheFile API から拾って同じ 17 列で集計する。
CHAT_LIST_API = 'https://bops-api.gbase.ai/business/chat/pageQuery'
CHAT_FILES_API = 'https://bops-api.gbase.ai/business/chat/cacheFile/search'
CHAT_DOWNLOAD_API = 'https://bops-api.gbase.ai/business/chat/cacheFile/download'
CHAT_MSG_API = 'https://bops-api.gbase.ai/business/chat/chatMessage/getById/'
CHAT_STRATEGY = '新Skill（会話内生成）'
CHAT_LOOKBACK_DAYS = 14  # 期間開始より前に作られた会話でも、期間内に新しい版を出すことがある
CACHE_DIR = os.environ.get('BOPS_CHAT_CACHE', os.path.join(tempfile.gettempdir(), 'bops_chat_cache'))
GAP_THRESHOLD = 3600  # 1 時間以上の log gap は中断（純所要から除外）

HEADER = ['id', 'topic', 'username', 'companyName', 'themePresetId', 'strategyName',
          'status', 'slideCount', 'actualSlides', 'createdAt', 'startTime', 'endTime',
          'durationSec', 'logsCount', 'originalDurationSec', 'breakCount', 'maxGapSec']


KC_TOKEN_URL = 'https://iam.sparticle.com/realms/saas/protocol/openid-connect/token'
KC_CLIENT_ID = 'gbase-bops-prod'


def _refresh(headers):
    """access_token は寿命 5 分。auth.py が BOPS_AUTH_REFRESH_FILE に残した refresh_token で更新し、
    headers を差し替える（会話内 PPT の取得で処理が数分を超えるようになったため）。成功で True。"""
    path = os.environ.get('BOPS_AUTH_REFRESH_FILE')
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, encoding='utf-8') as f:
            saved = json.load(f)
        body = urllib.parse.urlencode({'grant_type': 'refresh_token', 'client_id': KC_CLIENT_ID,
                                       'refresh_token': saved['refresh_token']}).encode()
        req = urllib.request.Request(KC_TOKEN_URL, data=body, method='POST',
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            j = json.loads(resp.read().decode('utf-8'))
        headers['Authorization'] = f"{headers['Authorization'].split(' ')[0]} {j['access_token']}"
        if j.get('refresh_token'):
            saved['refresh_token'] = j['refresh_token']
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(saved, f)
        print('[fetch_bops] access token を refresh しました', file=sys.stderr)
        return True
    except Exception as e:
        print(f'[fetch_bops] token refresh 失敗: {e}', file=sys.stderr)
        return False


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
            if e.code == 401 and attempt < retries - 1 and _refresh(headers):
                continue
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


def _to_jst(s):
    """BOPS の createdAt/updatedAt/logs.createdAt は **UTC** 文字列（時差表記なし）。
    ダッシュボードは JST 日付でバケットするため、取得直後に +9h して JST 文字列へ統一する。
    2026-08-21 までこの変換が無く、日次/週次/月次の全バケットが 9 時間ズレていた。"""
    if not s:
        return s
    t = datetime.strptime(str(s).replace(' ', 'T')[:19], '%Y-%m-%dT%H:%M:%S')
    return (t + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M:%S')


# BOPS pageQuery はページングパラメータが currentPage（pageNum ではない）で、
# pageSize は約 80 でサーバ側 cap される。1 ページだけ取ると月次が 80 件で
# 頭打ちになるため、期間の下限を過ぎるまで全ページを舐める。
PAGE_SIZE_CAP = 80
MAX_PAGES = 200  # 暴走保険（80×200=16,000 件）


def fetch_ppt_list(headers, start_ts, end_ts):
    """期間 [start_ts, end_ts] にかかる PPT を全ページ走査で取得する。

    リストは createdAt 降順なので、ページ内の最古が start_ts を下回ったら打ち切り。
    ページ跨ぎで新規レコードが挿入されるとズレて重複しうるため bizId で去重。
    """
    seen, out = set(), []
    for page in range(1, MAX_PAGES + 1):
        data = _post(LIST_API, {'currentPage': page, 'pageSize': PAGE_SIZE_CAP}, headers)
        plist = data.get('pptList', [])
        if not plist:
            break
        for p in plist:
            biz = p.get('bizId')
            if biz in seen:
                continue
            seen.add(biz)
            if start_ts <= _ts(_to_jst(p['createdAt'])) <= end_ts:
                out.append(p)
        oldest = min(_ts(_to_jst(p['createdAt'])) for p in plist)
        pages = (data.get('paginator') or {}).get('pages')
        if oldest < start_ts or (pages and page >= pages):
            break
    return out


def _request(url, headers, body=None, raw=False, retries=3):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=dict(headers), method='POST' if data else 'GET')
            with urllib.request.urlopen(req, timeout=120) as resp:
                b = resp.read()
                return b if raw else json.loads(b.decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt < retries - 1 and _refresh(headers):
                continue
            if e.code == 401:
                raise SystemExit('[fetch_bops] 401 Unauthorized — BOPS_TOKEN が失効しています。')
            last_err = f'HTTP {e.code}'
        except Exception as e:
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f'{url}: {last_err}')


def _cached(key, fn):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest())
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read()
    data = fn()
    with open(path, 'wb') as f:
        f.write(data)
    return data


def _count_slides(pptx_bytes):
    with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as z:
        return sum(1 for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n))


def _turn_for(msgs, t_utc):
    """成果物の更新時刻を含む（なければ直前に終わった）会話ターンの (秒, ステップ数, 開始, 終了) を返す。"""
    best = None
    for m in msgs:
        try:
            arr = json.loads(m['answer']) if isinstance(m.get('answer'), str) else (m.get('answer') or [])
        except Exception:
            continue
        ts = [a.get('ts') for a in arr if isinstance(a, dict) and a.get('ts')]
        if not ts:
            continue
        lo, hi = min(ts) / 1000, max(ts) / 1000
        if lo - 60 <= t_utc <= hi + 300:
            return round(hi - lo), len(arr), lo, hi
        if hi <= t_utc and (best is None or hi > best[3]):
            best = (round(hi - lo), len(arr), lo, hi)
    return best or (0, 2, t_utc, t_utc)


def fetch_chat_ppts(headers, start_ts, end_ts):
    """会話内で生成された PPTX（outputs/ 配下の各版）を 17 列の行で返す。"""
    lookback = start_ts - CHAT_LOOKBACK_DAYS * 86400
    chats, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        data = _post(CHAT_LIST_API, {'currentPage': page, 'pageSize': PAGE_SIZE_CAP}, headers)
        lst = max((v for v in data.values() if isinstance(v, list)), key=len, default=[])
        if not lst:
            break
        for c in lst:
            if c['id'] not in seen and _ts(_to_jst(c.get('createdAt'))) <= end_ts \
                    and _ts(_to_jst(c.get('updatedAt') or c.get('createdAt'))) >= start_ts:
                seen.add(c['id'])
                chats.append(c)
        if min(_ts(_to_jst(c['createdAt'])) for c in lst) < lookback:
            break
    rows = []
    for c in chats:
        def _search(cid=c['id']):
            out, page = [], 1
            while True:
                d = _post(CHAT_FILES_API, {'chatId': cid, 'currentPage': page, 'pageSize': 200}, headers)
                out += d.get('fileList') or []
                if page >= ((d.get('paginator') or {}).get('pages') or 1):
                    return json.dumps(out).encode('utf-8')
                page += 1
        # 1 回の run_site で fetch を 7 回呼ぶため、会話の更新時刻をキーにファイル一覧もキャッシュする
        files = json.loads(_cached('files:' + c['id'] + ':' + (c.get('updatedAt') or ''), _search).decode('utf-8'))
        ppts = [f for f in files if (f.get('fileName') or '').lower().endswith('.pptx')
                and (f.get('filePath') or '').startswith('outputs')
                and start_ts <= _ts(_to_jst(f.get('updatedAt'))) <= end_ts]
        uniq = {}
        for f in ppts:  # cacheFile/search は同じファイルを重複して返すことがある
            uniq.setdefault((f.get('filePath'), f.get('fileName')), f)
        ppts = list(uniq.values())
        if not ppts:
            continue
        msgs = json.loads(_cached('msg:' + c['id'] + ':' + (c.get('updatedAt') or ''),
                                  lambda: _request(CHAT_MSG_API + c['id'], headers, raw=True)).decode('utf-8'))
        msgs = msgs.get('chatMessageList') or msgs.get('messages') or next(
            (v for v in msgs.values() if isinstance(v, list) and v and isinstance(v[0], dict)), []) if isinstance(msgs, dict) else msgs
        for f in ppts:
            key = f"{c['id']}|{f['filePath']}|{f['fileName']}"
            try:
                blob = _cached('ppt:' + key + f"|{f.get('fileSize')}", lambda: _request(
                    CHAT_DOWNLOAD_API, headers, {'chatId': c['id'], 'fileName': f['fileName'], 'filePath': f['filePath']}, raw=True))
                slides = _count_slides(blob)
            except Exception as e:
                print(f'  [warn] chat={c["id"]} {f["fileName"]} のページ数取得に失敗: {e}', file=sys.stderr)
                slides = 0
            t_utc = calendar.timegm(datetime.strptime(f['updatedAt'][:19], '%Y-%m-%d %H:%M:%S').timetuple())
            dur, steps, lo, hi = _turn_for(msgs, t_utc)
            fmt = lambda x: time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(x))
            topic = f"{(c.get('title') or '').strip()}｜{f['fileName']}"
            rows.append([
                int(hashlib.sha1(key.encode()).hexdigest()[:12], 16), topic, c.get('ownerName', ''),
                c.get('companyName', ''), '-', CHAT_STRATEGY, 'success', slides, slides,
                _to_jst(f['updatedAt']), _to_jst(fmt(lo)), _to_jst(fmt(hi)), dur, steps, dur, 0, 0,
            ])
    return rows


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
    ap.add_argument('--page-size', type=int, default=300,
                    help='(deprecated) 全ページ走査に移行したため未使用')
    args = ap.parse_args()

    token = os.environ.get('BOPS_TOKEN')
    if not token:
        raise SystemExit('[fetch_bops] 環境変数 BOPS_TOKEN が未設定です')
    token_type = (os.environ.get('BOPS_TOKEN_TYPE') or 'Bearer')  # 空文字は Bearer 扱い（CI で secret 未定義→'' になり 401 になった実害あり）
    headers = {'Content-Type': 'application/json',
               'Authorization': f'{token_type} {token}'}

    start_date, end_date = resolve_range(args)
    start_ts = _ts(start_date + ' 00:00:00')
    end_ts = _ts(end_date + ' 23:59:59')

    filtered = fetch_ppt_list(headers, start_ts, end_ts)
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
                _to_jst(p.get('createdAt', '')), _to_jst(dur['startTime'] or p.get('createdAt', '')),
                _to_jst(dur['endTime'] or p.get('createdAt', '')), dur['durationSec'], len(logs),
                dur['originalDurationSec'], dur['breakCount'], dur['maxGapSec'],
            ])
        except SystemExit:
            raise
        except Exception as e:
            print(f'  [warn] id={p.get("id")} の詳細取得に失敗: {e}', file=sys.stderr)

    if os.environ.get('BOPS_SKIP_CHAT_PPT') != '1':
        try:
            chat_rows = fetch_chat_ppts(headers, start_ts, end_ts)
            rows.extend(chat_rows)
            print(f'[fetch_bops] 会話内生成（新Skill）: {len(chat_rows)} 件')
        except SystemExit:
            raise
        except Exception as e:
            print(f'  [warn] 会話内生成 PPT の取得に失敗（PPT 一覧分のみ出力）: {e}', file=sys.stderr)

    # topic 等にユーザー入力の改行/タブが混入すると TSV の行が壊れるため空白に置換
    def _clean(c):
        return str(c).replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join('\t'.join(_clean(c) for c in r) for r in rows))
    print(f'[fetch_bops] 書き出し: {args.out}（{len(rows) - 1} 件）')
    # 期間メタを stdout 最終行に（呼び出し側が拾えるよう）
    print(f'RANGE\t{start_date}\t{end_date}')


if __name__ == '__main__':
    main()
