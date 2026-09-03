#!/usr/bin/env python3
"""会议入口：监视一个目录（会议纪要 / 转写导出，.md .txt .vtt .srt）→ inbox/ 事件文件。
环境变量：MEETING_DIR（例如 Lark 妙记 / Zoom 的导出目录，或你手动放纪要的文件夹）
已处理的文件名记录在 .meeting_seen，不会重复入库。
"""
import datetime, json, os, sys
from pathlib import Path

KB = Path(__file__).resolve().parent.parent
INBOX = KB / "inbox"
SEEN = KB / ".meeting_seen"
EXTS = {".md", ".txt", ".vtt", ".srt"}


def main():
    src = os.environ.get("MEETING_DIR")
    if not src:
        sys.exit("MEETING_DIR 未设置")
    seen = set(SEEN.read_text().split()) if SEEN.exists() else set()
    n = 0
    for f in sorted(Path(src).glob("*")):
        if f.suffix.lower() not in EXTS or f.name in seen:
            continue
        ts = datetime.datetime.fromtimestamp(f.stat().st_mtime).astimezone()
        meta = {"id": f"meeting-{f.stem}", "source": "meeting", "ts": ts.isoformat(),
                "from": "", "subject": f.stem, "thread": ""}
        fm = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items())
        out = INBOX / f"{ts.strftime('%Y%m%d-%H%M')}-meeting-{f.stem[:40]}.md"
        out.write_text(f"---\n{fm}\n---\n\n{f.read_text(encoding='utf-8', errors='replace').strip()}\n", encoding="utf-8")
        seen.add(f.name)
        print("写入", out.name)
        n += 1
    SEEN.write_text("\n".join(sorted(seen)))
    print(f"会议入口：{n} 个新事件")


if __name__ == "__main__":
    main()
