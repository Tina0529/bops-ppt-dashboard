#!/usr/bin/env python3
"""TSV → GitHub Pages 用 JSON（dashboard.json + detail.json）を生成。

index.html / detail.html はこの JSON を fetch して描画する静的ページ。
dashboard データは preview_html.build_period を再利用、明細は Excel 列に準拠。

依存（sparticle-toolkit の bops-ppt-monitor からコピー）:
  generate_xlsx.py / preview_html.py / fetch_bops.py / auth.py /
  update_trend.py / backfill_trend.py / make_summary.py / lark_card.py

使い方:
  python3 generate_site.py --date 2026-06-14 --out-dir docs/data \
    --daily d.tsv \
    --weekly w.tsv [--weekly-prev wp.tsv] [--weekly-trend tw.csv] \
    --monthly m.tsv [--monthly-prev mp.tsv] [--monthly-trend tm.csv]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_xlsx import parse_tsv, classify, fmt_mmss  # noqa: E402
from preview_html import build_period  # noqa: E402


def detail_records(tsv):
    """Excel 明細に準拠したレコード配列を返す。"""
    if not tsv or not os.path.exists(tsv):
        return []
    recs, _ = parse_tsv(tsv)
    out = []
    for r in recs:
        mult, reason = classify(r['status'], r['logsCount'])
        stat = r['actualSlides'] * mult
        if r['breakCount'] > 0:
            extra = (f"中断{r['breakCount']}回（元{r['originalDurationSec']}s→純{r['durationSec']}s、"
                     f"最長{fmt_mmss(r['maxGapSec'])}）")
            reason = (reason + ' / ' + extra) if reason else extra
        out.append({
            'id': r['id'], 'topic': r['topic'], 'username': r['username'], 'company': r['company'],
            'strategy': r['strategy'], 'status': r['status'] or '—',
            'slideCount': r['slideCount'], 'actualSlides': r['actualSlides'], 'statSlides': stat,
            'createdAt': r['createdAt'], 'startTime': r['startTime'], 'endTime': r['endTime'],
            'durationSec': r['durationSec'], 'mmss': fmt_mmss(r['durationSec']),
            'logsCount': r['logsCount'],
            'avgPerSlide': round(r['durationSec'] / r['actualSlides'], 1) if r['actualSlides'] > 0 else 0,
            'reason': reason, 'breakCount': r['breakCount'], 'maxGapSec': r['maxGapSec'],
            'excluded': stat == 0,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True)
    ap.add_argument('--out-dir', required=True)
    for k in ('daily', 'weekly', 'monthly'):
        ap.add_argument(f'--{k}')
        ap.add_argument(f'--{k}-prev')
        ap.add_argument(f'--{k}-trend')
        ap.add_argument(f'--{k}-label', default='')
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    defaults = {'daily': '当日', 'weekly': '当週', 'monthly': '当月'}
    dashboard = {'date': args.date}
    detail = {'date': args.date}
    for k in ('daily', 'weekly', 'monthly'):
        tsv = getattr(args, k)
        if not tsv or not os.path.exists(tsv):
            dashboard[k] = None
            detail[k] = []
            continue
        label = getattr(args, f'{k}_label') or defaults[k]
        dashboard[k] = build_period(k, label, tsv, getattr(args, f'{k}_prev'), getattr(args, f'{k}_trend'))
        detail[k] = detail_records(tsv)

    with open(os.path.join(args.out_dir, 'dashboard.json'), 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(args.out_dir, 'detail.json'), 'w', encoding='utf-8') as f:
        json.dump(detail, f, ensure_ascii=False, separators=(',', ':'))
    print(f'[generate_site] dashboard.json + detail.json → {args.out_dir} '
          f'(daily {len(detail["daily"])} / weekly {len(detail["weekly"])} / monthly {len(detail["monthly"])})')


if __name__ == '__main__':
    main()
