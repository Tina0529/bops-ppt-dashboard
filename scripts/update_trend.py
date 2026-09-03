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
import re
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
            rows = list(csv.DictReader(f))

    # 既存 label は「その場で」差し替える。削除して末尾に付け直すと並び順が壊れる。
    # 実害例（2026-09-01 発見）: 9/1 に 2026-09 を追記したあと 8 月を補跑した結果、
    # trend_monthly.csv が …07, 09, 08 の順になり折線グラフの X 軸が逆転した。
    for i, r in enumerate(rows):
        if r.get('label') == label:
            rows[i] = row
            break
    else:
        rows.append(row)

    # 月次（YYYY-MM）は年が入っていて曖昧さがないので、念のため昇順に整える。
    # 日次/週次の label（MM-DD / MM-DD週）は年を持たず年跨ぎで誤るため並べ替えない
    # ——上の原位置更新で順序が保たれる。
    if all(re.fullmatch(r'\d{4}-\d{2}', r['label'] or '') for r in rows):
        rows.sort(key=lambda r: r['label'])

    rows = rows[-MAX_POINTS:]

    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f'[update_trend] {csv_path} ← {label}: {row["total"]}件 / 完成率 {row["completion"]*100:.1f}% '
          f'/ {row["avg_per_slide"]:.0f}秒（計 {len(rows)} 点）')


if __name__ == '__main__':
    main()
