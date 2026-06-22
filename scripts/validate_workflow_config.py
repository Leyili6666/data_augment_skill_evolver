#!/usr/bin/env python3
"""Validate the complete upfront model/API configuration for an evolution run."""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


BASE_ROLES = ["prd_analyzer", "prompt_writer"]
EVOLUTION_ROLES = ["proposer", "skill_builder", "auditor"]


def validate_api_model(config: Dict[str, Any], label: str, check_env: bool) -> List[str]:
    errors = []
    if config.get("execution") != "api":
        errors.append("{} must use execution=api".format(label))
        return errors
    for field in ("provider", "model"):
        if not config.get(field):
            errors.append("{} requires {}".format(label, field))
    if "api_key" in config:
        errors.append("{} must not persist api_key; use api_key_env".format(label))
    api_key_env = config.get("api_key_env")
    if not api_key_env:
        errors.append("{} requires api_key_env".format(label))
    elif check_env and not os.environ.get(api_key_env):
        errors.append("{} environment variable is not set: {}".format(label, api_key_env))
    return errors


def validate_workflow_config(config: Dict[str, Any], check_env: bool = False) -> Dict[str, Any]:
    errors, warnings = [], []
    workflow_mode = config.get("workflow_mode")
    if workflow_mode not in ("evolve", "generate_evaluate"):
        errors.append("workflow_mode must be evolve or generate_evaluate")
    target_count = config.get("target_count", config.get("preview_count"))
    if not isinstance(target_count, int) or target_count < 1:
        errors.append("target_count must be a positive integer")
    if "preview_count" in config and "target_count" not in config:
        warnings.append("preview_count is deprecated; use target_count")
    if workflow_mode == "evolve":
        if not isinstance(config.get("max_iterations"), int) or config.get("max_iterations", 0) < 1:
            errors.append("max_iterations must be a positive integer in evolve mode")
    elif config.get("max_iterations") not in (None, 1):
        warnings.append("generate_evaluate mode ignores max_iterations values other than 1")
    roles = config.get("roles")
    if not isinstance(roles, dict):
        return {"valid": False, "errors": errors + ["roles must be an object"], "warnings": warnings}

    required_roles = BASE_ROLES + (EVOLUTION_ROLES if workflow_mode == "evolve" else [])
    for role in required_roles:
        role_config = roles.get(role)
        if not isinstance(role_config, dict):
            errors.append("roles.{} is required".format(role))
            continue
        execution = role_config.get("execution")
        if execution not in ("current_session", "api"):
            errors.append("roles.{}.execution must be current_session or api".format(role))
        elif execution == "api":
            errors.extend(validate_api_model(role_config, "roles.{}".format(role), check_env))
    if workflow_mode == "generate_evaluate":
        configured_evolution_roles = [role for role in EVOLUTION_ROLES if role in roles]
        if configured_evolution_roles:
            warnings.append(
                "generate_evaluate mode ignores evolution roles: {}".format(
                    ", ".join(configured_evolution_roles)
                )
            )

    generator = roles.get("generator", {})
    errors.extend(validate_api_model(generator, "roles.generator", check_env))

    evaluator = roles.get("evaluator")
    if not isinstance(evaluator, dict):
        errors.append("roles.evaluator is required")
        evaluator = {}
    deterministic_only = evaluator.get("deterministic_only", False)
    judges = evaluator.get("judges", [])
    judge_count = evaluator.get("judge_count")
    if not isinstance(judges, list):
        errors.append("roles.evaluator.judges must be an array")
        judges = []
    if deterministic_only:
        if judge_count != 0:
            errors.append("roles.evaluator.judge_count must be 0 when deterministic_only=true")
    elif not isinstance(judge_count, int) or judge_count < 1:
        errors.append("roles.evaluator.judge_count must be a positive integer")
    if isinstance(judge_count, int) and judge_count != len(judges):
        errors.append("roles.evaluator.judge_count must match judges length")
    for index, judge in enumerate(judges):
        if not isinstance(judge, dict):
            errors.append("roles.evaluator.judges[{}] must be an object".format(index))
            continue
        errors.extend(validate_api_model(judge, "roles.evaluator.judges[{}]".format(index), check_env))

    arbitrator = evaluator.get("arbitrator")
    if deterministic_only:
        if judges or arbitrator:
            warnings.append("deterministic_only ignores configured judges and arbitrator")
    elif not isinstance(arbitrator, dict):
        errors.append("roles.evaluator.arbitrator is required unless deterministic_only=true")
    else:
        errors.extend(validate_api_model(arbitrator, "roles.evaluator.arbitrator", check_env))

    identities = [
        "{}:{}".format(judge.get("provider"), judge.get("model"))
        for judge in judges if isinstance(judge, dict)
    ]
    duplicates = [identity for identity, count in Counter(identities).items() if count > 1]
    if duplicates:
        warnings.append("duplicate judge model identities: {}".format(", ".join(duplicates)))
    if isinstance(arbitrator, dict):
        identity = "{}:{}".format(arbitrator.get("provider"), arbitrator.get("model"))
        if identity in identities:
            warnings.append("arbitrator uses the same model identity as a judge")
    builder = roles.get("skill_builder", {})
    auditor = roles.get("auditor", {})
    if builder.get("execution") == "api" and auditor.get("execution") == "api":
        builder_identity = "{}:{}".format(builder.get("provider"), builder.get("model"))
        auditor_identity = "{}:{}".format(auditor.get("provider"), auditor.get("model"))
        if builder_identity == auditor_identity:
            warnings.append("skill_builder and auditor use the same model identity")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate upfront workflow model/API configuration")
    parser.add_argument("--config", required=True)
    parser.add_argument("--check-env", action="store_true")
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        result = validate_workflow_config(config, args.check_env)
    except Exception as exc:
        result = {"valid": False, "errors": [str(exc)], "warnings": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
