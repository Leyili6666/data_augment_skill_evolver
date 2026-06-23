# 产物契约

字段名使用稳定英文；面向用户的说明和值可以使用中文。

## 运行目录

```text
.data-augmentation/runs/<run-id>/
├── manifest.json
├── workflow_config.json
├── prd_analysis.json
├── prd_generation_reference.json
├── prd_extraction_report.json
├── generation_prompt.json
├── evaluation_prompt.json
├── generated.jsonl
├── generation_report.json
├── eval_report.json
├── eval_bad_cases.json
├── human_feedback.json
├── proposal.json
├── candidate-skill/
├── audit_report.json
└── candidate.diff
```

只有提供 PRD 或需求文档时，才创建 PRD 提取产物。`human_feedback.json`、`proposal.json`、
`candidate-skill/`、`audit_report.json` 和 `candidate.diff` 仅属于 `evolve` 模式，在
`generate_evaluate` 模式下不得创建。

## manifest.json

```json
{
  "run_id": "20260611-153000-domain",
  "query": "user request",
  "domain": "domain-slug",
  "workflow_mode": "generate_evaluate | evolve",
  "generation_mode": "generate | generalize | generalize_by_record | prd_mvp_multiturn",
  "iteration": 1,
  "max_iterations": 3,
  "workflow_config": "workflow_config.json",
  "status": "drafting_prompts",
  "task_spec": {},
  "data_contract": {},
  "approved_project_skill": null,
  "parent_run": null
}
```

允许的状态流转：

`generate_evaluate`：

`drafting_prompts` → `awaiting_prd_approval` → `generated` → `evaluated` → `completed`。

如果没有 PRD，可跳过 `awaiting_prd_approval`。

`evolve`：

`drafting_prompts` → `awaiting_prd_approval` → `generated` → `evaluated` →
`awaiting_feedback` → `proposed` → `candidate_built` → `awaiting_promotion` →
`validating` → `accepted`。

如果没有 PRD，可跳过 `awaiting_prd_approval`。

创建 manifest 前必须校验 `workflow_config.json`。见
[`workflow-configuration.md`](workflow-configuration.md)。工作流配置是目标生成条数、迭代次数、
角色模型、评委、仲裁、Provider 和 API Key 环境变量名的唯一来源。不得持久化原始 API Key。

## PRD 提取产物

- `prd_analysis.json`：完整语义提取结果，包含每个功能需求、来源引用、预期行为、约束、边界情况
  和相关话术；仅 PRD 输入时还必须包含完整 MVP 流程。
- `prd_generation_reference.json`：经过校验的紧凑生成参考，会注入生成提示词。
- `prd_extraction_report.json`：需求数量、话术数量、完整覆盖 ID、MVP 流程步骤和无话术需求列表。

每个功能需求必须包含稳定 `id`、`name`、`description`、`source_refs` 和 `utterances` 数组。
空 `utterances` 数组是合法的，不得因此丢弃需求。`prd_analysis.json` 还必须包含非空
`source_inventory` 和明确的 `unmapped_sections`，便于审计提取完整性。

PRD 提取完成后，必须展示摘要并获得用户确认。用户提出修订要求时，更新 `prd_analysis.json`，
重新运行 `scripts/build_prd_reference.py`，再次展示结果。用户未确认前，不得创建生成 Prompt 或
调用生成脚本。

仅提供 PRD、没有 seed 数据时，`prd_analysis.json` 和 `prd_generation_reference.json` 必须包含
`mvp_flow`：

```json
{
  "mvp_flow": [
    {
      "id": "MVP-001",
      "name": "用户发起任务",
      "description": "用户表达核心目标",
      "actor": "user",
      "user_goal": "完成某个 MVP 任务",
      "system_behavior": "识别意图并进入下一步",
      "user_utterance_patterns": [],
      "assistant_response_requirements": [],
      "required_requirements": ["FR-001"],
      "branching": [],
      "edge_cases": [],
      "source_refs": [{"file": "prd.md", "section": "流程"}]
    }
  ]
}
```

后续生成必须按 `mvp_flow` 生成多轮对话样本，并在评估中检查流程覆盖。

## data_contract

默认 ChatML 契约：

```json
{
  "type": "object",
  "format": "chatml",
  "required_fields": ["messages"]
}
```

自定义记录可设置 `type` 和 `required_fields`；更深层结构要求写入 Prompt。

## generation_prompt.json

注意：`manifest.json` / Task Spec 可以使用 `generation_mode: "prd_mvp_multiturn"` 表达“仅 PRD 输入、
按 MVP 流程生成多轮对话”的任务意图；但 `generation_prompt.json` 中传给脚本的
`generation_mode` 仍使用 `"generate"`。MVP 多轮要求通过 `prd_generation_reference.json` 的
`mvp_flow` 和提示词约束实现。

