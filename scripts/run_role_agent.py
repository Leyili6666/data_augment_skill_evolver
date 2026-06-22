#!/usr/bin/env python3
"""Invoke one API-backed workflow role from the upfront workflow configuration."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from llm_client import create_provider, public_model_config


SUPPORTED_ROLES = {"prd_analyzer", "prompt_writer", "proposer", "skill_builder", "auditor"}


def role_config(workflow: Dict[str, Any], role: str) -> Dict[str, Any]:
    if role not in SUPPORTED_ROLES:
        raise ValueError("unsupported role: {}".format(role))
    config = workflow.get("roles", {}).get(role)
    if not isinstance(config, dict):
        raise ValueError("missing role configuration: {}".format(role))
    if config.get("execution") != "api":
        raise ValueError("role {} is configured for current_session, not api".format(role))
    return config


def run_role(args: argparse.Namespace) -> Dict[str, Any]:
    workflow = json.loads(Path(args.workflow_config).read_text(encoding="utf-8"))
    config = role_config(workflow, args.role)
    provider = create_provider(
        config.get("provider", "auto"),
        api_base=config.get("api_base", ""),
        api_key=args.api_key,
        api_key_env=config.get("api_key_env", ""),
        provider_module=config.get("provider_module", "") or args.provider_module,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )
    system_prompt = Path(args.system_prompt_file).read_text(encoding="utf-8")
    user_prompt = Path(args.input_file).read_text(encoding="utf-8")
    text = provider.generate(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        model=config.get("model", ""),
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        response_format={"type": "json_object"} if args.json_output else None,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text.rstrip() + "\n", encoding="utf-8")
    return {
        "role": args.role,
        "model": public_model_config(
            config.get("provider", "auto"), config.get("model", ""), config.get("api_key_env", "")
        ),
        "output": str(output),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Invoke one configured API-backed workflow role")
    parser.add_argument("--workflow-config", required=True)
    parser.add_argument("--role", required=True, choices=sorted(SUPPORTED_ROLES))
    parser.add_argument("--system-prompt-file", required=True)
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider-module", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-retries", type=int, default=3)
    return parser


def main() -> int:
    try:
        result = run_role(build_parser().parse_args())
    except Exception as exc:
        print("role invocation failed: {}".format(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
