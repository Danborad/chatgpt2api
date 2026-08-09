# 文档治理规则

## 文档所有权

同一事实只能有一个权威文档，其他位置使用链接，不复制维护第二份正文：

| 内容 | 权威位置 |
| --- | --- |
| AI 开发入口、规则路由、永久约束 | `AGENTS.md` |
| 可执行的开发与发布规则 | `.codex/rules/` |
| 领域术语、关系和所有权 | `CONTEXT.md` |
| 已接受且需要长期保留的架构决策 | `docs/adr/` |
| 尚未完成的需求意图与验收标准 | `docs/requirements/` |
| 当前代码结构和关键调用路径 | `docs/maps/` |
| 可重复执行的部署、恢复和运维步骤 | `docs/runbooks/` |
| 上游项目和工具的借鉴边界 | `docs/references/` |
| 当前专题文档和中央索引 | `docs/README.md` |
| 用户可感知的版本变化 | `CHANGELOG.md` |

发生冲突时按 `.codex/rules/architecture.md` 的事实来源顺序判断。PRD、旧提交信息、外部项目和 CodeGraph 输出都不是当前实现的事实来源。

## 文档语言

按文档用途确定主要语言，不要求整个仓库只使用一种语言：

| 文档范围 | 默认语言 |
| --- | --- |
| `README.md`、`CHANGELOG.md`、部署说明、运维步骤和面向使用者的说明 | 中文 |
| `README_EN.md` 等明确标记的英文用户文档 | 英文 |
| `AGENTS.md`、`.codex/rules/` 和面向当前维护者的执行规则 | 中文 |
| `CONTEXT.md`、`docs/adr/`、`docs/maps/`、`docs/requirements/`、`docs/references/` 以及架构、契约和性能专题文档 | 英文 |

- 同一份文档使用一种主要语言，不在相邻段落中无规则切换；代码标识、Interface 名称、状态值、命令和路径保留原始英文。
- 引用外部项目时保留其正式名称和原文标识，必要时在正文中补充当前文档主要语言的解释。
- 除 `README.md` 与 `README_EN.md` 等明确维护的对外入口外，不为同一事实维护中英文两份权威正文。
- 不仅为统一语言而批量翻译已有文档。修改现有文档时沿用其主要语言；确需转换语言时必须整份转换，并同步检查链接、术语和权威所有权。

## 文档变更触发条件

- 新增非简单功能、跨层行为或仍需确认的交互前，使用 `docs/requirements/_template.md` 建立 PRD；单一机械修改不强制建立 PRD。
- 改变领域术语、权威所有者、持久化边界、公开契约或跨 Module 生命周期时，必须同步检查 `CONTEXT.md`、accepted ADR 和 `docs/maps/`。需要推翻或补充长期架构决策时，先新增 ADR。
- 新增、删除或重命名路由、入口 Module、Repository、外部存储或关键流程时，必须在同一改动中更新对应 current map。
- 改变部署、升级、备份、恢复或故障处理步骤时，更新对应 runbook；一次性排查记录不能写成 runbook。
- 用户可感知行为改变时检查 `CHANGELOG.md`；只重排内部文档时不添加发布记录。
- 删除功能时，同一改动必须删除 current 文档中的对应描述，不能只追加“已废弃”造成双重事实。

## PRD 生命周期

PRD 文件名使用 `NNNN-short-name.md`，编号四位递增，状态只允许：

```text
draft -> approved -> implementing -> pending-verification -> implemented
   \-> rejected
```

- `draft`：问题、范围或所有权仍在讨论。
- `approved`：用户已确认范围、非目标和验收标准，但实现尚未开始。
- `implementing`：对应实现已经开始；只能描述意图和进行中的事实。
- `pending-verification`：实现和自动验证已结束，仍等待必要的可见行为验收或外部验证。
- `implemented`：验收标准已有证据，且需要的 current 文档和 CHANGELOG 已同步。
- `rejected`：明确决定不实现，并记录原因。

不得因代码存在、测试通过或 Agent 自查而跳过必要的用户验收。PRD 不能被用来证明功能已经实现。`implemented` 或 `rejected` 的 PRD 可以移入 `docs/requirements/archive/`，移动时同步更新索引和链接。

## 编写要求

- 每份文档开头标记 `Status: current`、PRD 生命周期状态或 ADR 状态。
- current 文档只写从当前代码、契约和测试验证过的事实；未知内容写明未知，不用旧计划补齐。
- PRD 必须写清问题、用户结果、范围、非目标、权威所有者、Interface、失败行为、验收标准和验证矩阵。
- 所有权不只包括持久化，还包括业务语义、状态转换、生命周期、并发、缓存、加载、选择、布局、焦点、浮层和滚动。每一项只能有一个权威所有者。
- 文档引用源码时使用仓库相对路径和稳定符号名；仅在精确定位缺陷时使用行号，避免普通说明因行号漂移失效。
- Mermaid 图只表达跨三个及以上 Module 的关系；简单映射使用表格。图、表和正文不得维护三份相同事实。
- 不提交生成报告、CodeGraph 数据库、临时测试记录、浏览器截图、真实账号数据或本机绝对路径。

## CodeGraph 使用边界

CodeGraph 用于发现符号、调用者、被调用者和潜在影响范围，不是架构真相。常用命令：

```powershell
codegraph status
codegraph query <symbol>
codegraph callers <symbol>
codegraph callees <symbol>
git diff --name-only | codegraph affected --stdin
```

查询结果必须回到当前源码、公开契约、测试、`CONTEXT.md` 和 accepted ADR 复核。`.codegraph/`、`.codegraph-*/` 及导出的图数据不得提交。

## 完成门禁

文档任务结束前必须检查：

1. 新增链接和仓库相对路径可解析。
2. 术语与 `CONTEXT.md` 一致，没有同义的第二套所有权。
3. PRD 状态没有超前于实现和验收证据。
4. current map 与当前路由、Module、Repository 和外部存储一致。
5. `git diff` 只包含授权范围，生成物和本机路径未进入工作区。
