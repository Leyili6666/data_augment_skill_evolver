#!/usr/bin/env python3
"""Deterministic and optional LLM evaluation for arbitrary JSONL datasets."""

import argparse
import json
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from generate_data import render_template, strip_code_fence
from llm_client import ProviderError, create_provider, public_model_config


DEFAULT_DIMENSIONS = ["naturalness", "relevance", "format", "diversity"]
DEFAULT_SYSTEM_PROMPT = """你是数据增强质量评估智能体。根据任务、数据契约和参考样本评估候选样本。
对 naturalness、relevance、format、diversity 分别给出 1-5 分，并提供 issues、highlight、
failure_tags。只输出 JSON 对象，不要输出其他文本。"""
DEFAULT_USER_TEMPLATE = """任务描述：
{task_desc}

数据契约：
{data_contract}

参考样本：
{reference}

候选样本：
{example}
"""
DEFAULT_ARBITRATION_SYSTEM_PROMPT = """你是数据增强评估仲裁智能体。综合多个独立评委的评分与理由、
确定性格式校验结果，对候选样本给出最终裁决。识别评委分歧，不盲从多数；格式校验错误优先。
对每个评估维度给出 1-5 分，并输出 issues、highlight、failure_tags、verdict、confidence、
disagreements。只输出 JSON 对象。"""
DEFAULT_ARBITRATION_USER_TEMPLATE = """任务描述：
{task_desc}

数据契约：
{data_contract}

候选样本：
{example}

确定性格式校验：
{format_validation}

独立评委结果：
{judge_results}
"""


def load_jsonl(path: Path) -> Tuple[List[Any], List[Dict[str, Any]]]:
    records, errors = [], []
    if not path.exists():
        return records, [{"line": None, "error": "file not found: {}".format(path)}]
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                errors.append({"line": number, "error": str(exc)})
    return records, errors


def validate_record(record: Any, contract: Dict[str, Any]) -> List[str]:
    errors = []
    expected_type = contract.get("type", "object")
    if expected_type == "object" and not isinstance(record, dict):
        return ["expected object"]
    if expected_type == "array" and not isinstance(record, list):
        return ["expected array"]
    if not isinstance(record, dict):
        return errors
    for field in contract.get("required_fields", []):
        if field not in record:
            errors.append("missing required field: {}".format(field))
    if contract.get("format") == "chatml":
        messages = record.get("messages")
        if not isinstance(messages, list) or not messages:
            errors.append("messages must be a non-empty array")
        else:
            for index, message in enumerate(messages):
                if not isinstance(message, dict):
                    errors.append("messages[{}] must be an object".format(index))
                elif "role" not in message or "content" not in message:
                    errors.append("messages[{}] requires role and content".format(index))
    return errors


def parse_score(text: str, dimensions: List[str]) -> Dict[str, Any]:
    value = json.loads(strip_code_fence(text))
    if not isinstance(value, dict):
        raise ValueError("evaluation response must be a JSON object")
    numeric = []
    for dimension in dimensions:
        score = value.get(dimension)
        if isinstance(score, (int, float)):
            numeric.append(float(score))
    value["overall"] = round(sum(numeric) / len(numeric), 2) if numeric else None
    value.setdefault("failure_tags", [])
    value.setdefault("issues", "")
    return value


def summarize(scores: List[Dict[str, Any]], dimensions: List[str]) -> Dict[str, Optional[float]]:
    result = {}
    for dimension in dimensions + ["overall"]:
        values = [item.get(dimension) for item in scores if isinstance(item.get(dimension), (int, float))]
        result[dimension] = round(sum(values) / len(values), 2) if values else None
    return result


def resolve_bad_output_path(output_path: Path, configured: str) -> Path:
    if configured:
        return Path(configured)
    return output_path.with_name(output_path.stem + "_bad_cases.json")


