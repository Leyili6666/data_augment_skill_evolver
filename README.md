# Data Augmentation Skill Evolver

[简体中文](README.zh-CN.md) | English

An agent-agnostic skill package for generating, evaluating, and optionally evolving
domain-specific data augmentation workflows. It can be used from Codex, Claude Code, Cursor, or
other agent runtimes that can load project instructions, skills, or rules.

It supports small-batch synthetic data generation from a query, PRD, specification, seed JSONL, or
existing examples. Generated data is validated deterministically, judged by one or more LLMs, and
optionally used to improve a project-level data augmentation skill after explicit user approval.

## What It Does

- Generates JSONL datasets for domain data augmentation.
- Supports pure `generate_evaluate` mode without self-evolution.
- Supports `evolve` mode for feedback-driven project skill updates.
- Extracts PRD functional requirements and related utterances for generation reference.
- Uses structured prompt specs for generation and evaluation.
- Supports per-record generalization from existing data.
- Evaluates generated records with deterministic checks, multiple judge models, and optional
  arbitration.
- Evaluates the complete generated dataset by default, embeds bad cases in the main report, and
  also exports the same bad-case report for human review.
- Keeps API keys out of persisted artifacts.
- Requires explicit approval before writing project skills or global rules.

## Workflow Modes

### `generate_evaluate`

Use this when you only want data generation and evaluation.

The workflow:

1. Parse the user query, PRD, seed data, and data contract.
2. Build generation and evaluation prompt specs.
3. Generate data.
4. Run deterministic validation and LLM evaluation.
5. Present generated data, judge results, disagreements, and arbitration.
6. Stop without creating proposals or modifying any skill.

### `evolve`

Use this when you want the skill to improve a reusable project-level data augmentation skill from
human feedback.

The workflow adds:

1. Human feedback normalization.
2. Proposal generation: `edit`, `create`, or `noop`.
3. Candidate skill construction and independent audit.
4. User-approved promotion only.
5. Fresh validation batch after promotion.

Project skills and global rules are never promoted automatically.

## Repository Layout

```text
.
├── SKILL.md                         # Main skill instructions
├── agents/openai.yaml               # UI metadata
├── references/                      # Role prompts
│   ├── prd-analysis-agent.md
│   ├── prompt-writer-agent.md
│   ├── evaluator-agent.md
│   ├── proposer-agent.md
│   └── skill-builder-agent.md
├── resources/                       # Contracts and workflow references
│   ├── artifact-contracts.md
│   ├── workflow-configuration.md
│   ├── augmentation-techniques.md
│   ├── prompt-writing-patterns.md
│   ├── prd-parsing.md
│   └── global-rules.md
├── scripts/
│   ├── generate_data.py             # Generate JSONL data from prompt specs
│   ├── evaluate_data.py             # Validate and evaluate generated data
│   ├── llm_client.py                # Provider abstraction
│   ├── run_role_agent.py            # API-backed role invocation
│   ├── build_prd_reference.py       # Compact PRD reference builder
│   ├── validate_workflow_config.py  # Initial config validation
│   └── llm_eval.py                  # Backward-compatible evaluation entrypoint
└── tests/
    └── test_scripts.py
```

## Installation

Install this repository wherever your agent expects reusable skills, rules, or project
instructions. The exact directory depends on the runtime.

### Claude Code

Place or symlink this repository into Claude's skills directory:

```bash
mkdir -p ~/.claude/skills
ln -s /path/to/data_augment_skill_evolver ~/.claude/skills/data-augmentation-skill-evolver
```

Restart Claude Code or clear the session so the skill list refreshes.

### Codex

Place or symlink this repository into Codex's skills directory:

```bash
mkdir -p ~/.agents/skills
ln -s /path/to/data_augment_skill_evolver ~/.agents/skills/data-augmentation-skill-evolver
```

### Cursor And Other Agents

For Cursor, Continue, Windsurf, or other agent tools, place or symlink this repository into the
project-level directory that the agent reads for rules, skills, or reusable instructions. If the
agent does not support `SKILL.md` directly, reference this repository's `SKILL.md` from the
agent's rule file and keep `references/`, `resources/`, and `scripts/` available beside it.

## Quick Start In Your Agent

Pure generation plus evaluation:

```text
/data-augmentation-skill-evolver

Use generate_evaluate mode. Generate and evaluate 50 examples for this domain.
Use my PRD and seed JSONL as references. Do not modify any skill.
```

Self-evolution workflow:

```text
/data-augmentation-skill-evolver

Use evolve mode. Generate a batch, evaluate it, collect my feedback, and propose a
candidate project data augmentation skill. Do not promote changes without my confirmation.
```

Per-record generalization:

```text
/data-augmentation-skill-evolver

Use generate_evaluate mode. Use seed.jsonl as source data. For each source record, generate
2 generalized variants while preserving intent, label semantics, and JSON structure.
```

PRD plus JSONL per-record augmentation:

```text
/data-augmentation-skill-evolver

Use generate_evaluate mode. Do not perform self-evolution and do not modify any skill.

PRD file: /path/to/prd.md
Source JSONL: /path/to/seed.jsonl

First parse the PRD and show me a summary of the extracted functional requirements, related
utterances, edge cases, constraints, out-of-scope rules, and open questions. Do not write
generation prompts or augment data until I approve the PRD analysis. If I request changes to the
PRD analysis, revise it and show the updated result again before continuing.

Generation mode: generalize_by_record.
Target count: 100.
Output file: generated.jsonl.

For each source record, generate generalized variants one record at a time. Preserve the original
intent, label semantics, JSON fields, and output format. Vary wording, scenario, slot values,
context, difficulty, or boundary conditions. Do not copy the original text or only replace a few
words.

Use the PRD as the requirement reference. The generated data should cover the functional
requirements, related utterances, edge cases, constraints, and out-of-scope rules extracted from
the PRD.

Evaluate generated.jsonl with deterministic validation, multiple judge models, and arbitration.
Judge format correctness, PRD coverage, relevance, diversity, label/intent drift, and over-copying
from seed data.
```

