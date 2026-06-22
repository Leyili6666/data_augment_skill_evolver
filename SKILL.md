---
name: data-augmentation-skill-evolver
description: 用于根据 query、PRD、规范、示例或 seed JSONL 生成、评估并可选自进化领域数据增强能力。支持纯生成评估、逐条泛化已有数据、多模型评估与仲裁、人工确认后的项目级 skill 更新，以及禁止未经确认推广全局规则。
---

# 数据增强 Skill Evolver

以可审阅、可追溯的方式生成数据。始终把生成数据、评估证据、人工反馈和 Skill 更新分开保存。
未经用户明确确认，不得推广候选项目 Skill，也不得写入全局规则。

## 核心角色

执行某个角色前，先阅读对应角色提示词：

| 角色 | 参考文件 | 职责 |
|---|---|---|
| PRD 需求提取智能体 | [`references/prd-analysis-agent.md`](references/prd-analysis-agent.md) | 提取所有功能需求、边界条件和相关话术 |
| 提示词撰写智能体 | [`references/prompt-writer-agent.md`](references/prompt-writer-agent.md) | 创建生成与评估 Prompt Spec |
| 评估智能体 | [`references/evaluator-agent.md`](references/evaluator-agent.md) | 结合确定性校验、多模型评委和仲裁 |
| 提议智能体 | [`references/proposer-agent.md`](references/proposer-agent.md) | 根据证据提出 `edit`、`create` 或 `noop` |
| 技能构建智能体 | [`references/skill-builder-agent.md`](references/skill-builder-agent.md) | 构建并审计候选项目 Skill |

创建运行产物前读取 [`resources/artifact-contracts.md`](resources/artifact-contracts.md)。
选择增强策略时读取 [`resources/augmentation-techniques.md`](resources/augmentation-techniques.md)。
有 PRD 或需求文档时读取 [`resources/prd-parsing.md`](resources/prd-parsing.md)。
编写生成或评估 Prompt Spec 前读取
[`resources/prompt-writing-patterns.md`](resources/prompt-writing-patterns.md)。

## 存储边界

目标项目中使用：

```text
.claude/skills/<domain>-data-augmentation/       # Claude Code 示例目录
.agents/skills/<domain>-data-augmentation/       # Codex / OpenAI Agents 示例目录
<agent-specific-skill-dir>/<domain>-data-augmentation/  # Cursor 等其他 Agent 的 Skill/Rules 目录
.data-augmentation/runs/<run-id>/                # 运行证据与候选产物
```

自动识别当前 Agent/CLI 环境，并只选择一个可部署项目 Skill 目录。Claude Code 常用
`.claude/skills/`，Codex / OpenAI Agents 常用 `.agents/skills/`。Cursor、Continue、Windsurf 或
其他 Agent 使用其项目级 Rules/Skills/Instructions 目录；无法判断当前环境时询问用户目标目录。

`manifest.json`、Prompt Spec、生成 JSONL、评估报告、人工反馈、proposal、候选 Skill、审计报告
和 diff 都保存到 run 目录。任何产物中都不得写入 API Key。未批准的候选内容只能留在 run 目录。

项目知识属于目标项目的领域 Skill。跨领域规则只有在用户单独确认后，才能写入当前 Skill 的
[`resources/global-rules.md`](resources/global-rules.md)。

## 工作模式

先询问工作模式：

- `generate_evaluate`：提取需求、生成数据、评估数据、展示结果，然后停止。不得提议、构建、
  审计、推广或修改任何 Skill。
- `evolve`：执行完整的“生成 → 评估 → 人工反馈 → 提议 → 构建候选 Skill → 审计 → 用户确认推广”
  闭环。

如果用户只是要求生成、增强或评估数据，默认使用 `generate_evaluate`。只有用户明确要求改进、
自进化或创建可复用项目 Skill 时，才使用 `evolve`。默认目标生成条数为 10；`evolve` 模式默认
最多 3 轮。

### 0. 一次性配置完整流程

在解析任务或创建任何产物前，一次性询问完整配置：

