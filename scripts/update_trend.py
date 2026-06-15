#!/usr/bin/env python3
"""当期の KPI を trend CSV に追記（同一 label は上書き）。推移トレンド折線図の元データ。

run_monitor.sh が日次/週次/月次の集計後に呼び、各粒度の履歴を貯める。
折線図はこの CSV を読んで「件数 / 完成率 / 平均秒per頁」の推移を描く。

使い方:
  python3 update_trend.py <tsv> <label> <trend_csv>
    <label> 例: "06-12週" / "2026-06"。同じ label があれば上書き。

CSV 列: label,total,generated,completion,avg_per_slide
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_xlsx import parse_tsv, aggregate  # noqa: E402

FIELDS = ['label', 'total', 'generated', 'completion', 'avg_per_slide']
MAX_POINTS = 26  # 直近 26 点（半年ぶんの週 or 2年ぶんの月）まで保持


def main():
    tsv, label, csv_path = sys.argv[1:4]
    recs, _ = parse_tsv(tsv)
    a = aggregate(recs)
    row = {'label': label, 'total': a['total'], 'generated': a['generated'],
           'completion': round(a['completion'], 4), 'avg_per_slide': round(a['avg_per_slide'], 1)}

    rows = []
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8') as f:
            rows = [r for r in csv.DictReader(f) if r.get('label') != label]
    rows.append(row)
    rows = rows[-MAX_POINTS:]

    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f'[update_trend] {csv_path} ← {label}: {row["total"]}件 / 完成率 {row["completion"]*100:.1f}% '
          f'/ {row["avg_per_slide"]:.0f}秒（計 {len(rows)} 点）')


if __name__ == '__main__':
    main()
