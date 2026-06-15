#!/usr/bin/env python3
"""日次/週次/月次 TSV から、期間フィルタ + 明暗テーマ + 推移トレンド付き Dashboard HTML を生成。

- 「当日 / 本週 / 本月」をボタンで切替（クライアント側）
- 右上の ☀/🌙 でライト/ダークテーマ切替（localStorage 記憶）
- 週次/月次は「推移トレンド」折線図（件数 / 完成率 / 平均秒per頁）で増減を可視化
  → trend CSV（update_trend.py が貯める）を読む。無ければトレンド欄は出ない。

使い方:
  python3 preview_html.py <out.html> \
      --daily   <tsv> --daily-label "..." \
      --weekly  <tsv> [--weekly-prev <tsv>]  [--weekly-trend <csv>]  --weekly-label "..." \
      --monthly <tsv> [--monthly-prev <tsv>] [--monthly-trend <csv>] --monthly-label "..."
"""
import argparse
import csv as csvmod
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_xlsx import parse_tsv, aggregate, classify, fmt_minsec  # noqa: E402


def delta_html(cur, prev, unit='', pt=False):
    if prev is None:
        return ''
    d = cur - prev
    if pt:
        d *= 100
        s = f'{abs(d):.1f}pt'
    else:
        s = f'{abs(d):g}{unit}'
    if d > 0.0001:
        return f'<span class="up">▲ +{s}</span>'
    if d < -0.0001:
        return f'<span class="down">▼ -{s}</span>'
    return '<span class="flat">± 0</span>'


def sig_label(cur, prev, diff):
    if diff > 0:
        return ('利用拡大', 'up')
    if diff < 0:
        return ('利用縮小（要フォロー）' if prev >= 3 else '微減', 'down')
    return ('横ばい', 'flat')


def load_trend(path):
    if not path or not os.path.exists(path):
        return None
    labels, total, completion, avgslide = [], [], [], []
    with open(path, encoding='utf-8') as f:
        for r in csvmod.DictReader(f):
            labels.append(r['label'])
            total.append(int(float(r['total'])))
            completion.append(round(float(r['completion']) * 100, 1))
            avgslide.append(round(float(r['avg_per_slide'])))
    if not labels:
        return None
    return {'labels': labels, 'total': total, 'completion': completion, 'avgslide': avgslide}


