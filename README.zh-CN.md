# Data Augmentation Skill Evolver

简体中文 | [English](README.md)

一个面向多种 Agent 的数据增强 Skill 包，支持在 Codex、Claude Code、Cursor 以及其他可读取项目
规则、技能或说明文件的 Agent 中使用。它可以根据 query、PRD、规范文档、seed JSONL 或已有样本
生成、评估，并可选地自进化项目级数据增强能力。

它可以从 PRD 中提取完整功能需求和相关话术，把 PRD 作为生成参考；也可以把已有 JSONL 作为源数据，逐条插入提示词中做泛化增强。生成结果会经过确定性格式校验、多评委模型评估和可选仲裁。

## 核心能力

- 生成 JSONL 数据集。
- 支持纯生成评估模式：`generate_evaluate`。
- 支持自进化模式：`evolve`。
- 从 PRD 中提取功能需求、边界条件、限制和相关话术。
- 支持基于已有 JSONL 的逐条泛化：`generalize_by_record`。
- 使用结构化 `generation_prompt.json` 和 `evaluation_prompt.json`。
- 支持多评委模型评估与仲裁。
- 默认评估完整生成数据，并额外保存低分/问题数据报告供人工核实。
- 不把 API Key 写入任何产物。
- 项目 Skill 和全局规则必须用户明确确认后才会推广。

## 两种工作模式

### `generate_evaluate`

只生成并评估数据，不做自进化。

流程：

1. 解析用户 query、PRD、seed 数据和数据格式。
2. 生成 `generation_prompt.json` 和 `evaluation_prompt.json`。
3. 生成数据。
4. 做确定性校验和 LLM 评估。
5. 展示生成结果、评委结果、分歧和仲裁结论。
6. 结束，不生成 proposal，不修改任何 Skill。

### `evolve`

用于根据模型评估和人工反馈持续改进项目级数据增强 Skill。

在生成评估基础上增加：

1. 标准化人工反馈。
2. 生成 `edit` / `create` / `noop` proposal。
3. 构建候选项目 Skill 并做独立审计。
4. 用户确认后才推广。
5. 推广后重新生成一批新数据做验证。

## 安装

把本仓库放到你的 Agent 支持的 Skills、Rules 或项目说明目录中即可。不同运行环境目录不同。

### Claude Code

```bash
mkdir -p ~/.claude/skills
ln -s /path/to/data_augment_skill_evolver ~/.claude/skills/data-augmentation-skill-evolver
```

然后重启 Claude Code 或清空会话，让 Skill 列表刷新。

### Codex

```bash
mkdir -p ~/.agents/skills
ln -s /path/to/data_augment_skill_evolver ~/.agents/skills/data-augmentation-skill-evolver
```

### Cursor 和其他 Agent

Cursor、Continue、Windsurf 或其他 Agent 可以把本仓库放到项目级规则、技能或说明目录中。如果该
Agent 不直接识别 `SKILL.md`，就在它的规则文件中引用本仓库的 `SKILL.md`，并确保 `references/`、
`resources/` 和 `scripts/` 与之一起可访问。

## 推荐使用方式

### PRD + JSONL 逐条泛化增强

这是最常用的方式：PRD 提供需求范围，JSONL 提供已有样本格式和语义锚点。

```text
/data-augmentation-skill-evolver

使用 generate_evaluate 模式，不做自进化，不修改任何 skill。

PRD 文件：/path/to/prd.md
源数据 JSONL：/path/to/seed.jsonl

请先解析 PRD 并展示解析结果摘要，包括功能需求、相关话术、边界情况、约束、不支持范围和开放问题。
在我确认 PRD 解析结果之前，不要编写生成提示词，也不要开始数据增强。
如果我对 PRD 解析提出补充或修改要求，请先按要求重新解析并再次展示，直到我确认。

生成方式：generalize_by_record。
目标生成条数：100。
输出文件：generated.jsonl。

对 JSONL 中的源数据逐条泛化。每次只把一条源数据插入提示词，围绕这条数据生成泛化变体。
必须保留原始数据的意图、标签语义、JSON 字段结构和输出格式。
可以改变用户表达、场景、槽位值、上下文、难度或边界条件。
禁止复制原句，禁止只替换少量词。

PRD 作为需求参考。生成数据需要覆盖 PRD 中提取出的功能需求、相关话术、边界情况、约束和不支持范围。

对 generated.jsonl 进行确定性校验、多评委模型评估和仲裁。
评估维度包括格式正确性、PRD 覆盖度、相关性、多样性、标签/意图是否漂移、是否过度复制 seed 数据。
```

### 只根据 PRD 生成并评估

```text
/data-augmentation-skill-evolver

使用 generate_evaluate 模式，不做自进化，不修改任何 skill。

PRD 文件：/path/to/prd.md
生成方式：prd_mvp_multiturn。
目标生成条数：100。
输出文件：generated.jsonl。

请从 PRD 中提取所有功能需求、相关话术、边界情况和限制，并额外解析完整 MVP 流程。
MVP 流程需要覆盖用户发起任务、必要澄清、系统/助手执行、异常处理和完成反馈。
先展示 PRD 解析结果和 MVP 流程，得到我确认后，再按 MVP 流程生成多轮对话数据。

每条生成样本都应是完整多轮对话，覆盖一个完整 MVP 主流程或合理分支。
生成后进行确定性校验、多评委模型评估和仲裁，重点评估 MVP 流程覆盖度、PRD 覆盖度和多轮对话合理性。
```

### 自进化项目 Skill

