# BOPS PPT Dashboard

BOPS の PPT 生成記録を**毎晩 20:00 JST に自動集計**し、GitHub Pages で公開する
ダッシュボード。当日/当週/当月の KPI・推移トレンド・使用意欲シグナル＋**明細ページ**を
ブラウザで直接閲覧でき、毎晩 Lark に図表カード（クリック可能な Pages リンク付き）を通知する。

公開 URL（Pages 有効化後）: **https://tina0529.github.io/bops-ppt-dashboard/**

---

## ⚠️ データ公開に関する重要な注意

- GitHub Pages は**公開ホスティング**で、アクセス制御（パスワード）は掛けられない。
- このダッシュボード／明細ページには **実顧客名（アビーム等）・PPT タイトル・利用量**が含まれる。
- **URL を知っている人は誰でも公開ネット上で閲覧可能**になる。`noindex` + `robots.txt` で
  検索エンジンのインデックスは防ぐが、URL 漏洩には対抗できない。
- これは Sparticle の顧客データの公開であり、**公開する判断と責任は運用者にある**。
  懸念がある場合は顧客名を伏せる（匿名化）か、公開を取りやめること。

---

## デプロイ手順（運用者が実施）

### 1. 再利用スクリプトをコピー

本リポジトリには「新規作成したコード」のみ含まれる。データ処理の共通スクリプトは
姉妹プロジェクト `sparticle-toolkit` の `bops-ppt-monitor` からコピーする:

```bash
SRC=/path/to/sparticle-toolkit/personal-plugins/denya/skills/bops-ppt-monitor/scripts
cp "$SRC"/{auth.py,fetch_bops.py,generate_xlsx.py,preview_html.py,update_trend.py,backfill_trend.py,make_summary.py,lark_card.py} ./scripts/
```

> `lark_card.py` は `DASHBOARD_URL` 環境変数に対応済み（footer にクリック可能リンクを出す）。

### 2. リポジトリを作成して push

```bash
gh repo create Tina0529/bops-ppt-dashboard --public
git init && git add . && git commit -m "init: BOPS PPT Dashboard"
git branch -M main && git remote add origin git@github.com:Tina0529/bops-ppt-dashboard.git
git push -u origin main
```

### 3. Secrets を登録

Settings → Secrets and variables → Actions:

| Secret | 用途 |
|---|---|
| `BOPS_USERNAME` | BOPS ログイン ID（自動ログイン） |
| `BOPS_PASSWORD` | BOPS ログインパスワード |
| `LARK_WEBHOOK_GBASE_PPT_DAILY_MONITOR` | Lark 通知先 webhook |

### 4. Pages を有効化

Settings → Pages → Source = **Deploy from a branch** → Branch = **main** / **/docs**

### 5. Actions の書き込み権限

Settings → Actions → General → Workflow permissions = **Read and write**

### 6. 初回実行（トレンド初期化込み）

Actions → "BOPS PPT Dashboard Daily" → Run workflow → `backfill_days = 70` で実行。
完了後 https://tina0529.github.io/bops-ppt-dashboard/ を開いて確認。
以後は毎晩 20:00 JST に自動更新される。

---

## 構成

```
bops-ppt-dashboard/
├── docs/                      ← GitHub Pages 公開対象
│   ├── index.html             Dashboard（KPI/トレンド/会社別/シグナル、期間切替、明暗テーマ）
│   ├── detail.html            明細ページ（当日/当週/当月、Excel 列準拠、ソート/検索）
│   ├── robots.txt             検索エンジン除外
│   ├── .nojekyll
│   └── data/                  CI が生成（dashboard.json / detail.json / trend_*.csv）
│                              trend_org_monthly.csv = 組織別 月次推移（long 形式）
├── scripts/
│   ├── generate_site.py       TSV → dashboard.json + detail.json（本リポジトリ固有）
│   ├── org_trend.py           組織別 月次集計の共通ロジック（本リポジトリ固有）
│   ├── update_org_trend.py    当月 TSV → trend_org_monthly.csv へ upsert（本リポジトリ固有）
│   ├── backfill_org_trend.py  archive/*.json から組織別トレンドを再構築（本リポジトリ固有）
│   ├── run_site.sh            オーケストレータ（本リポジトリ固有）
│   └── （上記 1. でコピーする 8 ファイル）
└── .github/workflows/daily.yml  毎晩 20:00 JST cron
```

## 組織別 月次推移（生成本数）

Dashboard 下部の「組織別 月次推移」パネル。会社ごとの月次生成本数を折れ線／積み上げ棒で
切り替えて表示し、下に**全社のマトリクス表**（会社 × 月 + 合計 + 前月比）を出す。

- データ源: `docs/data/trend_org_monthly.csv`（`month,company,total,generated,completion,avg_per_slide`）
- 集計口径は `generate_xlsx.aggregate` と同一（`status=failed` / `logsCount<=1` は未生成扱い）。
  月次合計は `trend_monthly.csv` の `total` / `generated` と一致する。
- グラフは**上位6社を個別表示**、それ以外は「その他 N社」に集約。凡例クリックで表示/非表示を切替でき、
  件数の多い社を隠すと小規模社の推移が読める。表は全社を掲載。
- **集計途中の月には `※進行中` を表示**する。締まった月との単純比較・前月比は過小に出るため注意。
- 会社名が空のレコードは `(未設定)` に寄せる。

### 過去分の再構築（backfill）

`docs/data/archive/*.json` があればオフラインで作り直せる（BOPS 接続不要）:

```bash
python3 scripts/backfill_org_trend.py
# 既定: docs/data/archive → docs/data/trend_org_monthly.csv
```

> アーカイブが無い月（例: 2026-05）は組織別内訳を復元できない。月次合計のみ `trend_monthly.csv` に残る。

## 明細ページ（detail.html）の列（Excel 準拠）

ID / トピック / ユーザー / 会社 / 戦略 / 状態 / スライド数(一覧) / 実際 / 統計用 /
作成日時 / 開始 / 終了 / 所要(秒) / mm:ss / ログ件数 / 平均秒/頁 / 未做成原因 /
中断回数 / 最大中断(秒)

- 灰色行 = 統計上の未生成（status 空/created かつ logsCount≤1）
- 黄色セル = 中断（log 間隔 ≥ 1 時間）あり
- 列ヘッダクリックでソート、検索ボックスで絞り込み
