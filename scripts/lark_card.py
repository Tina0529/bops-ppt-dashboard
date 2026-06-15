#!/usr/bin/env python3
"""BOPS PPT モニタの結果を Lark Interactive Card（chart 組件入り）で送る。

webhook だけで折線/柱状チャートを描ける（Lark card 2.0 の chart 要素 = VChart）。
アプリ凭证は不要。→ 毎日 Lark 群で KPI + 推移トレンドを一目で確認できる。

使い方:
  LARK_WEBHOOK=https://... python3 lark_card.py <summary.json> <trend_weekly.csv> <trend_monthly.csv>
  webhook 未設定ならカード JSON を stdout に出すだけ（デバッグ用）。
"""
import csv as csvmod
import json
import os
import sys
import urllib.request


def load_trend(path):
    if not path or path == '-' or not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return list(csvmod.DictReader(f))


def fmt_pct(v):
    return f'{v*100:.1f}%' if isinstance(v, (int, float)) else '-'


def delta_md(cur, prev, unit='', pt=False):
    """環比を ▲緑/▼赤 の markdown で。"""
    if not isinstance(cur, (int, float)) or not isinstance(prev, (int, float)):
        return ''
    d = (cur - prev) * 100 if pt else (cur - prev)
    s = f'{abs(d):.1f}pt' if pt else f'{abs(d):g}{unit}'
    if d > 0.05:
        return f" <font color='green'>▲{s}</font>"
    if d < -0.05:
        return f" <font color='red'>▼{s}</font>"
    return " <font color='grey'>±0</font>"


def metric_card(value, label, color, sub=''):
    content = [
        {"tag": "markdown", "content": f"## <font color='{color}'>{value}</font>", "text_align": "center"},
        {"tag": "markdown", "content": f"<font color='grey'>{label}</font>", "text_align": "center"},
    ]
    if sub:
        content.append({"tag": "markdown", "content": sub, "text_align": "center", "text_size": "notation"})
    return {"tag": "column", "weight": 1, "width": "weighted", "padding": "10px",
            "background_style": f"{color}-50", "vertical_spacing": "2px", "elements": content}


def line_chart(title, rows, yfield_key, transform=lambda v: v):
    values = [{"x": r['label'], "y": transform(float(r[yfield_key]))} for r in rows]
    return {"tag": "chart", "aspect_ratio": "16:9", "chart_spec": {
        "type": "line", "title": {"text": title},
        "data": {"values": values}, "xField": "x", "yField": "y",
        "label": {"visible": True}, "point": {"visible": True},
        "line": {"smooth": True}}}


def section(text):
    return {"tag": "markdown", "content": f"**<font color='blue'>▎</font> {text}**", "text_size": "heading"}


def build_card(summary, tw, tm):
    date = summary.get('date', '?')
    d = summary.get('daily', {})
    w = summary.get('weekly', {})
    els = []

    # KPI（本週、環比つき）
    pt = w.get('prev_total')
    pc = w.get('prev_completion')
    els.append({"tag": "column_set", "flex_mode": "none", "horizontal_spacing": "8px", "columns": [
        metric_card(f"{w.get('total','-')}", "本週 生成件数", "blue",
                    delta_md(w.get('total'), pt) if pt is not None else ''),
        metric_card(fmt_pct(w.get('completion')), "完成率", "turquoise",
                    delta_md(w.get('completion'), pc, pt=True) if pc is not None else ''),
        metric_card(f"{w.get('avg_per_slide','-')}秒", "1ページ平均", "violet"),
        metric_card(f"{w.get('breaks','-')}", "中断件数", "orange"),
    ]})
    els.append({"tag": "markdown",
                "content": f"<font color='grey'>【当日 {date}】生成 {d.get('generated','-')}/{d.get('total','-')} 件"
                           f" · 完成率 {fmt_pct(d.get('completion'))} · 平均 {d.get('avg_per_slide','-')}秒/頁</font>"})
    els.append({"tag": "hr"})

    # 推移トレンド（折線）
    if tw:
        els.append(section("推移トレンド（週次）"))
        els.append(line_chart("生成件数の推移", tw, 'total'))
        els.append(line_chart("完成率の推移（%）", tw, 'completion', transform=lambda v: round(v * 100, 1)))
        els.append(line_chart("平均秒/頁の推移", tw, 'avg_per_slide'))
    if tm:
        els.append(section("推移トレンド（月次・生成件数）"))
        els.append(line_chart("月次 生成件数の推移", tm, 'total'))
    els.append({"tag": "hr"})

    # 使用意欲シグナル
    rising = w.get('rising') or []
    falling = w.get('falling') or []
    sig = "**使用意欲シグナル（会社別 前期比）**\n"
    if rising:
        sig += "🟢 利用拡大: " + ", ".join(rising) + "\n"
    if falling:
        sig += "🔴 利用縮小(要フォロー): " + ", ".join(falling) + "\n"
    if not rising and not falling:
        sig += "<font color='grey'>前期比データなし</font>\n"
    els.append({"tag": "markdown", "content": sig})

    dash_url = os.environ.get('DASHBOARD_URL')
    if dash_url:
        foot = ("<font color='grey'>完全な交互ダッシュボード（テーマ切替/期間フィルタ/会社別チャート）→ "
                f"[GitHub で開く]({dash_url})（Download raw → ブラウザで表示）</font>")
    else:
        foot = ("<font color='grey'>完全な交互ダッシュボード（テーマ切替/期間フィルタ/会社別チャート）は "
                "reports/BOPS_PPT_Dashboard.html</font>")
    els.append({"tag": "markdown", "content": foot, "text_size": "notation"})

    return {"schema": "2.0",
            "header": {"template": "blue",
                       "icon": {"tag": "standard_icon", "token": "bar-chart_2_outlined", "color": "blue"},
                       "title": {"tag": "plain_text", "content": f"  BOPS PPT Monitor  {date}"}},
            "body": {"elements": els}}


def main():
    summary_path = sys.argv[1] if len(sys.argv) > 1 else None
    tw = load_trend(sys.argv[2]) if len(sys.argv) > 2 else []
    tm = load_trend(sys.argv[3]) if len(sys.argv) > 3 else []
    summary = {}
    if summary_path and os.path.exists(summary_path):
        with open(summary_path, encoding='utf-8') as f:
            summary = json.load(f)

    card = build_card(summary, tw, tm)
    webhook = os.environ.get('LARK_WEBHOOK')
    if not webhook:
        print(json.dumps(card, ensure_ascii=False, indent=2))
        print('[lark_card] LARK_WEBHOOK 未設定 → カード JSON を出力のみ', file=sys.stderr)
        return

    payload = json.dumps({"msg_type": "interactive", "card": card}).encode('utf-8')
    req = urllib.request.Request(webhook, data=payload,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode('utf-8', 'ignore')
            print(f'[lark_card] sent ({resp.status}) {body[:120]}')
    except Exception as e:
        print(f'[lark_card] 送信失敗（本体に影響なし）: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
