#!/usr/bin/env python3
"""邮件入口：IMAP 未读邮件 → inbox/ 事件文件。
环境变量：IMAP_HOST IMAP_USER IMAP_PASS [IMAP_FOLDER=INBOX]
Gmail 用应用专用密码；Outlook/Lark Mail 开 IMAP 即可。
"""
import datetime, email, imaplib, json, os, sys
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

INBOX = Path(__file__).resolve().parent.parent / "inbox"


def hdr(msg, key):
    return str(make_header(decode_header(msg.get(key, "")))).strip()


def body_of(msg):
    parts = msg.walk() if msg.is_multipart() else [msg]
    for p in parts:
        if p.get_content_type() == "text/plain" and not p.get("Content-Disposition"):
            return p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
    return "(无纯文本正文)"


def write_event(uid, msg):
    ts = parsedate_to_datetime(msg["Date"]) if msg.get("Date") else datetime.datetime.now().astimezone()
    meta = {
        "id": f"mail-{uid}", "source": "mail", "ts": ts.isoformat(),
        "from": hdr(msg, "From"), "subject": hdr(msg, "Subject"),
        "thread": msg.get("In-Reply-To") or msg.get("Message-ID") or "",
    }
    fm = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items())
    path = INBOX / f"{ts.strftime('%Y%m%d-%H%M')}-mail-{uid}.md"
    path.write_text(f"---\n{fm}\n---\n\n{body_of(msg).strip()}\n", encoding="utf-8")
    return path


def main():
    host, user, pw = (os.environ.get(k) for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASS"))
    if not all((host, user, pw)):
        sys.exit("IMAP_HOST / IMAP_USER / IMAP_PASS 未设置")
    m = imaplib.IMAP4_SSL(host)
    m.login(user, pw)
    m.select(os.environ.get("IMAP_FOLDER", "INBOX"))
    _, data = m.search(None, "UNSEEN")
    n = 0
    for uid in data[0].split():
        _, raw = m.fetch(uid, "(RFC822)")
        p = write_event(uid.decode(), email.message_from_bytes(raw[0][1]))
        m.store(uid, "+FLAGS", "\\Seen")
        print("写入", p.name)
        n += 1
    m.logout()
    print(f"邮件入口：{n} 个新事件")


if __name__ == "__main__":
    main()
