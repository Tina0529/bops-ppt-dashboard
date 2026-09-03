# 主题索引（_topics.md）

> 这是 Triage Agent 的路由表，也是知识库的目录。每个主题一行。
> Triage 读完事件正文后，按「描述 / 关键词」匹配，给出 slug 和置信度。

## 路由规则

- 命中 1 个主题 → 路由到该主题。
- 命中多个主题 → 选置信度最高的一个处理，其余 slug 写入该主题 `_progress.md` 的「最近事件」备注里。
- 命中 0 个，或最高置信度 < 0.5 → 路由到 `_unsorted`，等待人工归类。人归类后把该事件从 `topics/_unsorted/events/` 移到目标主题即可。
- `auto` 列列出 agent 可以直接执行的动作。不在列表内的动作，agent 只能写进 `_progress.md` 的「待确认」，不得自动执行。
- 新增主题：加一行，并建 `topics/<slug>/_progress.md`（复制 `topics/_template_progress.md`）。

## 主题表

| slug | 主题 | 描述 / 关键词 | 负责人 | 状态 | auto |
|---|---|---|---|---|---|
| agent-lecture | Agent 讲座例会 | agent 架构, triage, topic agent, 讲座, 例会, 分享, knowledge base | me | active | 整理纪要, 汇总要点, 起草群消息草稿 |
| _unsorted | 未归类 | 无法路由的事件 | - | active | 无 |