def build_bad_case_report(
    input_path: str,
    threshold: float,
    parse_errors: List[Dict[str, Any]],
    deterministic: List[Dict[str, Any]],
    input_records: List[Any],
    details: List[Dict[str, Any]],
) -> Dict[str, Any]:
    bad_cases = []
    for item in deterministic:
        if item["valid"]:
            continue
        index = item["index"]
        bad_cases.append({
            "index": index,
            "reason": "format_invalid",
            "record": input_records[index] if index < len(input_records) else None,
            "format_errors": item["errors"],
            "scores": None,
            "judge_results": [],
            "arbitration": None,
            "human_review": {
                "verdict": "",
                "notes": "",
                "corrective_action": "",
            },
        })
    for detail in details:
        scores = detail.get("scores")
        if not scores or scores.get("overall") is None or scores["overall"] >= threshold:
            continue
        bad_cases.append({
            "index": detail["index"],
            "reason": "low_score",
            "record": detail.get("example"),
            "format_errors": deterministic[detail["index"]]["errors"] if detail["index"] < len(deterministic) else [],
            "scores": scores,
            "judge_results": detail.get("judge_results", []),
            "arbitration": detail.get("arbitration"),
            "human_review": {
                "verdict": "",
                "notes": "",
                "corrective_action": "",
            },
        })
    bad_cases.sort(key=lambda item: (item["index"] if item["index"] is not None else -1, item["reason"]))
    report = {
        "input": input_path,
        "low_score_threshold": threshold,
        "counts": {
            "parse_errors": len(parse_errors),
            "bad_cases": len(bad_cases),
            "format_invalid": sum(1 for item in bad_cases if item["reason"] == "format_invalid"),
            "low_score": sum(1 for item in bad_cases if item["reason"] == "low_score"),
        },
        "parse_errors": parse_errors,
        "bad_cases": bad_cases,
    }
    return report