1. 工作模式：`generate_evaluate` 或 `evolve`。
2. 目标生成条数；仅 `evolve` 模式需要最大迭代轮数。
3. PRD 需求提取模型。
4. 提示词撰写模型。
5. 数据生成模型和 API 配置。
6. 独立评委模型数量，以及每个评委的模型和 API 配置。
7. 仲裁模型和 API 配置。
8. 仅 `evolve` 模式：提议模型、技能构建模型和独立审计模型。

PRD 需求提取、提示词撰写和自进化角色可以由当前 Agent 会话执行，也可以使用外部 API 模型。
数据生成、评委和仲裁必须使用 API，因为脚本会直接调用它们。建议至少配置 2 个不同模型身份的独立
评委。

外部模型需要收集 `provider`、`model`、必要时的 `api_base`，以及 API Key 环境变量名或仅本会话
使用的 Key。不要把原始 API Key 写入磁盘。后续阶段必须复用 `workflow_config.json`，不要重复询问
模型或 API 信息，除非校验失败或用户主动要求修改。

读取 [`resources/workflow-configuration.md`](resources/workflow-configuration.md)，写入
`.data-augmentation/runs/<run-id>/workflow_config.json`，然后校验：

```bash
python3 <skill-dir>/scripts/validate_workflow_config.py \
  --config <run-dir>/workflow_config.json \
  --check-env
```

配置校验成功后才能继续。若用户明确选择仅确定性评估，可以不配置评委和仲裁。

非脚本角色如果配置为 `execution: api`，使用：

```bash
python3 <skill-dir>/scripts/run_role_agent.py \
  --workflow-config <run-dir>/workflow_config.json \
  --role <prd_analyzer|prompt_writer|proposer|skill_builder|auditor> \
  --system-prompt-file <skill-dir>/references/<role>-agent.md \
  --input-file <role-input-file> \
  --output <role-output-file>
```

如果配置为 `execution: current_session`，则由当前会话执行该角色。

### 1. 理解任务与解析 PRD

在提问前，优先从用户提供的文件、PRD 和 seed 数据中推断信息。生成 Task Spec：

```yaml
task: 单句任务目标
domain: 稳定领域标识
mode: generate | generalize | generalize_by_record | prd_mvp_multiturn
input_space: 典型输入范围、风格和格式
output_space: 期望输出结构和响应行为
subtasks: 覆盖类别
edge_cases: 负例、歧义和边界情况
out_of_scope: 禁止或无关内容
data_contract: JSON 记录契约
```

如果有 seed 数据，分析字段、角色、长度、重复模式和覆盖缺口。示例比纯文字需求更可靠。
如果用户希望“基于已有数据逐条泛化”，设置 `mode: generalize_by_record`：每条源记录独立插入
提示词，并围绕该源记录生成变体。

如果用户只提供 PRD、没有提供 seed JSONL，设置 `mode: prd_mvp_multiturn`。此时 PRD 解析必须额外
抽取完整 MVP 流程，后续生成必须围绕该流程生成多轮对话数据，而不是只生成孤立单轮样本。

如果存在 PRD 或需求文档，执行 PRD 需求提取智能体，创建：

- `prd_analysis.json`：完整功能需求、来源引用、预期行为和相关话术。
- `prd_generation_reference.json`：用于生成阶段的紧凑参考。
- `prd_extraction_report.json`：需求数量、话术数量、覆盖统计和无话术需求列表。

运行：

```bash
python3 <skill-dir>/scripts/build_prd_reference.py \
  --input <run-dir>/prd_analysis.json \
  --output <run-dir>/prd_generation_reference.json \
  --report <run-dir>/prd_extraction_report.json
```

每个需求必须有稳定 ID 和来源引用。没有示例话术的需求也必须保留，`utterances` 设为空数组。

### 2. 展示并确认 PRD 解析结果

只要本轮使用了 PRD 或需求文档，就必须在数据增强前向用户展示解析结果摘要，并等待用户确认。
不得在用户确认前进入 Prompt 编写或数据生成。

展示内容至少包括：

