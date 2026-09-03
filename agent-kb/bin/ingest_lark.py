#!/usr/bin/env python3
"""IM 入口：接收 Lark 事件订阅回调（im.message.receive_v1）→ inbox/ 事件文件。

1. 在 Lark 开放平台建一个自建应用，开通「接收消息」事件，事件订阅地址填本服务的公网地址
   （本地开发用 ngrok / cloudflared 把 8787 端口暴露出去；或改用 lark-oapi SDK 的长连接模式，不需要公网）。
2. 把应用拉进目标群。
3. LARK_VERIFICATION_TOKEN=xxx python3 bin/ingest_lark.py

注意：本示例不处理 Encrypt Key 加密，创建应用时留空 Encrypt Key。
收到事件后立刻跑一次 bin/triage.sh，就是“agent 主动接受 IM event”。
"""
import datetime, json, os, subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

KB = Path(__file__).resolve().parent.parent
INBOX = KB / "inbox"
TOKEN = os.environ.get("LARK_VERIFICATION_TOKEN", "")
TRIGGER_TRIAGE = os.environ.get("TRIGGER_TRIAGE", "1") == "1"


def write_event(ev):
    msg, sender = ev["message"], ev.get("sender", {})
    content = json.loads(msg.get("content", "{}"))
    text = content.get("text") or json.dumps(content, ensure_ascii=False)
    ts = datetime.datetime.fromtimestamp(int(msg["create_time"]) / 1000).astimezone()
    meta = {
        "id": f"im-{msg['message_id']}", "source": "im", "ts": ts.isoformat(),
        "from": sender.get("sender_id", {}).get("open_id", ""),
        "subject": f"Lark {msg.get('chat_type')} {msg.get('chat_id')}",
        "thread": msg.get("root_id") or msg.get("chat_id", ""),
    }
    fm = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items())
    path = INBOX / f"{ts.strftime('%Y%m%d-%H%M')}-im-{msg['message_id']}.md"
    path.write_text(f"---\n{fm}\n---\n\n{text.strip()}\n", encoding="utf-8")
    return path


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or b"{}"))
        # 首次配置回调地址时的校验
        if body.get("type") == "url_verification":
            return self.reply({"challenge": body.get("challenge", "")})
        header = body.get("header", {})
        if TOKEN and header.get("token") != TOKEN:
            return self.reply({"error": "bad token"}, 403)
        if header.get("event_type") == "im.message.receive_v1":
            p = write_event(body["event"])
            print("写入", p.name)
            if TRIGGER_TRIAGE:
                subprocess.Popen(["bash", str(KB / "bin" / "triage.sh")], cwd=KB)
        self.reply({"ok": True})

    def reply(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8787"))
    print(f"IM 入口监听 :{port}")
    HTTPServer(("0.0.0.0", port), H).serve_forever()