```text
/data-augmentation-skill-evolver

使用 evolve 模式。

PRD 文件：/path/to/prd.md
源数据 JSONL：/path/to/seed.jsonl
生成方式：generalize_by_record。
目标生成条数：100。

先解析 PRD 并展示解析结果，得到我确认后再生成并评估数据，然后收集我的人工反馈。
根据反馈提出候选项目级数据增强 Skill，但未经我确认不得推广。
全局规则必须单独询问我确认。
```

## 运行开始时需要配置什么

Skill 会在最开始一次性询问完整配置，后续流程复用，不会每一步都重新问模型和 API：

- 工作模式：`generate_evaluate` 或 `evolve`
- 目标生成条数：`target_count`
- PRD Analyzer：当前会话或外部 API 模型
- Prompt Writer：当前会话或外部 API 模型
- 数据生成模型：provider、model、api_base、API Key 环境变量名
- 评委数量和每个评委模型配置
- 仲裁模型配置
- 你最关注的评估维度，例如 PRD 覆盖、MVP 流程覆盖、格式正确性、自然度、多样性、是否过度复制 seed
- 仅 `evolve` 模式需要：Proposer、Skill Builder、Auditor 配置

配置会写入：

```text
.data-augmentation/runs/<run-id>/workflow_config.json
```

并通过以下脚本校验：

```bash
python3 scripts/validate_workflow_config.py \
  --config .data-augmentation/runs/<run-id>/workflow_config.json \
  --check-env
```

## 主要流程和用到的文件

### 1. 解析 PRD

用到：

- `resources/prd-parsing.md`
- `references/prd-analysis-agent.md`
- `scripts/build_prd_reference.py`

产物：

- `prd_analysis.json`
- `prd_generation_reference.json`
- `prd_extraction_report.json`

`prd_generation_reference.json` 会作为生成提示词的参考资料，确保数据覆盖 PRD 的需求点和话术。
当只提供 PRD 时，解析结果还必须包含 `mvp_flow`，用于后续按完整 MVP 流程生成多轮对话。
PRD 解析完成后必须先展示摘要并等待用户确认；如果用户要求修订，先重新解析并重建
`prd_generation_reference.json`，再次确认后才进入下一步。

### 2. 编写 Prompt Spec

用到：

- `references/prompt-writer-agent.md`
- `resources/prompt-writing-patterns.md`
- `resources/augmentation-techniques.md`
- `resources/artifact-contracts.md`

产物：

- `generation_prompt.json`
- `evaluation_prompt.json`

逐条泛化时，`generation_prompt.json` 会包含：

```json
{
  "generation_mode": "generalize_by_record",
  "source_data_file": "/path/to/seed.jsonl",
  "variants_per_record": 2,
  "reference_files": ["prd_generation_reference.json"],
  "user_template": "... {source_record} ... {source_index} ... {source_total} ... {variants_per_record} ... {generation_references} ..."
}
```

### 3. 生成数据

用到：

- `scripts/generate_data.py`
- `scripts/llm_client.py`

示例：

```bash
python3 scripts/generate_data.py \
  --prompt-spec .data-augmentation/runs/<run-id>/generation_prompt.json \
  --output .data-augmentation/runs/<run-id>/generated.jsonl \
  --report .data-augmentation/runs/<run-id>/generation_report.json
```

### 4. 评估数据

用到：

- `references/evaluator-agent.md`
- `scripts/evaluate_data.py`
- `scripts/llm_client.py`

示例：

```bash
python3 scripts/evaluate_data.py \
  --input .data-augmentation/runs/<run-id>/generated.jsonl \
  --prompt-spec .data-augmentation/runs/<run-id>/evaluation_prompt.json \
  --output .data-augmentation/runs/<run-id>/eval_report.json \
  --bad-output .data-augmentation/runs/<run-id>/eval_bad_cases.json
```

评估默认覆盖完整生成数据。只有你明确要求抽样时，才会使用 `--sample <n>`。评估 Prompt 可以先根据
你的关注点定制维度，每个维度按 1-5 分打分，脚本会计算逐条 `overall` 和整体均分。

低分、格式错误和需要人工核实的数据会额外保存到 `eval_bad_cases.json`，其中包含原始记录、问题原因、
模型评分、仲裁结果和 `human_review` 人工复核占位字段，便于你核实后和完整评估报告对比。

## 运行产物

每次运行保存到：

```text
.data-augmentation/runs/<run-id>/
```

常见产物：

- `manifest.json`
- `workflow_config.json`
- `generation_prompt.json`
- `evaluation_prompt.json`
- `generated.jsonl`
- `generation_report.json`
- `eval_report.json`
- `eval_bad_cases.json`

PRD 相关产物：

- `prd_analysis.json`
- `prd_generation_reference.json`
- `prd_extraction_report.json`

仅自进化模式会产生：

- `human_feedback.json`
- `proposal.json`
- `candidate-skill/`
- `audit_report.json`
- `candidate.diff`

## 安全规则

- 不要把原始 API Key 写入任何配置、报告、prompt spec 或 manifest。
- 优先使用 `api_key_env`。
- `generate_evaluate` 模式不能创建 proposal、候选 Skill、审计或 diff。
- `evolve` 模式可以提出修改，但必须用户明确确认后才推广。
- 全局规则必须单独确认，不能因为项目 Skill 被确认就自动写入全局规则。

## 开发与验证

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

校验 Skill 结构：

```bash
python3 "$HOME/.claude/skills/skill-creator/scripts/quick_validate.py" .
```

检查 Python 语法：

```bash
python3 -m py_compile scripts/*.py tests/test_scripts.py
```