- 任务目标、领域和数据契约摘要。
- 已审阅的源文件和章节。
- 功能需求总数、需求 ID、名称、优先级和来源位置。
- 仅 PRD 场景下的完整 MVP 流程：步骤 ID、步骤名、参与方、用户目标、系统行为、分支、边界情况和
  关联功能需求。
- 每个需求下提取到的相关话术数量和示例。
- 边界情况、约束、不支持范围和开放问题。
- `prd_extraction_report.json` 中的覆盖统计，尤其是无话术需求。
- 你将如何把 PRD 需求用于后续生成与评估。

询问用户是否批准该 PRD 解析结果用于数据增强：

- 如果用户确认，继续初始化 run 并编写 Prompt Spec。
- 如果用户提出补充、纠正、拆分、合并、忽略或重新分类需求的要求，必须先根据反馈更新
  `prd_analysis.json`，重新运行 `scripts/build_prd_reference.py`，再次展示修订结果并等待确认。
- 如果用户拒绝或解析结果仍不完整，不得生成数据。

### 3. 初始化运行

创建 `.data-augmentation/runs/<run-id>/manifest.json`。记录 `workflow_config.json` 引用，不写入
原始 API Key。将 iteration 设为 1，状态设为 `drafting_prompts`。

### 4. 编写 Prompt Spec

执行提示词撰写智能体。读取 [`resources/prompt-writing-patterns.md`](resources/prompt-writing-patterns.md)，
产出：

- `generation_prompt.json`：要求模型返回匹配数据契约的 `{"examples": [...]}`。包含 `{count}`、
  `{batch_index}`、`{generated_count}` 和 `{generation_references}`。如果有 PRD，将
  `prd_generation_reference.json` 加入 `reference_files`。
  对 `generalize_by_record`，还要设置 `generation_mode: "generalize_by_record"`、
  `source_data_file` 和 `variants_per_record`，并在 `user_template` 中包含 `{source_record}`、
  `{source_index}`、`{source_total}` 和 `{variants_per_record}`。
  对仅 PRD 输入的 `prd_mvp_multiturn`，设置 `generation_mode: "generate"`，但必须在提示词中要求
  模型按照 `prd_generation_reference.json` 的 `mvp_flow` 生成完整多轮对话。每条样本应覆盖一个
  完整或合理分支的 MVP 流程，包含用户发起、必要澄清、系统/助手执行、异常或完成反馈等轮次。
- `evaluation_prompt.json`：定义评估维度、rubric、任务上下文、数据契约、独立评委和可选仲裁。

约束组合顺序：已批准全局规则 → 已批准项目 Skill → 当前 Task Spec → 本轮反馈。不要把一次性偏好
变成持久规则。

保存 Prompt Spec 前，按 `resources/prompt-writing-patterns.md` 的质量清单检查占位符、结构化输出、
覆盖目标、失败模式约束和密钥泄露风险。

模型配置从 `workflow_config.json` 填充，不再询问。

### 5. 生成数据

运行：

```bash
python3 <skill-dir>/scripts/generate_data.py \
  --prompt-spec <run-dir>/generation_prompt.json \
  --output <run-dir>/generated.jsonl \
  --report <run-dir>/generation_report.json \
  --provider <provider> --api-base <base> --model <model> \
  --api-key-env <environment-variable>
```

自定义 Provider 使用 `--provider-module <path>`。部分失败后可用 `--resume`。优先使用环境变量提供
凭据；命令行 `--api-key` 仅作为运行时覆盖。使用最初配置中确认的数据生成模型。

逐条泛化时，在 Prompt Spec 中配置 `generation_mode: "generalize_by_record"` 和 `source_data_file`，
或通过 `--source-data <jsonl-or-json>` 指定源数据。脚本会逐条渲染 `{source_record}`，并为每条源记录
请求 `variants_per_record` 个输出。

### 6. 评估数据

即使没有模型凭据，也要先运行确定性校验：

```bash
python3 <skill-dir>/scripts/evaluate_data.py \
  --input <run-dir>/generated.jsonl \
  --prompt-spec <run-dir>/evaluation_prompt.json \
  --output <run-dir>/eval_report.json \
  --deterministic-only
```

