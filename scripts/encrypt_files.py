#!/usr/bin/env python3
"""明細ページ（detail.html）のダウンロード列用に、会話内生成 PPTX を暗号化して docs/files/ に置く。

Pages は公開ホスティングなので、顧客の PPT を平文で置かない。
  - 鍵: 環境変数 PPT_FILE_KEY（GitHub Secret）の口令から PBKDF2-SHA256 で導出した AES-256-GCM 鍵
  - ファイル: docs/files/<YYYY-MM>/<明細 id>.enc = IV(12B) + 暗号文 + tag
  - docs/files/meta.json : salt / 反復回数 / 口令確認用の check（ページが口令の正否を判定する）
  - docs/files/index.json: {"files": {id: {"m": 月, "n": ファイル名, "s": 平文サイズ}}}
ページはブラウザ内（WebCrypto）で復号する。口令はページにもリポジトリにも書かない。

  python3 encrypt_files.py --stage <fetch_bops.py の PPT_FILE_STAGE> --out docs/files --date YYYY-MM-DD

- 既に暗号化済みのファイルは作り直さない（毎晩 IV が変わって差分が増えるのを防ぐ）。サイズが変われば作り直す。
- 保存期間: 基準日の当月＋前月。それより古い月のディレクトリは削除する。
- 口令が変わったら既存ファイルを全部消して、今回取得した分だけ新しい鍵で作り直す。
- PPT_FILE_KEY が未設定なら何もしない（ダウンロード列は出ないだけで、サイト生成は続行）。
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITER = 310000
CHECK = b'bops-ppt-dashboard'
MONTH_RE = re.compile(r'^\d{4}-\d{2}$')


def derive(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, ITER, 32)


def encrypt(key, data):
    iv = os.urandom(12)
    return iv + AESGCM(key).encrypt(iv, data, None)


def decrypt(key, blob):
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)


def b64e(b):
    return base64.b64encode(b).decode('ascii')


def month_dirs(out):
    return [d for d in os.listdir(out) if MONTH_RE.match(d) and os.path.isdir(os.path.join(out, d))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--date', required=True, help='基準日 YYYY-MM-DD（保存期間の判定に使う）')
    args = ap.parse_args()

    pw = os.environ.get('PPT_FILE_KEY', '')
    if not pw:
        print('[encrypt_files] PPT_FILE_KEY 未設定 → スキップ（ダウンロード列は更新されない）')
        return 0
    if len(pw) < 16:
        print('[encrypt_files] WARN: 口令が短い（16 文字以上を推奨）', file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    meta_p = os.path.join(args.out, 'meta.json')
    idx_p = os.path.join(args.out, 'index.json')

    key = None
    if os.path.exists(meta_p):
        with open(meta_p, encoding='utf-8') as f:
            meta = json.load(f)
        if meta.get('iter') == ITER:
            k = derive(pw, base64.b64decode(meta['salt']))
            try:
                if decrypt(k, base64.b64decode(meta['check'])) == CHECK:
                    key = k
            except Exception:
                pass
        if key is None:
            print('[encrypt_files] 口令（または方式）が変わった → 既存の暗号化ファイルを削除して作り直す')
    if key is None:
        for d in month_dirs(args.out):
            shutil.rmtree(os.path.join(args.out, d))
        if os.path.exists(idx_p):
            os.remove(idx_p)
        salt = os.urandom(16)
        key = derive(pw, salt)
        meta = {'v': 1, 'kdf': 'PBKDF2-SHA256', 'iter': ITER, 'salt': b64e(salt),
                'cipher': 'AES-256-GCM', 'check': b64e(encrypt(key, CHECK))}
        with open(meta_p, 'w', encoding='utf-8') as f:
            json.dump(meta, f)

    index = {}
    if os.path.exists(idx_p):
        with open(idx_p, encoding='utf-8') as f:
            index = (json.load(f) or {}).get('files', {})

    # 保存期間: 当月＋前月
    d = datetime.strptime(args.date, '%Y-%m-%d')
    prev = f'{d.year - 1}-12' if d.month == 1 else f'{d.year}-{d.month - 1:02d}'

    added = 0
    if os.path.isdir(args.stage):
        for m in sorted(os.listdir(args.stage)):
            if not MONTH_RE.match(m) or m < prev:
                continue
            for fn in sorted(os.listdir(os.path.join(args.stage, m))):
                if not fn.endswith('.pptx'):
                    continue
                rid = fn[:-5]
                with open(os.path.join(args.stage, m, fn), 'rb') as f:
                    data = f.read()
                try:
                    with open(os.path.join(args.stage, m, rid + '.json'), encoding='utf-8') as f:
                        name = json.load(f).get('name') or (rid + '.pptx')
                except Exception:
                    name = rid + '.pptx'
                dst = os.path.join(args.out, m, rid + '.enc')
                old = index.get(rid)
                if not os.path.exists(dst) or not old or old.get('s') != len(data):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, 'wb') as f:
                        f.write(encrypt(key, data))
                    added += 1
                index[rid] = {'m': m, 'n': name, 's': len(data)}

    removed = 0
    for m in month_dirs(args.out):
        if m < prev:
            shutil.rmtree(os.path.join(args.out, m))
            removed += 1
    index = {rid: v for rid, v in index.items()
             if os.path.exists(os.path.join(args.out, v['m'], rid + '.enc'))}
    with open(idx_p, 'w', encoding='utf-8') as f:
        json.dump({'v': 1, 'files': index}, f, ensure_ascii=False, separators=(',', ':'))
    print(f'[encrypt_files] 新規/更新 {added} 件、削除した月 {removed}、公開中 {len(index)} 件（{prev} 以降）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