def build_period(key, label, tsv, prev_tsv, trend_csv):
    recs, _ = parse_tsv(tsv)
    a = aggregate(recs)
    gen = [r for r in recs if classify(r['status'], r['logsCount'])[0] == 1]
    breaks = sum(1 for r in recs if r['breakCount'] > 0)
    pa = None
    if prev_tsv:
        precs, _ = parse_tsv(prev_tsv)
        pa = aggregate(precs)

    kpis = [
        {'label': '総生成件数', 'value': f"{a['total']}", 'unit': '本',
         'delta': delta_html(a['total'], pa['total'] if pa else None)},
        {'label': '完成率', 'value': f"{a['completion']*100:.1f}", 'unit': '%',
         'delta': delta_html(a['completion'], pa['completion'] if pa else None, pt=True)
                  + f" <small>生成 {a['generated']}/{a['total']}</small>"},
        {'label': '1件あたり平均純所要', 'value': fmt_minsec(a['avg_duration']), 'unit': '',
         'delta': delta_html(a['avg_duration'], pa['avg_duration'] if pa else None, unit='s')},
        {'label': '1ページあたり平均', 'value': f"{a['avg_per_slide']:.0f}", 'unit': '秒',
         'delta': delta_html(round(a['avg_per_slide']), round(pa['avg_per_slide']) if pa else None, unit='s')
                  + f" <small>{a['total_slides']}頁</small>"},
    ]

    cur_c = a['companies']
    prev_c = pa['companies'] if pa else Counter()
    comps = sorted(set(cur_c) | set(prev_c), key=lambda c: -cur_c.get(c, 0))[:12]
    comp_rows = [(c, cur_c.get(c, 0), prev_c.get(c, 0), cur_c.get(c, 0) - prev_c.get(c, 0)) for c in comps]
    signals = []
    for c, cur, prev, diff in sorted(comp_rows, key=lambda x: -abs(x[3]))[:8]:
        lab, cls = sig_label(cur, prev, diff)
        signals.append({'comp': c, 'cur': cur, 'prev': prev, 'diff': diff, 'lab': lab, 'cls': cls})

    date_counts = Counter(r['createdAt'][:10] for r in recs if r['createdAt'])
    dates = sorted(date_counts)
    bins = [(0, 60, '〜1分'), (60, 300, '1〜5分'), (300, 600, '5〜10分'),
            (600, 1200, '10〜20分'), (1200, 1800, '20〜30分'),
            (1800, 3600, '30〜60分'), (3600, 10**9, '60分〜')]
    bin_counts = [(lab, sum(1 for r in gen if lo <= r['durationSec'] < hi)) for lo, hi, lab in bins]

    return {
        'key': key, 'label': label, 'has_prev': bool(pa),
        'pp': (f'前期比あり（前期 {pa["total"]} 件 / 完成率 {pa["completion"]*100:.1f}%）' if pa
               else '前期比なし'),
        'kpis': kpis, 'signals': signals,
        'excluded': a['excluded'], 'breaks': breaks, 'gen_n': len(gen),
        'trend': load_trend(trend_csv),
        'charts': {
            'daily': {'labels': dates, 'data': [date_counts[d] for d in dates]},
            'bins': {'labels': [b[0] for b in bin_counts], 'data': [b[1] for b in bin_counts]},
            'comp': {'labels': [c for c, _, _, _ in comp_rows],
                     'cur': [cur for _, cur, _, _ in comp_rows],
                     'prev': [prev for _, _, prev, _ in comp_rows]},
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out_html')
    for k in ('daily', 'weekly', 'monthly'):
        ap.add_argument(f'--{k}')
        ap.add_argument(f'--{k}-prev')
        ap.add_argument(f'--{k}-trend')
        ap.add_argument(f'--{k}-label', default='')
    args = ap.parse_args()

    defaults = {'daily': '当日', 'weekly': '本週', 'monthly': '本月'}
    periods = []
    for k in ('daily', 'weekly', 'monthly'):
        tsv = getattr(args, k)
        if not tsv:
            continue
        label = getattr(args, f'{k}_label') or defaults[k]
        periods.append(build_period(k, label, tsv, getattr(args, f'{k}_prev'), getattr(args, f'{k}_trend')))
    if not periods:
        sys.exit('少なくとも 1 期間（--daily/--weekly/--monthly）が必要です')

    tabs = {'daily': '当日', 'weekly': '本週', 'monthly': '本月'}
    btns = ''.join(
        f'<button class="seg-btn{" active" if i == 0 else ""}" data-key="{p["key"]}">{tabs[p["key"]]}</button>'
        for i, p in enumerate(periods))

    html = (HTML_TMPL.replace('__BTNS__', btns)
            .replace('__DATA__', json.dumps({p['key']: p for p in periods}, ensure_ascii=False))
            .replace('__FIRST__', json.dumps(periods[0]['key'])))
    with open(args.out_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Saved: {args.out_html}  ({len(periods)} 期間: {", ".join(tabs[p["key"]] for p in periods)})')


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="ja" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BOPS PPT Monitor</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Sans+JP:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root, html[data-theme="dark"] {
    --primary:#0C5CAB; --primary-2:#2f81d6; --secondary:#0a4a8a;
    --success:#10b981; --warning:#f59e0b; --danger:#ef4444;
    --surface:#09090b; --panel:#101014; --panel-2:#16161c;
    --border:rgba(255,255,255,.08); --text:#fafafa; --muted:#a1a1aa; --muted-2:#71717a;
    --shadow:0 1px 0 rgba(255,255,255,.04) inset, 0 8px 24px rgba(0,0,0,.45);
    --glow1:rgba(12,92,171,.18); --glow2:rgba(47,129,214,.10);
    --grid:rgba(255,255,255,.06); --axis:#a1a1aa; --trendmuted:#3f3f46;
  }
  html[data-theme="light"] {
    --primary:#0C5CAB; --primary-2:#2f81d6; --secondary:#0a4a8a;
    --success:#0a9d6e; --warning:#b9770a; --danger:#d23b35;
    --surface:#eef2f7; --panel:#ffffff; --panel-2:#f3f6fb;
    --border:rgba(20,40,80,.12); --text:#1c2430; --muted:#5b6675; --muted-2:#8a94a6;
    --shadow:0 1px 2px rgba(20,40,80,.06), 0 8px 24px rgba(20,40,80,.08);
    --glow1:rgba(12,92,171,.10); --glow2:rgba(47,129,214,.06);
    --grid:rgba(20,40,80,.08); --axis:#5b6675; --trendmuted:#c3cddd;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:
           radial-gradient(1200px 600px at 80% -10%, var(--glow1), transparent 60%),
           radial-gradient(900px 500px at -10% 10%, var(--glow2), transparent 55%),
           var(--surface);
         color:var(--text); font-family:"IBM Plex Sans JP","IBM Plex Sans",system-ui,sans-serif;
         -webkit-font-smoothing:antialiased; transition:background .25s, color .25s; }
  .wrap { max-width:1180px; margin:0 auto; padding:28px 24px 40px; }
  .head { display:flex; align-items:center; gap:14px; margin-bottom:20px; }
  .logo { width:38px; height:38px; border-radius:10px; flex:0 0 auto;
          background:linear-gradient(135deg,var(--primary),var(--primary-2));
          display:grid; place-items:center; font-weight:700; color:#fff; font-size:18px;
          box-shadow:0 6px 18px rgba(12,92,171,.45); }
  .head h1 { margin:0; font-size:20px; font-weight:600; letter-spacing:.2px; }
  .head .sub { font-size:12px; color:var(--muted); margin-top:2px; }
  .head .right { margin-left:auto; display:flex; align-items:center; gap:10px; }
  .chip { font-size:11px; color:var(--muted); border:1px solid var(--border);
          background:var(--panel); padding:5px 12px; border-radius:999px; }
  .theme-btn { display:inline-grid; place-items:center; width:36px; height:36px; cursor:pointer;
               border:1px solid var(--border); background:var(--panel); border-radius:9px;
               color:var(--text); font-size:16px; transition:.18s; }
  .theme-btn:hover { border-color:var(--primary-2); }
  .theme-btn:focus-visible { outline:2px solid var(--primary-2); outline-offset:2px; }

  .toolbar { display:flex; align-items:center; gap:14px; flex-wrap:wrap;
             background:var(--panel); border:1px solid var(--border); border-radius:14px;
             padding:14px 16px; box-shadow:var(--shadow); margin-bottom:18px; }
  .toolbar .lbl { font-size:12px; color:var(--muted); font-weight:500; text-transform:uppercase; letter-spacing:.08em; }
  .seg { display:inline-flex; background:var(--panel-2); border:1px solid var(--border);
         border-radius:10px; padding:4px; gap:4px; }
  .seg-btn { border:0; background:transparent; color:var(--muted); font-weight:600; font-size:13px;
             font-family:inherit; padding:7px 18px; border-radius:7px; cursor:pointer; transition:.18s; }
  .seg-btn:hover { color:var(--text); }
  .seg-btn:focus-visible { outline:2px solid var(--primary-2); outline-offset:2px; }
  .seg-btn.active { background:linear-gradient(180deg,var(--primary),var(--secondary));
                    color:#fff; box-shadow:0 4px 12px rgba(12,92,171,.5); }
  .period-info { margin-left:auto; font-size:12.5px; color:var(--muted); }
  .period-info b { color:var(--text); font-weight:600; }

  .kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:18px; }
  .kpi { position:relative; background:linear-gradient(180deg,var(--panel),var(--panel-2));
         border:1px solid var(--border); border-radius:14px; padding:16px 16px 14px;
         box-shadow:var(--shadow); overflow:hidden; }
  .kpi::before { content:""; position:absolute; left:0; top:0; height:3px; width:100%;
                 background:linear-gradient(90deg,var(--primary),var(--primary-2)); opacity:.9; }
  .kpi-label { color:var(--muted); font-weight:500; font-size:12px; letter-spacing:.02em; }
  .kpi-value { font-size:30px; font-weight:700; margin:8px 0 6px; line-height:1; letter-spacing:-.5px; }
  .kpi-unit { font-size:13px; color:var(--muted); margin-left:4px; font-weight:500; }
  .kpi-delta { font-size:12px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .kpi-delta small { color:var(--muted-2); }
  .up { color:var(--success); font-weight:600; }
  .down { color:var(--danger); font-weight:600; }
  .flat { color:var(--muted); font-weight:600; }

  .panel { background:var(--panel); border:1px solid var(--border); border-radius:14px;
           padding:18px 18px 20px; box-shadow:var(--shadow); margin-bottom:18px; }
  .panel.hidden { display:none; }
  .panel h2 { font-size:14px; font-weight:600; margin:0 0 4px; display:flex; align-items:center; gap:8px; }
  .panel h2::before { content:""; width:8px; height:8px; border-radius:2px;
                      background:linear-gradient(135deg,var(--primary),var(--primary-2)); }
  .legend-tip { font-size:12px; color:var(--muted); margin:0 0 14px; }

  .trend3 { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  thead th { background:var(--panel-2); color:var(--muted); font-weight:600; text-align:left;
             padding:9px 12px; border-bottom:1px solid var(--border); font-size:11.5px;
             text-transform:uppercase; letter-spacing:.05em; }
  tbody td { padding:9px 12px; border-bottom:1px solid var(--border); color:var(--text); }
  tbody tr:hover { background:var(--panel-2); }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .pill { display:inline-flex; align-items:center; gap:5px; padding:2px 9px; border-radius:999px;
          font-size:11.5px; font-weight:600; }
  .pill.up { background:rgba(16,185,129,.14); color:var(--success); }
  .pill.down { background:rgba(239,68,68,.14); color:var(--danger); }
  .pill.flat { background:rgba(127,127,127,.14); color:var(--muted); }

  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  .card { background:var(--panel-2); border:1px solid var(--border); border-radius:12px; padding:14px; }
  .card.full { margin-top:16px; }
  .note { color:var(--muted-2); font-size:11.5px; margin-top:14px; line-height:1.6; }
  @media(max-width:760px){ .kpis,.grid2,.trend3{grid-template-columns:1fr;} .period-info{margin-left:0;width:100%;} }
</style></head>
<body><div class="wrap">
  <div class="head">
    <div class="logo">P</div>
    <div>
      <h1>BOPS PPT Monitor</h1>
      <div class="sub">生成品質モニタリング & 利用意欲インサイト</div>
    </div>
    <div class="right">
      <span class="chip">プレビュー / 匿名サンプル</span>
      <button class="theme-btn" id="themeBtn" title="ライト/ダーク切替" aria-label="テーマ切替">🌙</button>
    </div>
  </div>

  <div class="toolbar">
    <span class="lbl">統計期間</span>
    <div class="seg" role="tablist" aria-label="統計期間">__BTNS__</div>
    <span class="period-info" id="periodInfo"></span>
  </div>

  <div class="kpis" id="kpis"></div>

  <div class="panel hidden" id="trendPanel">
    <h2>推移トレンド（期間ごとの増減）</h2>
    <div class="legend-tip">直近の各期間の指標推移。線の上り下りで増減が一目で分かります。</div>
    <div class="trend3">
      <div class="card"><canvas id="t_total" height="150"></canvas></div>
      <div class="card"><canvas id="t_comp" height="150"></canvas></div>
      <div class="card"><canvas id="t_slide" height="150"></canvas></div>
    </div>
  </div>

  <div class="panel">
    <h2>使用意欲シグナル（会社別 前期比）</h2>
    <div class="legend-tip">当期件数が前期比で増 → 利用拡大。前期3件以上から減 → 要フォロー。</div>
    <table>
      <thead><tr><th>会社</th><th style="text-align:right">当期</th><th style="text-align:right">前期</th><th style="text-align:right">増減</th><th>シグナル</th></tr></thead>
      <tbody id="sigBody"></tbody>
    </table>
  </div>

  <div class="panel">
    <h2>チャート分析</h2>
    <div class="grid2">
      <div class="card"><canvas id="c_daily" height="150"></canvas></div>
      <div class="card"><canvas id="c_bin" height="150"></canvas></div>
    </div>
    <div class="card full"><canvas id="c_comp" height="170"></canvas></div>
    <div class="note" id="footNote"></div>
  </div>
</div>
<script>
const DATA = __DATA__;
const CK = {primary:'#0C5CAB', primary2:'#2f81d6', sky:'#38bdf8', success:'#10b981', warning:'#f59e0b'};
Chart.defaults.font.family = "'IBM Plex Sans JP','IBM Plex Sans',sans-serif";
let charts = {}, currentKey = __FIRST__;

function css(v){ return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function themeColors(){ return {axis:css('--axis'), grid:css('--grid'), text:css('--text'), tmuted:css('--trendmuted')}; }
function destroyCharts(){ Object.values(charts).forEach(c=>c&&c.destroy()); charts={}; }
function axes(){ const t=themeColors(); return {
  x:{grid:{color:t.grid},ticks:{color:t.axis}},
  y:{grid:{color:t.grid},ticks:{color:t.axis},beginAtZero:true} }; }
function axesFree(){ const t=themeColors(); return {
  x:{grid:{color:t.grid},ticks:{color:t.axis}},
  y:{grid:{color:t.grid},ticks:{color:t.axis},beginAtZero:false} }; }
function titleOpt(txt){ return {display:true,text:txt,color:themeColors().text,font:{size:13,weight:'600'},padding:{bottom:10}}; }

function lineChart(ctx, labels, data, title, color, free){
  return new Chart(ctx,{type:'line',data:{labels,datasets:[{label:title,data,
      borderColor:color,backgroundColor:color+'22',fill:true,tension:.3,
      pointBackgroundColor:color,pointRadius:3,pointHoverRadius:5,borderWidth:2}]},
    options:{plugins:{legend:{display:false},title:titleOpt(title)},
      scales: free?axesFree():axes()}});
}

function render(key){
  currentKey = key;
  const p = DATA[key];
  document.getElementById('periodInfo').innerHTML = '<b>'+p.label+'</b>　|　'+p.pp;

  document.getElementById('kpis').innerHTML = p.kpis.map(k =>
    `<div class="kpi"><div class="kpi-label">${k.label}</div>`+
    `<div class="kpi-value">${k.value}<span class="kpi-unit">${k.unit}</span></div>`+
    `<div class="kpi-delta">${k.delta}</div></div>`).join('');

  document.getElementById('sigBody').innerHTML = p.signals.length ? p.signals.map(s =>
    `<tr><td>${s.comp}</td><td class="num">${s.cur}</td><td class="num">${s.prev}</td>`+
    `<td class="num ${s.cls}">${s.diff>0?'+':''}${s.diff}</td>`+
    `<td><span class="pill ${s.cls}">${s.lab}</span></td></tr>`
  ).join('') : '<tr><td colspan="5" style="color:var(--muted)">前期データなし</td></tr>';

  document.getElementById('footNote').textContent =
    `※ 「純所要時間」= log 間隔 ≥ 1 時間の中断を除外した実生成時間。`+
    `統計上の未生成 ${p.excluded} 件 / 中断あり ${p.breaks} 件 / 生成成功 ${p.gen_n} 件。`;

  destroyCharts();
  // 推移トレンド（trend がある期間のみ表示）
  const tp = document.getElementById('trendPanel');
  if (p.trend) {
    tp.classList.remove('hidden');
    const T = p.trend;
    charts.tTotal = lineChart(t_total, T.labels, T.total, '生成件数の推移', CK.primary, false);
    charts.tComp  = lineChart(t_comp,  T.labels, T.completion, '完成率の推移（%）', CK.success, true);
    charts.tSlide = lineChart(t_slide, T.labels, T.avgslide, '平均秒/頁の推移', CK.warning, true);
  } else {
    tp.classList.add('hidden');
  }

  const C = p.charts, tc = themeColors();
  charts.daily = new Chart(c_daily,{type:'bar',data:{labels:C.daily.labels,datasets:[{label:'件数',data:C.daily.data,backgroundColor:CK.primary,borderRadius:4,maxBarThickness:40}]},options:{plugins:{legend:{display:false},title:titleOpt('日別 PPT 生成件数')},scales:axes()}});
  charts.bin = new Chart(c_bin,{type:'bar',data:{labels:C.bins.labels,datasets:[{label:'件数',data:C.bins.data,backgroundColor:CK.sky,borderRadius:4,maxBarThickness:40}]},options:{plugins:{legend:{display:false},title:titleOpt('所要時間分布（生成成功）')},scales:axes()}});
  charts.comp = new Chart(c_comp,{type:'bar',data:{labels:C.comp.labels,datasets:p.has_prev?[{label:'当期',data:C.comp.cur,backgroundColor:CK.primary,borderRadius:4},{label:'前期',data:C.comp.prev,backgroundColor:tc.tmuted,borderRadius:4}]:[{label:'当期',data:C.comp.cur,backgroundColor:CK.primary,borderRadius:4}]},options:{indexAxis:'y',plugins:{legend:{display:p.has_prev,labels:{color:tc.axis,boxWidth:12}},title:titleOpt('会社別件数'+(p.has_prev?'（当期 vs 前期）':'（当期）'))},scales:axes()}});
}

// テーマ切替
function applyTheme(theme){
  document.documentElement.dataset.theme = theme;
  document.getElementById('themeBtn').textContent = theme === 'dark' ? '🌙' : '☀️';
  try { localStorage.setItem('bops_theme', theme); } catch(e){}
  render(currentKey);  // チャート色をテーマに合わせ再描画
}
document.getElementById('themeBtn').addEventListener('click', ()=>{
  applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
});

document.querySelectorAll('.seg-btn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.seg-btn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  render(b.dataset.key);
}));

(function init(){
  let theme = 'dark';
  try {
    theme = localStorage.getItem('bops_theme')
      || (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  } catch(e){}
  applyTheme(theme);   // 内部で render を呼ぶ
})();
</script>
</body></html>"""


if __name__ == '__main__':
    main()
