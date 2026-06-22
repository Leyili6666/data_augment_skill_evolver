# 工作流配置

在任务解析、PRD 提取、数据生成或评估之前，一次性收集工作模式和完整模型/API 计划。配置确认后，
整个 run 都复用它，不要在每一步重复询问。

## 模式

- `generate_evaluate`：只执行 PRD 提取、提示词撰写、数据生成和评估。不得配置或调用 Proposer、
  Skill Builder、Auditor。
- `evolve`：执行完整自进化流程。

## 初始询问

询问用户：

1. 工作模式和目标生成条数；最大自进化迭代轮数仅 `evolve` 需要。
2. PRD Analyzer：当前会话或外部 API 模型。
3. Prompt Writer：当前会话或外部 API 模型。
4. Generator：provider、model、必要时的 API base、API Key 环境变量名。
5. 评委数量，以及每个独立评委的 API 配置。
6. 仲裁模型：provider、model、必要时的 API base、API Key 环境变量名。
7. 仅 `evolve`：Proposer，当前会话或外部 API 模型。
8. 仅 `evolve`：Skill Builder 和独立 Auditor，当前会话或外部 API 模型。

建议至少使用两个不同 provider/model 身份的评委，并让仲裁模型尽量不同于评委。说明原始 API Key
可以只在当前会话中提供，但不会写入产物；更推荐环境变量。

可使用这个紧凑询问：

```text
开始前请一次性确认完整流程配置：
1. 流程模式：仅生成评估 / 自进化；目标生成条数；仅自进化模式需要最大迭代轮数
2. PRD 需求提取模型：当前会话 / 外部 API
3. 提示词撰写模型：当前会话 / 外部 API
4. 数据生成模型：provider、model、api_base、API Key 环境变量名
5. 评委数量，以及每个评委的 provider、model、api_base、API Key 环境变量名
6. 仲裁模型：provider、model、api_base、API Key 环境变量名
7. 仅自进化模式：提议模型
8. 仅自进化模式：技能构建模型与独立审计模型
```

## workflow_config.json

```json
{
  "workflow_mode": "evolve",
  "target_count": 10,
  "max_iterations": 3,
  "roles": {
    "prd_analyzer": {"execution": "current_session"},
    "prompt_writer": {"execution": "current_session"},
    "generator": {
      "execution": "api",
      "provider": "openai",
      "model": "model-generation",
      "api_base": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY"
    },
    "evaluator": {
      "judge_count": 2,
      "judges": [
        {
          "name": "judge-a",
          "execution": "api",
          "provider": "openai",
          "model": "model-a",
          "api_key_env": "OPENAI_API_KEY"
        },
        {
          "name": "judge-b",
          "execution": "api",
          "provider": "gemini",
          "model": "model-b",
          "api_key_env": "GEMINI_API_KEY"
        }
      ],
      "arbitrator": {
        "execution": "api",
        "provider": "openai",
        "model": "model-c",
        "api_key_env": "OPENAI_API_KEY"
      }
    },
    "proposer": {"execution": "current_session"},
    "skill_builder": {"execution": "current_session"},
    "auditor": {"execution": "current_session"}
  }
}
```

最小 `generate_evaluate` 配置不包含 `max_iterations`、`proposer`、`skill_builder` 和 `auditor`：

```json
{
  "workflow_mode": "generate_evaluate",
  "target_count": 100,
  "roles": {
    "prd_analyzer": {"execution": "current_session"},
    "prompt_writer": {"execution": "current_session"},
    "generator": {"execution": "api", "provider": "openai", "model": "model-generation", "api_key_env": "OPENAI_API_KEY"},
    "evaluator": {
      "judge_count": 2,
      "judges": [
        {"name": "judge-a", "execution": "api", "provider": "openai", "model": "model-a", "api_key_env": "OPENAI_API_KEY"},
        {"name": "judge-b", "execution": "api", "provider": "gemini", "model": "model-b", "api_key_env": "GEMINI_API_KEY"}
      ],
      "arbitrator": {"execution": "api", "provider": "openai", "model": "model-c", "api_key_env": "OPENAI_API_KEY"}
    }
  }
}
```

`execution` 只能是 `current_session` 或 `api`。Generator 和评委必须使用 `api`。除非用户明确选择
仅确定性评估，否则仲裁也必须使用 `api`。

外部 PRD Analyzer、Prompt Writer、Proposer、Skill Builder 和 Auditor 可通过
`scripts/run_role_agent.py` 调用。当前元 Skill 负责决定何时调用每个角色；该脚本只执行一次配置好的
角色调用，不是完整自动编排器。

## PRD 确认规则

当输入包含 PRD 或需求文档时，PRD 提取完成后必须展示解析结果，等待用户确认。用户确认前：

- 不得创建 `generation_prompt.json`；
- 不得调用 `scripts/generate_data.py`；
- 不得把 PRD 解析结果当作已批准事实。

如果用户要求补充、纠正、拆分、合并、忽略或重新分类需求，必须修订 `prd_analysis.json`，重新运行
`scripts/build_prd_reference.py`，再次展示结果并等待确认。

## 安全规则

- 不要在 `workflow_config.json`、manifest、Prompt Spec、报告或日志中写入 `api_key`。
- 优先使用 `api_key_env`；开始前校验每个环境变量是否存在。
- 多个角色共享凭据时，可复用同一个环境变量名。
- 只有配置缺失、无效、不可用或用户明确要求修改时，才再次询问。