移除 `--deterministic-only` 后，脚本会调用 `evaluation_prompt.json` 中的全部评委，再调用仲裁模型。
如果没有仲裁或仲裁失败，脚本会降级为各维度中位数共识。展示生成数据、评委分歧和最终仲裁。

`evolve` 模式下，询问用户逐条 `accept/revise/reject` 和整体方向，并规范化为
`human_feedback.json`。不得编造用户没有提供的反馈。`generate_evaluate` 模式下，展示结果后直接
完成，不收集用于技能进化的反馈。

### 7. 结束或进入提议

如果 `workflow_mode` 是 `generate_evaluate`，展示生成数据、确定性校验、评委结果、分歧和仲裁，
将状态设为 `completed` 并停止。不得：

- 请求用于 Skill 改进的反馈；
- 创建用于进化的 `human_feedback.json`；
- 创建 `proposal.json`、`candidate-skill/`、`audit_report.json` 或 `candidate.diff`；
- 写入 `.claude/skills/`、`.agents/skills/`、其他 Agent 的 Skill/Rules 目录或当前全局 Skill。

以下步骤只适用于 `evolve` 模式。

### 8. 提议

执行提议智能体，比较：

- 通过和失败样本；
- 模型评估与人工反馈；
- 现有项目 Skill 与已批准全局规则；
- 历史已接受和已拒绝 proposal。

写入 `proposal.json`，主动作只能是：

- `edit`：已有项目 Skill 本应避免该问题；
- `create`：没有现有 Skill 覆盖该可复用能力；
- `noop`：证据不足或问题孤立。

可能跨领域通用的内容放入 `global_rule_candidates`，它们不是已批准变更。优先局部编辑，保留已经
成功的行为。

### 9. 构建并审计候选 Skill

仅在用户批准 proposal 后，执行技能构建智能体，在以下目录创建候选：

```text
<run-dir>/candidate-skill/<domain>-data-augmentation/
```

遵循已安装的 `skill-creator`。运行其 `quick_validate.py`，测试新增脚本，并写入 `audit_report.json`
和相对于已批准项目 Skill 的可读 diff。审计硬编码样本、不可追溯规则、领域污染、缺失运行时发现、
脚本过大和关键步骤可被静默绕过等问题。

此阶段不得推广候选 Skill。

### 10. 确认并推广

展示候选 diff 和审计结果。只有用户明确批准后，才能推广到当前 Agent 的项目 Skill/Rules 目录。
Claude Code 可使用 `.claude/skills/<domain>-data-augmentation/`，Codex / OpenAI Agents 可使用
`.agents/skills/<domain>-data-augmentation/`；Cursor 等其他 Agent 使用用户指定的项目级规则或技能目录。

全局规则候选必须单独展示并单独确认。批准项目 Skill 不等于批准全局规则。

### 11. 新批次验证

使用推广后的项目 Skill 生成一批新的、不重叠的数据。不要复用用于证明变更的样本。重新评估、
收集反馈并迭代，直到用户接受或达到迭代上限。保留所有运行产物和 proposal 结论，供后续提议分析。

## Provider 接口

内置 Provider 为 `openai` 和 `gemini`；`auto` 会从 API base 推断。自定义 Python 模块必须暴露：

```python
def create_provider(config):
    return provider  # provider 需暴露 generate(messages, model, temperature, max_tokens, response_format)
```

脚本会在运行时把凭据放入 `config`，但绝不序列化保存。

## 完成标准

`generate_evaluate` 模式完成条件：

- 生成数据符合数据契约；
- 确定性校验没有未解释错误；
- 模型评估和最终仲裁已记录并展示；
- 未创建自进化产物，也未修改任何 Skill。

`evolve` 模式完成条件：

- 用户接受的数据批次符合数据契约；
- 确定性校验没有未解释错误；
- 评估和人工反馈已记录；
- 每个推广的 Skill 变更都有明确批准和干净审计；
- 全局规则中没有未经批准的项目专属知识。
