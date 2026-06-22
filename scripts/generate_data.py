#!/usr/bin/env python3
"""Generate JSONL datasets from a prompt specification."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

from llm_client import ProviderError, create_provider, public_model_config


def strip_code_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def parse_examples(text: str) -> List[Any]:
    """Parse an array, an examples wrapper, one object, or JSONL."""
    value = strip_code_fence(text)
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("examples"), list):
            return parsed["examples"]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    examples = []
    for line_number, line in enumerate(value.splitlines(), 1):
        if not line.strip():
            continue
        try:
            examples.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError("invalid model JSON on response line {}: {}".format(line_number, exc))
    if not examples:
        raise ValueError("model response contained no JSON examples")
    return examples


def read_jsonl(path: Path) -> List[Any]:
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError("existing output line {} is invalid: {}".format(number, exc))
    return records


def read_source_records(path: Path) -> List[Any]:
    if not path.is_file():
        raise ValueError("source data file not found: {}".format(path))
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("source data file is empty: {}".format(path))
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("examples"), list):
            return parsed["examples"]
        if isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
            return parsed["records"]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    return read_jsonl(path)


def write_jsonl(path: Path, records: Iterable[Any], append: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def render_template(template: str, values: Dict[str, Any]) -> str:
    """Replace known placeholders while leaving literal JSON braces untouched."""
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def format_user_prompt(template: str, count: int, batch_index: int, generated_count: int) -> str:
    return render_template(template, {
        "count": count,
        "batch_index": batch_index,
        "generated_count": generated_count,
    })


def resolve_relative(spec_path: Path, configured_path: str) -> Path:
    path = Path(configured_path).expanduser()
    if not path.is_absolute():
        path = spec_path.parent / path
    return path


def load_reference_files(spec_path: Path, reference_files: List[str]) -> str:
    references = []
    for configured_path in reference_files:
        path = resolve_relative(spec_path, configured_path)
        if not path.is_file():
            raise ValueError("generation reference file not found: {}".format(path))
        references.append("=== {} ===\n{}".format(
            configured_path, path.read_text(encoding="utf-8").strip()
        ))
    return "\n\n".join(references)


def create_generation_provider(args: argparse.Namespace, spec: Dict[str, Any]):
    provider_name = args.provider or spec.get("model", {}).get("provider", "auto")
    model = args.model or spec.get("model", {}).get("model", "")
    api_base = args.api_base or spec.get("model", {}).get("api_base", "")
    api_key_env = args.api_key_env or spec.get("model", {}).get("api_key_env", "")
    provider = create_provider(
        provider_name,
        api_base=api_base,
        api_key=args.api_key,
        api_key_env=api_key_env,
        provider_module=args.provider_module,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )
    return provider, provider_name, model, api_key_env


def call_generation_model(
    provider: Any,
    model: str,
    system_prompt: str,
    user_template: str,
    template_values: Dict[str, Any],
    temperature: float,
    max_tokens: int,
) -> List[Any]:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": render_template(user_template, template_values)})
    text = provider.generate(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return parse_examples(text)


def generate_by_record(
    args: argparse.Namespace,
    spec_path: Path,
    spec: Dict[str, Any],
    output_path: Path,
    existing: List[Any],
    generation_references: str,
) -> Dict[str, Any]:
    configured_source = args.source_data or spec.get("source_data_file", "")
    if not configured_source:
        raise ValueError("generalize_by_record requires source_data_file or --source-data")
    source_path = resolve_relative(spec_path, configured_source)
    source_records = read_source_records(source_path)
    variants_per_record = (
        args.variants_per_record
        if args.variants_per_record is not None
        else int(spec.get("variants_per_record", 1))
    )
    if variants_per_record < 1:
        raise ValueError("variants-per-record must be positive")
    target_count = args.count if args.count is not None else variants_per_record * len(source_records)
    if target_count < 1:
        raise ValueError("count must be positive")
    if len(existing) >= target_count:
        provider_name = args.provider or spec.get("model", {}).get("provider", "auto")
        model = args.model or spec.get("model", {}).get("model", "")
        api_key_env = args.api_key_env or spec.get("model", {}).get("api_key_env", "")
        return {
            "requested": target_count,
            "existing": len(existing),
            "generated": 0,
            "total": len(existing),
            "complete": True,
            "failures": [],
            "model": public_model_config(provider_name, model, api_key_env),
            "output": str(output_path),
            "generation_mode": "generalize_by_record",
            "source_data_file": str(source_path),
            "source_records": len(source_records),
            "variants_per_record": variants_per_record,
            "per_source": [],
        }

    provider, provider_name, model, api_key_env = create_generation_provider(args, spec)
    system_prompt = spec.get("system_prompt", "")
    user_template = spec.get("user_template") or spec.get("user_prompt", "")
    if not user_template:
        raise ValueError("prompt spec requires user_template or user_prompt")
    temperature = float(spec.get("temperature", 0.7))
    max_tokens = int(spec.get("max_tokens", 4096))
    failures = []
    per_source = []
    generated_count = len(existing)
    source_total = len(source_records)
    start_source_index = min(generated_count // variants_per_record, source_total)

    for zero_based_index in range(start_source_index, source_total):
        if generated_count >= target_count:
            break
        source_record = source_records[zero_based_index]
        requested = min(variants_per_record, target_count - generated_count)
        try:
            records = call_generation_model(
                provider,
                model,
                system_prompt,
                user_template,
                {
                    "count": requested,
                    "variants_per_record": requested,
                    "source_index": zero_based_index + 1,
                    "source_total": source_total,
                    "source_record": json.dumps(source_record, ensure_ascii=False),
                    "generated_count": generated_count,
                    "generation_references": generation_references,
                },
                temperature,
                max_tokens,
            )[:requested]
            if not records:
                raise ValueError("provider returned an empty batch")
            write_jsonl(output_path, records)
            generated_count += len(records)
            per_source.append({
                "source_index": zero_based_index + 1,
                "requested": requested,
                "generated": len(records),
            })
            print("source {}/{}: wrote {} examples ({}/{})".format(
                zero_based_index + 1, source_total, len(records), generated_count, target_count
            ))
        except (ProviderError, ValueError) as exc:
            failures.append({"source_index": zero_based_index + 1, "error": str(exc)})
            print("source {} failed: {}".format(zero_based_index + 1, exc), file=sys.stderr)
            if not args.continue_on_error:
                break
            if len(failures) >= args.max_failures:
                break

    return {
        "requested": target_count,
        "existing": len(existing),
        "generated": generated_count - len(existing),
        "total": generated_count,
        "complete": generated_count >= target_count,
        "failures": failures,
        "model": public_model_config(provider_name, model, api_key_env),
        "output": str(output_path),
        "generation_mode": "generalize_by_record",
        "source_data_file": str(source_path),
        "source_records": source_total,
        "variants_per_record": variants_per_record,
        "per_source": per_source,
    }


def generate_batches(args: argparse.Namespace) -> Dict[str, Any]:
    spec_path = Path(args.prompt_spec)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    generation_mode = spec.get("generation_mode", spec.get("mode", "generate"))
    target_count = args.count if args.count is not None else int(spec.get("count", 10))
    batch_size = args.batch_size if args.batch_size is not None else int(spec.get("batch_size", 10))
    if target_count < 1 or batch_size < 1:
        raise ValueError("count and batch-size must be positive")
    output_path = Path(args.output)
    existing = read_jsonl(output_path) if args.resume else []
    if not args.resume and output_path.exists():
        output_path.unlink()
    remaining = max(target_count - len(existing), 0)
    generation_references = load_reference_files(spec_path, spec.get("reference_files", []))

    if generation_mode == "generalize_by_record":
        report = generate_by_record(args, spec_path, spec, output_path, existing, generation_references)
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report

    provider_name = args.provider or spec.get("model", {}).get("provider", "auto")
    model = args.model or spec.get("model", {}).get("model", "")
    api_base = args.api_base or spec.get("model", {}).get("api_base", "")
    api_key_env = args.api_key_env or spec.get("model", {}).get("api_key_env", "")
    provider = None
    if remaining:
        provider = create_provider(
            provider_name,
            api_base=api_base,
            api_key=args.api_key,
            api_key_env=api_key_env,
            provider_module=args.provider_module,
            timeout=args.timeout,
            max_retries=args.max_retries,
        )
    system_prompt = spec.get("system_prompt", "")
    user_template = spec.get("user_template") or spec.get("user_prompt", "")
    if not user_template:
        raise ValueError("prompt spec requires user_template or user_prompt")
    temperature = float(spec.get("temperature", 0.7))
    max_tokens = int(spec.get("max_tokens", 4096))
    failures = []
    generated_count = len(existing)
    batch_index = 0

    while remaining:
        batch_index += 1
        requested = min(batch_size, remaining)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({
            "role": "user",
            "content": render_template(
                format_user_prompt(user_template, requested, batch_index, generated_count),
                {"generation_references": generation_references},
            ),
        })
        try:
            text = provider.generate(  # type: ignore[union-attr]
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            records = parse_examples(text)[:requested]
            if not records:
                raise ValueError("provider returned an empty batch")
            write_jsonl(output_path, records)
            generated_count += len(records)
            remaining = max(target_count - generated_count, 0)
            print("batch {}: wrote {} examples ({}/{})".format(
                batch_index, len(records), generated_count, target_count
            ))
        except (ProviderError, ValueError) as exc:
            failures.append({"batch_index": batch_index, "error": str(exc)})
            print("batch {} failed: {}".format(batch_index, exc), file=sys.stderr)
            if not args.continue_on_error:
                break
            if len(failures) >= args.max_failures:
                break

    report = {
        "requested": target_count,
        "existing": len(existing),
        "generated": generated_count - len(existing),
        "total": generated_count,
        "complete": generated_count >= target_count,
        "failures": failures,
        "model": public_model_config(provider_name, model, api_key_env),
        "output": str(output_path),
        "generation_mode": generation_mode,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate JSONL from a prompt specification")
    parser.add_argument("--prompt-spec", required=True)
    parser.add_argument("--output", default="generated.jsonl")
    parser.add_argument("--report", default="generation_report.json")
    parser.add_argument("--count", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--source-data", default="")
    parser.add_argument("--variants-per-record", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--max-failures", type=int, default=3)
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
        report = generate_batches(build_parser().parse_args())
    except Exception as exc:
        print("generation failed: {}".format(exc), file=sys.stderr)
        return 1
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
