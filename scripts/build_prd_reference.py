#!/usr/bin/env python3
"""Validate PRD analysis and build a compact generation reference."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


REQUIRED_REQUIREMENT_FIELDS = ("id", "name", "description", "source_refs", "utterances")
REQUIRED_FLOW_STEP_FIELDS = ("id", "name", "description", "source_refs")


def normalize_utterance(value: Any, requirement_id: str) -> Dict[str, Any]:
    if isinstance(value, str):
        return {"text": value.strip(), "type": "example", "source_refs": []}
    if not isinstance(value, dict):
        raise ValueError("{} utterance must be a string or object".format(requirement_id))
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("{} utterance requires non-empty text".format(requirement_id))
    return {
        "text": text.strip(),
        "type": value.get("type", "example"),
        "intent": value.get("intent", ""),
        "expected_behavior": value.get("expected_behavior", ""),
        "source_refs": value.get("source_refs", []),
    }


def normalize_mvp_flow(analysis: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    flow = analysis.get("mvp_flow", [])
    if flow in (None, []):
        return [], []
    if not isinstance(flow, list):
        raise ValueError("mvp_flow must be an array when provided")
    normalized, step_ids = [], set()
    for index, step in enumerate(flow):
        if not isinstance(step, dict):
            raise ValueError("mvp_flow[{}] must be an object".format(index))
        missing = [field for field in REQUIRED_FLOW_STEP_FIELDS if field not in step]
        if missing:
            raise ValueError("mvp_flow[{}] missing fields: {}".format(index, ", ".join(missing)))
        step_id = str(step["id"]).strip()
        if not step_id:
            raise ValueError("mvp_flow[{}] has empty id".format(index))
        if step_id in step_ids:
            raise ValueError("duplicate mvp_flow id: {}".format(step_id))
        if not isinstance(step.get("name"), str) or not step["name"].strip():
            raise ValueError("{} requires non-empty name".format(step_id))
        if not isinstance(step.get("description"), str) or not step["description"].strip():
            raise ValueError("{} requires non-empty description".format(step_id))
        if not isinstance(step.get("source_refs"), list) or not step["source_refs"]:
            raise ValueError("{} requires at least one source_ref".format(step_id))
        step_ids.add(step_id)
        normalized.append({
            "id": step_id,
            "name": step["name"],
            "description": step["description"],
            "actor": step.get("actor", ""),
            "user_goal": step.get("user_goal", ""),
            "system_behavior": step.get("system_behavior", ""),
            "user_utterance_patterns": step.get("user_utterance_patterns", []),
            "assistant_response_requirements": step.get("assistant_response_requirements", []),
            "required_requirements": step.get("required_requirements", []),
            "branching": step.get("branching", []),
            "edge_cases": step.get("edge_cases", []),
            "source_refs": step.get("source_refs", []),
        })
    return normalized, [item["id"] for item in normalized]


def build_reference(analysis: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    source_inventory = analysis.get("source_inventory")
    if not isinstance(source_inventory, list) or not source_inventory:
        raise ValueError("source_inventory must be a non-empty array")
    for index, source in enumerate(source_inventory):
        if not isinstance(source, dict) or not source.get("file"):
            raise ValueError("source_inventory[{}] requires file".format(index))
        if not isinstance(source.get("sections_reviewed"), list) or not source["sections_reviewed"]:
            raise ValueError("source_inventory[{}] requires sections_reviewed".format(index))
    requirements = analysis.get("functional_requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("functional_requirements must be a non-empty array")
    seen_ids, seen_utterances = set(), set()
    normalized, missing_utterances, errors = [], [], []
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            errors.append("functional_requirements[{}] must be an object".format(index))
            continue
        missing = [field for field in REQUIRED_REQUIREMENT_FIELDS if field not in requirement]
        if missing:
            errors.append("requirement {} missing fields: {}".format(index, ", ".join(missing)))
            continue
        requirement_id = str(requirement["id"]).strip()
        if not requirement_id:
            errors.append("requirement {} has empty id".format(index))
            continue
        if requirement_id in seen_ids:
            errors.append("duplicate requirement id: {}".format(requirement_id))
            continue
        if not isinstance(requirement.get("name"), str) or not requirement["name"].strip():
            errors.append("{} requires non-empty name".format(requirement_id))
            continue
        if not isinstance(requirement.get("description"), str) or not requirement["description"].strip():
            errors.append("{} requires non-empty description".format(requirement_id))
            continue
        if not isinstance(requirement.get("source_refs"), list) or not requirement["source_refs"]:
            errors.append("{} requires at least one source_ref".format(requirement_id))
            continue
        if not isinstance(requirement.get("utterances"), list):
            errors.append("{} utterances must be an array".format(requirement_id))
            continue
        seen_ids.add(requirement_id)
        utterances = []
        for value in requirement.get("utterances", []):
            utterance = normalize_utterance(value, requirement_id)
            key = utterance["text"].casefold()
            if key not in seen_utterances:
                seen_utterances.add(key)
                utterances.append(utterance)
        if not utterances:
            missing_utterances.append(requirement_id)
        normalized.append({
            "id": requirement_id,
            "parent_id": requirement.get("parent_id"),
            "name": requirement["name"],
            "description": requirement["description"],
            "priority": requirement.get("priority", ""),
            "preconditions": requirement.get("preconditions", []),
            "inputs": requirement.get("inputs", []),
            "expected_behaviors": requirement.get("expected_behaviors", []),
            "edge_cases": requirement.get("edge_cases", []),
            "constraints": requirement.get("constraints", []),
            "source_refs": requirement.get("source_refs", []),
            "utterances": utterances,
        })
    if errors:
        raise ValueError("; ".join(errors))
    mvp_flow, mvp_step_ids = normalize_mvp_flow(analysis)
    reference = {
        "task": analysis.get("task", ""),
        "domain": analysis.get("domain", ""),
        "source_inventory": source_inventory,
        "functional_requirements": normalized,
    }
    if mvp_flow:
        reference["mvp_flow"] = mvp_flow
    report = {
        "valid": True,
        "source_document_count": len(source_inventory),
        "unmapped_sections": analysis.get("unmapped_sections", []),
        "requirement_count": len(normalized),
        "utterance_count": sum(len(item["utterances"]) for item in normalized),
        "requirements_without_utterances": missing_utterances,
        "coverage_requirement_ids": [item["id"] for item in normalized],
        "mvp_flow_step_count": len(mvp_flow),
        "mvp_flow_step_ids": mvp_step_ids,
    }
    return reference, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build generation reference from PRD analysis")
    parser.add_argument("--input", required=True, help="PRD analysis JSON")
    parser.add_argument("--output", default="prd_generation_reference.json")
    parser.add_argument("--report", default="prd_extraction_report.json")
    args = parser.parse_args()
    try:
        analysis = json.loads(Path(args.input).read_text(encoding="utf-8"))
        reference, report = build_reference(analysis)
        Path(args.output).write_text(
            json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as exc:
        print("PRD reference build failed: {}".format(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
