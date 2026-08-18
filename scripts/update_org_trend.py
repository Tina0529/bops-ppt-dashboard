#!/usr/bin/env python3
"""当月の TSV を会社別に集計して trend_org_monthly.csv へ upsert。

run_site.sh が月次 TSV 取得後に呼ぶ。同一 month の行は毎回全置換するため、
月の途中で新しい会社が現れても自動的に追従する。

使い方:
  python3 update_org_trend.py <monthly_tsv> <month_label> <trend_org_monthly.csv>
    <month_label> 例: 2026-08
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_xlsx import parse_tsv, classify  # noqa: E402
from org_trend import agg_by_company, upsert  # noqa: E402


def main():
    tsv, month, csv_path = sys.argv[1:4]
    recs, _ = parse_tsv(tsv)
    rows = [{
        'company': r['company'],
        'generated': classify(r['status'], r['logsCount'])[0] == 1,
        'durationSec': r['durationSec'],
        'actualSlides': r['actualSlides'],
    } for r in recs]
    per = agg_by_company(rows)
    upsert(csv_path, month, per)
    top = sorted(per.items(), key=lambda kv: -kv[1]['total'])[:3]
    brief = ' / '.join(f'{c} {m["total"]}本' for c, m in top)
    print(f'[update_org_trend] {csv_path} ← {month}: {len(per)}社 / {sum(m["total"] for m in per.values())}本  {brief}')


if __name__ == '__main__':
    main()