def write_bad_case_report(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_provider(model_config: Dict[str, Any], args: argparse.Namespace):
    return create_provider(
        model_config.get("provider", "auto"),
        api_base=model_config.get("api_base", ""),
        api_key=model_config.get("api_key", ""),
        api_key_env=model_config.get("api_key_env", ""),
        provider_module=model_config.get("provider_module", "") or args.provider_module,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )


def legacy_model_config(args: argparse.Namespace, spec: Dict[str, Any]) -> Dict[str, Any]:
    model_spec = spec.get("model", {})
    provider_name = args.provider or model_spec.get("provider", "")
    model = args.model or model_spec.get("model", "")
    if not (provider_name or args.provider_module or model):
        return {}
    return {
        "name": "judge-1",
        "provider": provider_name or "auto",
        "model": model,
        "api_base": args.api_base or model_spec.get("api_base", ""),
        "api_key": args.api_key,
        "api_key_env": args.api_key_env or model_spec.get("api_key_env", ""),
        "provider_module": args.provider_module or model_spec.get("provider_module", ""),
    }


def public_config(config: Dict[str, Any]) -> Dict[str, str]:
    result = public_model_config(
        config.get("provider", "auto"),
        config.get("model", ""),
        config.get("api_key_env", ""),
    )
    result["name"] = config.get("name", "")
    return result


def model_identity(config: Dict[str, Any]) -> str:
    return "{}:{}".format(config.get("provider", "auto"), config.get("model", ""))


def configuration_warnings(
    judge_configs: List[Dict[str, Any]], arbitrator_config: Dict[str, Any]
) -> List[str]:
    warnings = []
    identities = [model_identity(config) for config in judge_configs]
    duplicates = [identity for identity, count in Counter(identities).items() if count > 1]
    if duplicates:
        warnings.append("duplicate judge model identities: {}".format(", ".join(duplicates)))
    if arbitrator_config and model_identity(arbitrator_config) in identities:
        warnings.append("arbitrator uses the same model identity as a judge")
    return warnings


def median_arbitration(
    judge_results: List[Dict[str, Any]],
    dimensions: List[str],
    format_errors: List[str],
) -> Optional[Dict[str, Any]]:
    scores = [item["scores"] for item in judge_results if item.get("scores")]
    if not scores:
        return None
    result = {}
    disagreements = []
    for dimension in dimensions:
        values = [float(score[dimension]) for score in scores if isinstance(score.get(dimension), (int, float))]
        result[dimension] = round(statistics.median(values), 2) if values else None
        if values and max(values) - min(values) >= 2:
            disagreements.append("{} score range {}-{}".format(dimension, min(values), max(values)))
    numeric = [result[dimension] for dimension in dimensions if isinstance(result.get(dimension), (int, float))]
    result["overall"] = round(sum(numeric) / len(numeric), 2) if numeric else None
    tags = Counter(
        tag for score in scores for tag in score.get("failure_tags", []) if isinstance(tag, str)
    )
    result["failure_tags"] = [tag for tag, count in tags.items() if count >= max(1, len(scores) // 2)]
    result["issues"] = "; ".join(
        score.get("issues", "") for score in scores if score.get("issues")
    )
    result["highlight"] = "; ".join(
        score.get("highlight", "") for score in scores if score.get("highlight")
    )
    result["verdict"] = "reject" if format_errors else "consensus"
    result["confidence"] = round(1.0 - min(len(disagreements) / max(len(dimensions), 1), 0.75), 2)
    result["disagreements"] = disagreements
    result["strategy"] = "median"
    return result


def model_arbitration(
    provider: Any,
    config: Dict[str, Any],
    spec: Dict[str, Any],
    task_desc: str,
    contract: Dict[str, Any],
    record: Any,
    format_errors: List[str],
    judge_results: List[Dict[str, Any]],
    dimensions: List[str],
) -> Dict[str, Any]:
    prompt = render_template(spec.get("arbitration_user_template", DEFAULT_ARBITRATION_USER_TEMPLATE), {
        "task_desc": task_desc,
        "data_contract": json.dumps(contract, ensure_ascii=False, indent=2),
        "example": json.dumps(record, ensure_ascii=False, indent=2),
        "format_validation": json.dumps({"valid": not format_errors, "errors": format_errors}, ensure_ascii=False),
        "judge_results": json.dumps(judge_results, ensure_ascii=False, indent=2),
    })
    text = provider.generate(
        [
            {"role": "system", "content": spec.get(
                "arbitration_system_prompt", DEFAULT_ARBITRATION_SYSTEM_PROMPT
            )},
            {"role": "user", "content": prompt},
        ],
        model=config.get("model", ""),
        temperature=0.0,
        max_tokens=int(spec.get("arbitration_max_tokens", 1200)),
        response_format={"type": "json_object"},
    )
    result = parse_score(text, dimensions)
    result["strategy"] = "model"
    return result


def evaluate(args: argparse.Namespace) -> Dict[str, Any]:
    input_records, parse_errors = load_jsonl(Path(args.input))
    seed_records, seed_parse_errors = load_jsonl(Path(args.seed)) if args.seed else ([], [])
    spec = {}
    if args.prompt_spec:
        spec = json.loads(Path(args.prompt_spec).read_text(encoding="utf-8"))
    contract = spec.get("data_contract", {})
    dimensions = spec.get("dimensions", DEFAULT_DIMENSIONS)
    deterministic = []
    valid_records = []
    for index, record in enumerate(input_records):
        errors = validate_record(record, contract)
        deterministic.append({"index": index, "valid": not errors, "errors": errors})
        if not errors:
            valid_records.append((index, record))

    judge_configs = spec.get("judges", [])
    if not judge_configs:
        legacy = legacy_model_config(args, spec)
        judge_configs = [legacy] if legacy else []
    judge_configs = [
        dict({"name": "judge-{}".format(index + 1)}, **config)
        for index, config in enumerate(judge_configs)
    ]
    arbitrator_config = spec.get("arbitrator", {})
    use_llm = not args.deterministic_only and bool(judge_configs)
    judge_providers = []
    arbitrator_provider = None
    if use_llm and valid_records:
        judge_providers = [(config, build_provider(config, args)) for config in judge_configs]
        if arbitrator_config:
            arbitrator_provider = build_provider(arbitrator_config, args)

    random.seed(args.random_seed)
    if args.sample is None or args.sample < 1:
        sampled = list(valid_records)
    else:
        sample_count = min(args.sample, len(valid_records))
        sampled = random.sample(valid_records, sample_count) if sample_count else []
    reference_pool = seed_records or input_records
    reference = random.choice(reference_pool) if reference_pool else {}
    system_prompt = spec.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
    user_template = spec.get("user_template", DEFAULT_USER_TEMPLATE)
    details = []
    for index, record in sampled:
        if not judge_providers:
            break
        prompt = render_template(user_template, {
            "task_desc": args.task_desc or spec.get("task_desc", ""),
            "data_contract": json.dumps(contract, ensure_ascii=False, indent=2),
            "reference": json.dumps(reference, ensure_ascii=False, indent=2),
            "example": json.dumps(record, ensure_ascii=False, indent=2),
        })
        judge_results = []
        for config, provider in judge_providers:
            try:
                text = provider.generate(
                    [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                    model=config.get("model", ""),
                    temperature=0.0,
                    max_tokens=int(spec.get("max_tokens", 800)),
                    response_format={"type": "json_object"},
                )
                judge_results.append({"judge": config.get("name"), "scores": parse_score(text, dimensions)})
            except (ProviderError, ValueError, json.JSONDecodeError) as exc:
                judge_results.append({"judge": config.get("name"), "scores": None, "error": str(exc)})
        format_errors = deterministic[index]["errors"]
        arbitration = None
        arbitration_error = None
        if arbitrator_provider is not None:
            try:
                arbitration = model_arbitration(
                    arbitrator_provider, arbitrator_config, spec,
                    args.task_desc or spec.get("task_desc", ""), contract, record,
                    format_errors, judge_results, dimensions,
                )
            except (ProviderError, ValueError, json.JSONDecodeError) as exc:
                arbitration_error = str(exc)
        if arbitration is None:
            arbitration = median_arbitration(judge_results, dimensions, format_errors)
        detail = {
            "index": index,
            "example": record,
            "judge_results": judge_results,
            "arbitration": arbitration,
            "scores": arbitration,
        }
        if arbitration_error:
            detail["arbitration_error"] = arbitration_error
        details.append(detail)

    scored = [item["scores"] for item in details if item.get("scores")]
    judge_summaries = {}
    for config in judge_configs:
        name = config.get("name", "")
        judge_scores = [
            result["scores"]
            for item in details
            for result in item.get("judge_results", [])
            if result.get("judge") == name and result.get("scores")
        ]
        judge_summaries[name] = summarize(judge_scores, dimensions)
    failure_tag_counts = Counter(
        tag
        for score in scored
        for tag in score.get("failure_tags", [])
        if isinstance(tag, str)
    )
    low_scoring = [
        {"index": item["index"], "overall": item["scores"]["overall"], "issues": item["scores"].get("issues", "")}
        for item in details
        if item.get("scores") and item["scores"].get("overall") is not None
        and item["scores"]["overall"] < args.low_score_threshold
    ]
    bad_output_path = resolve_bad_output_path(Path(args.output), args.bad_output)
    bad_case_report = build_bad_case_report(
        args.input, args.low_score_threshold, parse_errors,
        deterministic, input_records, details,
    )
    write_bad_case_report(bad_output_path, bad_case_report)
    report = {
        "input": args.input,
        "output": args.output,
        "bad_output": str(bad_output_path),
        "counts": {
            "records": len(input_records),
            "parse_errors": len(parse_errors),
            "format_valid": sum(1 for item in deterministic if item["valid"]),
            "format_invalid": sum(1 for item in deterministic if not item["valid"]),
            "llm_evaluated": len(scored),
            "llm_evaluation_scope": "all_valid_records" if args.sample is None or args.sample < 1 else "sampled",
            "judge_calls_succeeded": sum(
                1 for item in details for result in item.get("judge_results", []) if result.get("scores")
            ),
            "judge_calls_failed": sum(
                1 for item in details for result in item.get("judge_results", []) if result.get("error")
            ),
            "arbitrations_succeeded": sum(1 for item in details if item.get("arbitration")),
            "arbitrations_failed": sum(1 for item in details if item.get("arbitration_error")),
        },
        "judges": [public_config(config) for config in judge_configs],
        "arbitrator": public_config(arbitrator_config) if arbitrator_config else None,
        "configuration_warnings": configuration_warnings(judge_configs, arbitrator_config),
        "judge_summaries": judge_summaries,
        "summary": summarize(scored, dimensions),
        "evidence": {
            "failure_tag_counts": dict(failure_tag_counts.most_common()),
            "passing_indexes": [
                item["index"] for item in details
                if item.get("scores") and item["scores"].get("overall") is not None
                and item["scores"]["overall"] >= args.low_score_threshold
            ],
            "failing_indexes": [item["index"] for item in low_scoring],
        },
        "low_scoring": low_scoring,
        "parse_errors": parse_errors,
        "seed_parse_errors": seed_parse_errors,
        "format_validation": deterministic,
        "details": details,
        "bad_case_report": dict({"output": str(bad_output_path)}, **bad_case_report),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and evaluate a JSONL dataset")
    parser.add_argument("--input", required=True)
    parser.add_argument("--seed", default="")
    parser.add_argument("--prompt-spec", default="")
    parser.add_argument("--output", default="eval_report.json")
    parser.add_argument("--bad-output", default="")
    parser.add_argument("--task-desc", default="")
    parser.add_argument(
        "--sample", type=int, default=0,
        help="Number of valid records to LLM-evaluate; 0 or omitted evaluates all valid records",
    )
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--low-score-threshold", type=float, default=3.0)
    parser.add_argument("--deterministic-only", action="store_true")
    parser.add_argument("--provider", choices=["auto", "openai", "gemini"], default="")
    parser.add_argument("--provider-module", default="")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--api-key-env", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-retries", type=int, default=3)
    return parser


def main() -> int:
    try:
        report = evaluate(build_parser().parse_args())
    except Exception as exc:
        print("evaluation failed: {}".format(exc), file=sys.stderr)
        return 1
    print(json.dumps(report["counts"], ensure_ascii=False))
    print("report: {}".format(report["output"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
