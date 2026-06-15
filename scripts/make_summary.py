#!/usr/bin/env python3
"""日次/週次/前期 TSV から Lark 用 summary.json を作る。

使い方:
  python3 make_summary.py <daily.tsv> <weekly.tsv> <prev.tsv|-> <date> <out.json>
  prev が無い場合は '-' を渡す（前期比なし）。
"""
import json
import os
import sys

# 同ディレクトリの generate_xlsx を import（parse_tsv / aggregate を再利用）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_xlsx import parse_tsv, aggregate  # noqa: E402


def agg(path):
    recs, _ = parse_tsv(path)
    a = aggregate(recs)
    breaks = sum(1 for r in recs if r['breakCount'] > 0)
    return a, breaks


def main():
    daily_tsv, weekly_tsv, prev_tsv, date, out = sys.argv[1:6]
    s = {'date': date}

    da, db = agg(daily_tsv)
    s['daily'] = {'total': da['total'], 'generated': da['generated'],
                  'completion': da['completion'], 'avg_per_slide': round(da['avg_per_slide']),
                  'breaks': db}

    wa, wbreaks = agg(weekly_tsv)
    w = {'total': wa['total'], 'generated': wa['generated'], 'completion': wa['completion'],
         'avg_per_slide': round(wa['avg_per_slide']), 'breaks': wbreaks}

    if prev_tsv and prev_tsv != '-' and os.path.exists(prev_tsv) and os.path.getsize(prev_tsv) > 0:
        pa, _ = agg(prev_tsv)
        w['prev_total'] = pa['total']
        w['prev_completion'] = pa['completion']
        cur_c, prev_c = wa['companies'], pa['companies']
        deltas = [(c, cur_c.get(c, 0) - prev_c.get(c, 0)) for c in set(cur_c) | set(prev_c)]
        rising = sorted([x for x in deltas if x[1] > 0], key=lambda x: -x[1])[:3]
        falling = sorted([x for x in deltas if x[1] < 0], key=lambda x: x[1])[:3]
        w['rising'] = [f'{c}(+{d})' for c, d in rising]
        w['falling'] = [f'{c}({d})' for c, d in falling]
    s['weekly'] = w

    with open(out, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    print('[make_summary]', json.dumps(s, ensure_ascii=False))


if __name__ == '__main__':
    main()