PRD-only MVP multi-turn generation:

```text
/data-augmentation-skill-evolver

Use generate_evaluate mode. Do not perform self-evolution and do not modify any skill.

PRD file: /path/to/prd.md
Generation mode: prd_mvp_multiturn.
Target count: 100.
Output file: generated.jsonl.

Extract all functional requirements, related utterances, edge cases, constraints, and out-of-scope
rules from the PRD. Also extract the complete MVP flow: user initiation, required clarification,
assistant/system execution, exception handling, and completion feedback.

Show me the PRD analysis and MVP flow first. Do not write generation prompts or generate data until
I approve them. If I request changes, revise the PRD analysis and show it again.

After approval, generate multi-turn dialogue records. Each record should cover a complete MVP main
flow or a reasonable branch, not an isolated single-turn requirement. Evaluate MVP flow coverage,
PRD coverage, format correctness, relevance, and dialogue coherence.
```

At the beginning of a run, the skill asks for the full workflow configuration: generation model,
judge models, arbitrator model, API provider details, and whether helper roles run in the current
session or through an API. It can also ask which evaluation dimensions matter most to you, then
turn those priorities into scored 1-5 rubric dimensions.

When a PRD is provided, the skill must show the PRD analysis and wait for user approval before
writing generation prompts or generating data.

## Model Providers

Built-in providers:

- OpenAI-compatible APIs
- Gemini
- Custom Python provider modules

Provider settings are stored by public reference only:

```json
{
  "provider": "openai",
  "model": "model-name",
  "api_base": "https://api.openai.com/v1",
  "api_key_env": "OPENAI_API_KEY"
}
```

Raw API keys should be supplied through environment variables. Command-line API keys are supported
only as runtime overrides and are not written to artifacts.

## Script Usage

### Generate Data

```bash
python3 scripts/generate_data.py \
  --prompt-spec .data-augmentation/runs/<run-id>/generation_prompt.json \
  --output .data-augmentation/runs/<run-id>/generated.jsonl \
  --report .data-augmentation/runs/<run-id>/generation_report.json \
  --provider openai \
  --model model-name \
  --api-key-env OPENAI_API_KEY
```

### Per-Record Generalization

In `generation_prompt.json`:

```json
{
  "generation_mode": "generalize_by_record",
  "source_data_file": "seed.jsonl",
  "variants_per_record": 2,
  "user_template": "Generate {variants_per_record} variants for source {source_index}/{source_total}: {source_record}",
  "model": {
    "provider": "openai",
    "model": "model-name",
    "api_key_env": "OPENAI_API_KEY"
  }
}
```

Run:

```bash
python3 scripts/generate_data.py \
  --prompt-spec generation_prompt.json \
  --output generated.jsonl \
  --report generation_report.json
```

`source_data_file` can be JSONL, a JSON array, `{"examples": [...]}`, `{"records": [...]}`, or a
single JSON object.

### Evaluate Data

Deterministic-only validation:

```bash
python3 scripts/evaluate_data.py \
  --input generated.jsonl \
  --prompt-spec evaluation_prompt.json \
  --output eval_report.json \
  --deterministic-only
```

LLM judge evaluation:

```bash
python3 scripts/evaluate_data.py \
  --input generated.jsonl \
  --prompt-spec evaluation_prompt.json \
  --output eval_report.json \
  --bad-output eval_bad_cases.json
```

The evaluator supports multiple judges and an optional arbitrator. If arbitration is absent or
fails, it falls back to median consensus. It evaluates all valid generated records by default; use
`--sample <n>` only when you explicitly want sampled evaluation.

Low-scoring records, format-invalid records, parse errors, judge results, arbitration, and blank
human-review fields are included in `eval_report.json` under `bad_case_report`. The same content is
also written to `eval_bad_cases.json` so you can manually verify problematic data while comparing
against the full evaluation report.

## Run Artifacts

Each run writes artifacts under:

```text
.data-augmentation/runs/<run-id>/
```

Common artifacts:

- `manifest.json`
- `workflow_config.json`
- `generation_prompt.json`
- `evaluation_prompt.json`
- `generated.jsonl`
- `generation_report.json`
- `eval_report.json`
- `eval_bad_cases.json`

PRD artifacts are created when a PRD or requirements document is provided:

- `prd_analysis.json`
- `prd_generation_reference.json`
- `prd_extraction_report.json`

Evolution-only artifacts:

- `human_feedback.json`
- `proposal.json`
- `candidate-skill/`
- `audit_report.json`
- `candidate.diff`

## Security And Promotion Rules

- Do not write raw API keys to config, reports, prompt specs, or manifests.
- Prefer `api_key_env` for every provider.
- `generate_evaluate` mode must not create proposals, candidate skills, audits, or diffs.
- `evolve` mode may propose changes, but promotion requires explicit user approval.
- Global rules require separate explicit approval from project-specific skill changes.

## Development

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Validate skill structure:

```bash
python3 "$HOME/.claude/skills/skill-creator/scripts/quick_validate.py" .
```

Check Python syntax:

```bash
python3 -m py_compile scripts/*.py tests/test_scripts.py
```

## License

Add a license before publishing if this repository will be shared publicly.
