#!/usr/bin/env python3
"""組織（会社）単位・月次集計の共通ロジック。

trend_org_monthly.csv は long 形式（1行 = 1ヶ月 × 1社）:
    month,company,total,generated,completion,avg_per_slide

集計口径は generate_xlsx.aggregate と完全に一致させること:
    generated     = classify() が 1 を返すレコード（status=failed / logs<=1 は未生成）
    completion    = generated / total
    avg_per_slide = 生成成功分の総 durationSec / 総 actualSlides
"""
import csv
import os

FIELDS = ['month', 'company', 'total', 'generated', 'completion', 'avg_per_slide']
UNKNOWN = '(未設定)'


def norm_company(name) -> str:
    """会社名の正規化。空/None は (未設定) に寄せる。"""
    return (name or '').strip() or UNKNOWN


def agg_by_company(rows):
    """[{company, generated(bool), durationSec, actualSlides}] → {company: metrics}。"""
    acc = {}
    for r in rows:
        c = norm_company(r['company'])
        a = acc.setdefault(c, {'total': 0, 'generated': 0, 'dur': 0, 'slides': 0})
        a['total'] += 1
        if r['generated']:
            a['generated'] += 1
            a['dur'] += r['durationSec']
            a['slides'] += r['actualSlides']
    out = {}
    for c, a in acc.items():
        out[c] = {
            'total': a['total'],
            'generated': a['generated'],
            'completion': round(a['generated'] / a['total'], 4) if a['total'] else 0,
            'avg_per_slide': round(a['dur'] / a['slides'], 1) if a['slides'] else 0,
        }
    return out


def upsert(csv_path, month, per_company):
    """指定 month の行を全削除してから書き直す（月内の会社増減に追従するため）。"""
    rows = []
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8') as f:
            rows = [r for r in csv.DictReader(f) if r.get('month') != month]
    for c, m in sorted(per_company.items(), key=lambda kv: (-kv[1]['total'], kv[0])):
        rows.append({'month': month, 'company': c, **m})
    rows.sort(key=lambda r: (r['month'], -int(r['total']), r['company']))
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)) or '.', exist_ok=True)
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


def load(csv_path):
    """CSV → {'months':[...], 'companies':[{name,total,data,gen,comp}], 'totals':[...]}。"""
    if not csv_path or not os.path.exists(csv_path):
        return None
    with open(csv_path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    months = sorted({r['month'] for r in rows})
    idx = {m: i for i, m in enumerate(months)}
    n = len(months)
    comp = {}
    for r in rows:
        c = r['company']
        e = comp.setdefault(c, {'name': c, 'total': 0,
                                'data': [0] * n, 'gen': [0] * n, 'comp': [None] * n})
        i = idx[r['month']]
        e['data'][i] = int(r['total'])
        e['gen'][i] = int(r['generated'])
        e['comp'][i] = round(float(r['completion']) * 100, 1)
        e['total'] += int(r['total'])
    companies = sorted(comp.values(), key=lambda e: (-e['total'], e['name']))
    totals = [sum(e['data'][i] for e in companies) for i in range(n)]
    return {'months': months, 'companies': companies, 'totals': totals}
