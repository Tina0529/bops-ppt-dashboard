#!/usr/bin/env python3
"""docs/data/archive/*.json から組織別月次トレンドを再構築する。

archive の detail は generate_site.detail_records が出力済みの正規化レコードで、
excluded フラグが「統計上の未生成」を表す（= classify()==0 と同義）。
BOPS へ接続せずオフラインで trend_org_monthly.csv を作り直せる。

使い方:
  python3 backfill_org_trend.py [archive_dir] [out_csv]
    既定: ../docs/data/archive  →  ../docs/data/trend_org_monthly.csv
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from org_trend import agg_by_company, upsert  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_ARCH = os.path.join(HERE, '..', 'docs', 'data', 'archive')
DEF_OUT = os.path.join(HERE, '..', 'docs', 'data', 'trend_org_monthly.csv')


def main():
    arch = sys.argv[1] if len(sys.argv) > 1 else DEF_ARCH
    out = sys.argv[2] if len(sys.argv) > 2 else DEF_OUT
    files = sorted(f for f in glob.glob(os.path.join(arch, '*.json'))
                   if os.path.basename(f) != 'index.json')
    if not files:
        print(f'[backfill_org_trend] アーカイブなし: {arch}')
        return
    if os.path.exists(out):
        os.remove(out)
    for fn in files:
        with open(fn, encoding='utf-8') as f:
            a = json.load(f)
        month = a.get('month') or os.path.basename(fn)[:-5]
        rows = [{
            'company': r.get('company'),
            'generated': not r.get('excluded'),
            'durationSec': r.get('durationSec', 0),
            'actualSlides': r.get('actualSlides', 0),
        } for r in a.get('detail', [])]
        per = agg_by_company(rows)
        upsert(out, month, per)
        print(f'[backfill_org_trend] {month}: {len(per)}社 / {sum(r["total"] for r in per.values())}本')
    print(f'[backfill_org_trend] → {out}')


if __name__ == '__main__':
    main()
