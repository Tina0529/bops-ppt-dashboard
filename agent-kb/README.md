# 本地 Triage Agent → Topic Agent → Knowledge Base（会话优先版）

用 Claude Code 无头模式 + 一组 Markdown 文件 + 几个 shell / python 脚本搭起来，不依赖任何框架。

**设计原则：会话是工作记忆，文件是持久记忆。**
每个主题有一个专属会话，同主题的事件持续发给它，它不需要每次重读知识库，处理快、便宜、连贯。
文件层负责三件事：会话轮换时交接给下一任、让 triage 和人看到状态、出错时从干净状态重来。

```
kb/
├── _topics.md                  顶层主题索引 = 路由表（人维护，agent 不改）
├── _log.md                     路由与轮换日志（脚本写）
├── CLAUDE.md                   所有 agent 共享的规则：两层记忆、文件约定、边界
├── kb.conf                     轮换阈值、工具白名单
├── inbox/                      待处理事件，每个事件一个 .md（入口脚本写入）
├── topics/<slug>/
│   ├── _progress.md            当前状态 / 待办 / 待确认 / 决策 / 最近事件 / 给下一任的交接
│   ├── research/ plans/ data/  独立详情文档
│   ├── events/                 已处理的原始事件
│   └── archive/                从 _progress.md 归档出去的内容
├── .claude/skills/
│   ├── triage/                 分拣：读正文 → 匹配 _topics.md → ROUTE_JSON（不做处理）
│   ├── topic-work/             主题处理：用会话里已有的上下文处理事件，轻量写回
│   └── handoff/                交接：轮换前把脑子里有、文件里没有的东西写进 _progress.md
├── .sessions.json              slug → 当前专属会话（id、第几任、事件数、上下文大小）
├── .threads.json               线程 → slug，同一线程的后续消息直达，不经 triage
└── bin/
    ├── triage.sh               主循环（见下）
    ├── rotate.sh <slug>        手动轮换：让当前会话写交接，下一事件换新一任
    ├── chat.sh <slug>          直接和某主题的专属 agent 对话（恢复它的会话）
    ├── status.sh               各主题会话状态一览
    ├── tick.sh                 定时入口：采集 + triage
    ├── ingest_mail.py          邮件入口（IMAP）
    ├── ingest_lark.py          IM 入口（Lark 事件订阅回调，收到即触发 triage）
    ├── ingest_meeting.py       会议入口（监视纪要 / 转写导出目录）
    └── mock_claude.sh          假的 claude，不花钱跑通脚本逻辑
```

## 主循环 `bin/triage.sh` 做什么

对 `inbox/` 里的每个事件：

0. **线程直达**。事件的 `thread` 之前路由过，直接送到那个主题，不再问 triage。
1. **Triage 分拣**。新开一个便宜的调用，读正文、对照 `_topics.md`，输出主题和置信度。分拣不需要记忆，每次新开。
2. **该主题有专属会话在跑？**
   是 → `--resume` 它，事件交给它处理（热路径，图里的「专属主题 Agent 接手」）。
   否 → 新开一任，先读 `_progress.md` 和上一任留下的「给下一任的交接」。
3. **轻量写回**。最近事件加一行、待办增删、当前状态只在变化时改；然后 `git commit`。
4. **轮换判断**。满足任一条件就让当前会话趁热写交接，然后关闭，下一事件换新一任：
   - agent 自己在输出里写了 `ROTATE: <原因>`（阶段性终点，或它觉得上下文堆了太多无关细节）
   - 最近一次调用的上下文超过 `ROTATE_CTX_TOKENS`（默认 12 万，避开自动压缩）
   - 本任处理的事件数超过 `ROTATE_MAX_EVENTS`（默认 30）
   - 闲置超过 `ROTATE_IDLE_DAYS`（默认 3 天，下一事件来时先交接再新开）

轮换是这套方案的关键：与其等 Claude Code 在上限附近自动压缩（一次你控制不了的有损摘要），
不如让 agent 在合适的节点主动写交接，把已排除的方案、未验证的假设、相关方的偏好这些不会进正文的东西留给下一任。

## 第 1 步：跑通闭环