默认批量生成：

```json
{
  "generation_mode": "generate",
  "system_prompt": "generation rules",
  "user_template": "{count} {batch_index} {generated_count} {generation_references}",
  "reference_files": ["prd_generation_reference.json"],
  "count": 10,
  "batch_size": 10,
  "model": {"provider": "openai", "model": "model-name", "api_key_env": "OPENAI_API_KEY"},
  "data_contract": {}
}
```

基于已有数据逐条泛化：

```json
{
  "generation_mode": "generalize_by_record",
  "source_data_file": "seed.jsonl",
  "variants_per_record": 2,
  "user_template": "{source_index}/{source_total} {source_record} {variants_per_record} {generation_references}",
  "reference_files": [],
  "model": {"provider": "openai", "model": "model-name", "api_key_env": "OPENAI_API_KEY"},
  "data_contract": {}
}
```

`source_data_file` 可以是 JSONL、JSON 数组、`{"examples": [...]}`、`{"records": [...]}` 或单个
JSON 对象。生成脚本会逐条通过 `{source_record}` 插入源记录，并在 `generation_report.json` 中记录
按源记录统计的生成数量。生成结果仍必须匹配 `data_contract`；除非契约允许，否则不要额外添加来源
字段。

## human_feedback.json

```json
{
  "batch": "generated.jsonl",
  "items": [
    {"index": 0, "verdict": "accept | revise | reject", "comment": ""}
  ],
  "overall_direction": "",
  "new_constraints": [],
  "promotion_preferences": []
}
```

只记录用户实际提供的反馈。未知字段保持为空。

## evaluation_prompt.json

配置独立评委模型和可选仲裁模型：

```json
{
  "system_prompt": "shared independent judge rubric",
  "user_template": "{task_desc} {data_contract} {reference} {example}",
  "dimensions": ["naturalness", "relevance", "format", "diversity"],
  "judges": [
    {"name": "judge-a", "provider": "openai", "model": "model-a", "api_key_env": "OPENAI_API_KEY"},
    {"name": "judge-b", "provider": "gemini", "model": "model-b", "api_key_env": "GEMINI_API_KEY"}
  ],
  "arbitrator": {
    "name": "arbitrator",
    "provider": "openai",
    "model": "model-c",
    "api_key_env": "OPENAI_API_KEY"
  },
  "arbitration_user_template": "{task_desc} {data_contract} {example} {format_validation} {judge_results}",
  "data_contract": {}
}
```

每个评委独立评估。仲裁模型可以读取全部评委结果和确定性格式校验。没有仲裁或仲裁失败时，脚本
记录中位数共识。

评估必须覆盖完整生成数据。`scripts/evaluate_data.py` 默认评估全部有效记录；只有用户明确要求抽样
时才允许使用 `--sample <n>`。评估 prompt 的维度可以先询问用户关注点，再标准化成稳定英文维度名。
每个维度必须是 1-5 分，脚本会计算逐条 `overall` 和汇总均分。

## eval_bad_cases.json

评估脚本必须在 `eval_report.json` 中内嵌完整 `bad_case_report`，同时额外写出同内容的坏数据报告，
默认文件名为 `eval_bad_cases.json`：

```json
{
  "input": "generated.jsonl",
  "low_score_threshold": 3.0,
  "counts": {
    "parse_errors": 0,
    "bad_cases": 1,
    "format_invalid": 0,
    "low_score": 1
  },
  "parse_errors": [],
  "bad_cases": [
    {
      "index": 0,
      "reason": "low_score | format_invalid",
      "record": {},
      "format_errors": [],
      "scores": {},
      "judge_results": [],
      "arbitration": {},
      "human_review": {
        "verdict": "",
        "notes": "",
        "corrective_action": ""
      }
    }
  ]
}
```

`eval_report.json` 中的 `bad_case_report` 必须直接包含完整 `bad_cases` 数组；`eval_bad_cases.json`
是同内容副本，用于人工核实和与完整报告对比，不代表自动删除数据。

## 推广规则

这些规则只适用于 `evolve` 模式。`generate_evaluate` 模式下，禁止创建 proposal、候选 Skill、
审计、diff 或修改任何 Skill。

- `proposal.json` 只是建议，不代表批准。
- 只有用户批准 proposal 后，才能构建候选项目 Skill。
- 只有用户批准 diff 和审计结果后，才能推广候选项目 Skill。Claude Code 可使用 `.claude/skills/`，
  Codex / OpenAI Agents 可使用 `.agents/skills/`，Cursor 等其他 Agent 使用用户指定的项目级
  Rules/Skills/Instructions 目录。
- 每条全局规则候选都必须单独明确批准。
- 不得把 API Key 复制到任何产物中。
