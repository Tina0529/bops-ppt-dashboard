#!/usr/bin/env python3
"""git 履歴から月次アーカイブ (docs/data/archive/YYYY-MM.json) を再構築する。

dashboard.json / detail.json は毎日上書きされるため、過去月の月次データは
git 履歴にしか残っていない。各月について、その月を基準日とした最後の
コミット（≒月末実行分）から monthly セクションを抽出して凍結する。

使い方: リポジトリルートで  python3 scripts/archive_backfill.py
（当月分もアーカイブされるが、以後の日次 CI が毎回上書きする）
"""
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True)


def main():
    commits = sh('git', 'log', '--format=%H', '--', 'docs/data/dashboard.json').split()
    months = {}
    for c in commits:  # 新しい順 → 各月で最初に見つかったコミットがその月の最終版
        try:
            dash = json.loads(sh('git', 'show', f'{c}:docs/data/dashboard.json'))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        month = (dash.get('date') or '')[:7]
        if not month or month in months or not dash.get('monthly'):
            continue
        try:
            det = json.loads(sh('git', 'show', f'{c}:docs/data/detail.json')).get('monthly', [])
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            det = []
        months[month] = {'month': month, 'date': dash['date'],
                         'dashboard': dash['monthly'], 'detail': det}
        print(f'[backfill] {month} ← {c[:7]} (基準日 {dash["date"]}, 明細 {len(det)} 件)')

    arch = os.path.join(ROOT, 'docs', 'data', 'archive')
    os.makedirs(arch, exist_ok=True)
    for month, payload in months.items():
        with open(os.path.join(arch, f'{month}.json'), 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    idx = sorted(fn[:-5] for fn in os.listdir(arch) if fn.endswith('.json') and fn != 'index.json')
    with open(os.path.join(arch, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump({'months': idx}, f)
    print(f'[backfill] archive/index.json → {idx}')


if __name__ == '__main__':
    main()