```bash
cp -r kb-starter ~/kb && cd ~/kb
git init -q && git add -A && git commit -qm "init kb"
claude --version && jq --version         # 需要 Claude Code 和 jq

CLAUDE_BIN=bin/mock_claude.sh bin/triage.sh   # 先用 mock 看流程，不花钱
git reset -q --hard && git clean -qfd          # 复原
bin/triage.sh                                  # 真跑：inbox/ 里有一个样例 IM 事件
bin/status.sh
```

看四处变化：`_log.md` 多了一行路由记录；`topics/agent-lecture/_progress.md` 被更新；
大块产出进了 `research/` 或 `plans/`；事件文件移到了 `events/`。

再往 `inbox/` 丢第二个同主题事件再跑一次：会打印「专属会话在跑，Session Handoff 给 …」，处理明显更快，
而且它记得上一条的上下文。

## 第 2 步：换成你自己的主题

编辑 `_topics.md` 加一行，`cp topics/_template_progress.md topics/<slug>/_progress.md` 并填好当前状态。
描述 / 关键词写得越具体，路由越准。`auto` 列决定 agent 能自动做什么，其余动作只会进「待确认」。

## 第 3 步：接入口

| 入口 | 脚本 | 需要什么 |
|---|---|---|
| 邮件 | `bin/ingest_mail.py` | `IMAP_HOST / IMAP_USER / IMAP_PASS`，Gmail 用应用专用密码 |
| IM | `bin/ingest_lark.py` | Lark 自建应用 + 事件订阅「接收消息」，本地用 ngrok 暴露 8787 端口，或改用 lark-oapi 长连接 |
| 会议 | `bin/ingest_meeting.py` | `MEETING_DIR` 指向纪要 / 转写导出目录 |

每个入口只做一件事：把原始资料变成 `inbox/` 里带 frontmatter 的 Markdown。格式见 `inbox/README.md`。
`thread` 字段尽量填（邮件的 Message-ID / In-Reply-To，IM 的会话或话题 id），线程直达靠它。

## 第 4 步：让它自己转

- 轮询：`crontab -e` 加 `*/10 * * * * cd ~/kb && bin/tick.sh >> .tick.log 2>&1`
- 事件驱动：`ingest_lark.py` 收到消息就直接起一次 `triage.sh`。并发由 `.lock` 目录保护，同时只跑一个。

## 第 5 步：人怎么进出这个环

- **看**：`bin/status.sh` 看每个主题第几任、处理了多少事件、上下文多大；`_progress.md` 的「待确认」是需要你拍板的。
- **答**：在 Lark 群回一句「按方案 A 走」，那句话又是一个 IM 事件，路由到同一主题，专属 agent 读到后继续做。
- **聊**：`bin/chat.sh <slug>` 直接进入该主题专属 agent 的会话，和一直在盯这件事的那个它对话。聊完它继续接收事件。
- **换**：`bin/rotate.sh <slug>` 手动让它交接换人，比如你觉得它跑偏了。
- **分拣**：在 `~/kb` 下直接运行 `claude`，输入 `/triage 事件文件：inbox/xxx.md` 就是手动分拣。

## 调参与安全

- `kb.conf` 里改阈值。事件密集的主题可以把 `ROTATE_CTX_TOKENS` 调高一些，充分利用缓存；事件稀疏的主题靠 `ROTATE_IDLE_DAYS`。
- 路由不准：看 `_log.md` 的置信度和理由，改 `_topics.md` 的关键词，不要改 prompt。
- 权限：`--permission-mode acceptEdits` + `--allowedTools` 白名单，agent 只能读写文件和 mv / mkdir，不能发消息、发邮件。
  要放开某个动作，先在 `_topics.md` 的 `auto` 列写明，再把对应工具加进 `kb.conf` 的 `TOOLS`。
- 每处理一个事件 commit 一次，出问题 `git revert`。
- 上下文大小取自 `claude -p --output-format json` 返回的 `usage.iterations` 最后一项。如果你的版本没有这个字段，估算会是 0，
  轮换就只靠事件数和闲置天数，功能不受影响。

## 用 Codex 的话

指令文件用 `AGENTS.md`（内容同 CLAUDE.md，或在 CLAUDE.md 里写 `@AGENTS.md` 引用），
`bin/lib.sh` 的 `run_claude` 换成 `codex exec`，会话恢复用 Codex 的对应机制，文件约定完全不变。
