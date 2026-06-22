import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from evaluate_data import evaluate, median_arbitration, parse_score, validate_record  # noqa: E402
from generate_data import (  # noqa: E402
    generate_batches,
    load_reference_files,
    parse_examples,
    read_source_records,
    render_template,
)
from build_prd_reference import build_reference  # noqa: E402
from llm_client import (  # noqa: E402
    GeminiProvider,
    OpenAICompatibleProvider,
    create_provider,
    public_model_config,
)
from llm_eval import translate_legacy_args  # noqa: E402
from run_role_agent import role_config, run_role  # noqa: E402
from validate_workflow_config import validate_workflow_config  # noqa: E402


MOCK_PROVIDER = ROOT / "tests" / "fixtures" / "mock_provider.py"


class ProviderTests(unittest.TestCase):
    def test_custom_provider_registration(self):
        provider = create_provider("custom", provider_module=str(MOCK_PROVIDER))
        result = provider.generate([{"role": "user", "content": "COUNT=1 "}], "mock")
        self.assertEqual(len(parse_examples(result)), 1)

    def test_public_config_does_not_include_secret(self):
        config = public_model_config("openai", "model", "OPENAI_API_KEY")
        self.assertNotIn("api_key", config)
        self.assertNotIn("api_base", config)

    def test_builtin_provider_response_parsing(self):
        openai = OpenAICompatibleProvider("https://example.test/v1", "secret")
        openai._post = lambda url, payload, headers: {"choices": [{"message": {"content": "openai"}}]}
        self.assertEqual(openai.generate([{"role": "user", "content": "x"}], "model"), "openai")
        gemini = GeminiProvider("https://example.test/v1beta", "secret")
        gemini._post = lambda url, payload, headers: {
            "candidates": [{"content": {"parts": [{"text": "gemini"}]}}]
        }
        self.assertEqual(gemini.generate([{"role": "user", "content": "x"}], "model"), "gemini")

    def test_legacy_argument_translation(self):
        result = translate_legacy_args(["--api-style", "gemini", "--seed-ratio", "0.5", "--sample", "4"])
        self.assertEqual(result, ["--provider", "gemini", "--sample", "4"])


class GenerationTests(unittest.TestCase):
    def test_parse_examples_accepts_fence_array_wrapper_and_jsonl(self):
        self.assertEqual(parse_examples("```json\n[{\"a\": 1}]\n```"), [{"a": 1}])
        self.assertEqual(parse_examples('{"examples": [{"a": 1}]}'), [{"a": 1}])
        self.assertEqual(parse_examples('{"a": 1}\n{"a": 2}'), [{"a": 1}, {"a": 2}])

    def test_template_replacement_preserves_json_braces(self):
        rendered = render_template('Return {"examples": []}; count={count}', {"count": 2})
        self.assertEqual(rendered, 'Return {"examples": []}; count=2')

    def test_generation_reference_files_are_loaded_relative_to_prompt_spec(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            spec = directory / "generation_prompt.json"
            spec.write_text("{}", encoding="utf-8")
            reference = directory / "prd_generation_reference.json"
            reference.write_text('{"functional_requirements": []}', encoding="utf-8")
            loaded = load_reference_files(spec, ["prd_generation_reference.json"])
            self.assertIn("functional_requirements", loaded)

    def test_generate_and_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            spec = directory / "generation_prompt.json"
            spec.write_text(json.dumps({
                "system_prompt": "generate",
                "user_template": "COUNT={count} BATCH={batch_index}",
                "count": 3,
                "batch_size": 2,
                "model": {"provider": "custom", "model": "mock"},
            }), encoding="utf-8")
            output = directory / "preview.jsonl"
            report = directory / "generation_report.json"
            args = argparse.Namespace(
                prompt_spec=str(spec), output=str(output), report=str(report), count=None,
                batch_size=None, resume=False, continue_on_error=False, max_failures=3,
                source_data="", variants_per_record=None, provider="",
                provider_module=str(MOCK_PROVIDER), api_base="", api_key="", api_key_env="",
                model="", timeout=1, max_retries=1,
            )
            result = generate_batches(args)
            self.assertTrue(result["complete"])
            self.assertEqual(result["total"], 3)
            args.resume = True
            result = generate_batches(args)
            self.assertEqual(result["existing"], 3)
            self.assertEqual(result["generated"], 0)

    def test_invalid_json_is_reported_as_partial_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            spec = directory / "generation_prompt.json"
            spec.write_text(json.dumps({
                "user_template": "COUNT={count}",
                "count": 2,
                "model": {"provider": "custom", "model": "invalid"},
            }), encoding="utf-8")
            args = argparse.Namespace(
                prompt_spec=str(spec), output=str(directory / "preview.jsonl"),
                report=str(directory / "generation_report.json"), count=None, batch_size=None,
                resume=False, continue_on_error=True, max_failures=1, source_data="",
                variants_per_record=None, provider="", provider_module=str(MOCK_PROVIDER),
                api_base="", api_key="", api_key_env="", model="", timeout=1, max_retries=1,
            )
            result = generate_batches(args)
            self.assertFalse(result["complete"])
            self.assertEqual(len(result["failures"]), 1)

    def test_source_records_accept_jsonl_and_json_wrappers(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            jsonl = directory / "seed.jsonl"
            jsonl.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
            self.assertEqual(len(read_source_records(jsonl)), 2)
            wrapper = directory / "seed.json"
            wrapper.write_text(json.dumps({"records": [{"a": 1}, {"a": 2}]}), encoding="utf-8")
            self.assertEqual(len(read_source_records(wrapper)), 2)

    def test_generalize_by_record_generates_variants_per_source_record(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "seed.jsonl"
            source.write_text(
                json.dumps({"messages": [{"role": "user", "content": "原始1"}]}, ensure_ascii=False) + "\n" +
                json.dumps({"messages": [{"role": "user", "content": "原始2"}]}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            spec = directory / "generation_prompt.json"
            spec.write_text(json.dumps({
                "generation_mode": "generalize_by_record",
                "system_prompt": "generalize",
                "user_template": (
                    "COUNT={variants_per_record} SOURCE_INDEX={source_index}/{source_total} "
                    "SOURCE={source_record} REFERENCES={generation_references}"
                ),
                "source_data_file": "seed.jsonl",
                "variants_per_record": 2,
                "model": {"provider": "custom", "model": "mock"},
            }), encoding="utf-8")
            output = directory / "preview.jsonl"
            report = directory / "generation_report.json"
            args = argparse.Namespace(
                prompt_spec=str(spec), output=str(output), report=str(report), count=None,
                batch_size=None, resume=False, continue_on_error=False, max_failures=3,
                source_data="", variants_per_record=None, provider="",
                provider_module=str(MOCK_PROVIDER), api_base="", api_key="", api_key_env="",
                model="", timeout=1, max_retries=1,
            )
            result = generate_batches(args)
            self.assertTrue(result["complete"])
            self.assertEqual(result["generation_mode"], "generalize_by_record")
            self.assertEqual(result["source_records"], 2)
            self.assertEqual(result["total"], 4)
            self.assertEqual(len(output.read_text(encoding="utf-8").strip().splitlines()), 4)


class EvaluationTests(unittest.TestCase):
    def test_validate_chatml_and_custom_contract(self):
        good = {"messages": [{"role": "user", "content": "hi"}]}
        self.assertEqual(validate_record(good, {"type": "object", "format": "chatml"}), [])
        self.assertTrue(validate_record({}, {"type": "object", "required_fields": ["label"]}))

    def test_parse_score_adds_overall(self):
        result = parse_score(
            '{"naturalness": 2, "relevance": 4, "format": 5, "diversity": 3}',
            ["naturalness", "relevance", "format", "diversity"],
        )
        self.assertEqual(result["overall"], 3.5)

    def test_empty_and_malformed_jsonl_do_not_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            data = directory / "data.jsonl"
            data.write_text('not-json\n', encoding="utf-8")
            output = directory / "eval.json"
            args = self._args(data, output, deterministic_only=True)
            report = evaluate(args)
            self.assertEqual(report["counts"]["records"], 0)
            self.assertEqual(report["counts"]["parse_errors"], 1)
            self.assertIsNone(report["summary"]["overall"])

    def test_empty_input_does_not_initialize_configured_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            data = directory / "data.jsonl"
            data.write_text("", encoding="utf-8")
            spec = directory / "evaluation_prompt.json"
            spec.write_text(json.dumps({
                "model": {"provider": "openai", "model": "configured-model"},
                "data_contract": {"type": "object"},
            }), encoding="utf-8")
            output = directory / "eval.json"
            args = self._args(data, output, deterministic_only=False)
            args.prompt_spec = str(spec)
            args.provider_module = ""
            args.model = ""
            report = evaluate(args)
            self.assertEqual(report["counts"]["records"], 0)
            self.assertEqual(report["counts"]["llm_evaluated"], 0)

    def test_llm_evaluation_and_low_score_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            data = directory / "data.jsonl"
            data.write_text(json.dumps({
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ]
            }) + "\n", encoding="utf-8")
            output = directory / "eval.json"
            args = self._args(data, output, deterministic_only=False)
            report = evaluate(args)
            self.assertEqual(report["summary"]["overall"], 3.5)
            self.assertEqual(len(report["low_scoring"]), 1)
            self.assertEqual(report["evidence"]["failure_tag_counts"]["unnatural_language"], 1)

    def test_multiple_judges_and_model_arbitration(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            data = directory / "data.jsonl"
            data.write_text(json.dumps({
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ]
            }) + "\n", encoding="utf-8")
            spec = directory / "evaluation_prompt.json"
            spec.write_text(json.dumps({
                "judges": [
                    {"name": "low", "provider": "custom", "model": "judge-low"},
                    {"name": "high", "provider": "custom", "model": "judge-high"},
                ],
                "arbitrator": {"name": "arb", "provider": "custom", "model": "arbitrator"},
                "data_contract": {"type": "object", "format": "chatml"},
            }), encoding="utf-8")
            args = self._args(data, directory / "eval.json", deterministic_only=False)
            args.prompt_spec = str(spec)
            args.model = ""
            report = evaluate(args)
            detail = report["details"][0]
            self.assertEqual(len(detail["judge_results"]), 2)
            self.assertEqual(detail["arbitration"]["strategy"], "model")
            self.assertEqual(detail["scores"]["overall"], 4.25)
            self.assertEqual(report["counts"]["judge_calls_succeeded"], 2)
            self.assertEqual(report["counts"]["arbitrations_succeeded"], 1)
            self.assertEqual(report["judge_summaries"]["low"]["naturalness"], 1.0)
            self.assertEqual(report["judge_summaries"]["high"]["naturalness"], 5.0)
            self.assertEqual(report["configuration_warnings"], [])

    def test_median_arbitration_marks_disagreement(self):
        result = median_arbitration([
            {"judge": "low", "scores": {"naturalness": 1, "format": 5, "failure_tags": ["style"]}},
            {"judge": "high", "scores": {"naturalness": 5, "format": 5, "failure_tags": ["style"]}},
        ], ["naturalness", "format"], [])
        self.assertEqual(result["naturalness"], 3.0)
        self.assertEqual(result["strategy"], "median")
        self.assertTrue(result["disagreements"])

    def _args(self, data, output, deterministic_only):
        return argparse.Namespace(
            input=str(data), seed="", prompt_spec="", output=str(output), task_desc="test",
            sample=40, random_seed=42, low_score_threshold=4.0,
            deterministic_only=deterministic_only, provider="",
            provider_module=str(MOCK_PROVIDER), api_base="", api_key="", api_key_env="",
            model="mock", timeout=1, max_retries=1,
        )


class WorkflowConfigTests(unittest.TestCase):
    def test_complete_initial_configuration_is_valid(self):
        config = self._config()
        result = validate_workflow_config(config)
        self.assertTrue(result["valid"])
        self.assertEqual(result["warnings"], [])

    def test_generate_evaluate_mode_does_not_require_evolution_roles(self):
        config = self._config()
        config["workflow_mode"] = "generate_evaluate"
        config.pop("max_iterations")
        for role in ("proposer", "skill_builder", "auditor"):
            config["roles"].pop(role)
        result = validate_workflow_config(config)
        self.assertTrue(result["valid"])
        self.assertEqual(result["warnings"], [])

    def test_preview_count_is_deprecated_alias_for_target_count(self):
        config = self._config()
        config["preview_count"] = config.pop("target_count")
        result = validate_workflow_config(config)
        self.assertTrue(result["valid"])
        self.assertTrue(any("preview_count is deprecated" in warning for warning in result["warnings"]))

    def test_evolve_mode_requires_evolution_roles(self):
        config = self._config()
        config["roles"].pop("proposer")
        result = validate_workflow_config(config)
        self.assertFalse(result["valid"])
        self.assertTrue(any("roles.proposer is required" in error for error in result["errors"]))

    def test_judge_count_and_raw_key_are_rejected(self):
        config = self._config()
        config["roles"]["evaluator"]["judge_count"] = 3
        config["roles"]["generator"]["api_key"] = "secret"
        result = validate_workflow_config(config)
        self.assertFalse(result["valid"])
        self.assertTrue(any("judge_count" in error for error in result["errors"]))
        self.assertTrue(any("must not persist api_key" in error for error in result["errors"]))

    def test_external_role_requires_api_configuration(self):
        config = self._config()
        config["roles"]["proposer"] = {"execution": "api", "model": "proposal-model"}
        result = validate_workflow_config(config)
        self.assertFalse(result["valid"])
        self.assertTrue(any("roles.proposer requires provider" in error for error in result["errors"]))

    def test_api_backed_role_uses_initial_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config = self._config()
            config["roles"]["prompt_writer"] = {
                "execution": "api", "provider": "custom", "model": "role-model",
                "api_key_env": "ROLE_KEY",
            }
            workflow = directory / "workflow_config.json"
            workflow.write_text(json.dumps(config), encoding="utf-8")
            system = directory / "system.md"
            system.write_text("prompt writer", encoding="utf-8")
            input_file = directory / "input.md"
            input_file.write_text("COUNT=1", encoding="utf-8")
            output = directory / "output.json"
            args = argparse.Namespace(
                workflow_config=str(workflow), role="prompt_writer",
                system_prompt_file=str(system), input_file=str(input_file), output=str(output),
                provider_module=str(MOCK_PROVIDER), api_key="", temperature=0.0, max_tokens=100,
                json_output=True, timeout=1, max_retries=1,
            )
            result = run_role(args)
            self.assertEqual(result["role"], "prompt_writer")
            self.assertTrue(output.exists())
            self.assertNotIn("api_key", result["model"])

    def test_current_session_role_cannot_be_api_invoked(self):
        with self.assertRaises(ValueError):
            role_config(self._config(), "proposer")

    def _config(self):
        return {
            "workflow_mode": "evolve",
            "target_count": 10,
            "max_iterations": 3,
            "roles": {
                "prd_analyzer": {"execution": "current_session"},
                "prompt_writer": {"execution": "current_session"},
                "generator": {
                    "execution": "api", "provider": "custom", "model": "generator",
                    "api_key_env": "GENERATOR_KEY",
                },
                "evaluator": {
                    "judge_count": 2,
                    "judges": [
                        {
                            "name": "judge-a", "execution": "api", "provider": "custom",
                            "model": "judge-a", "api_key_env": "JUDGE_A_KEY",
                        },
                        {
                            "name": "judge-b", "execution": "api", "provider": "custom",
                            "model": "judge-b", "api_key_env": "JUDGE_B_KEY",
                        },
                    ],
                    "arbitrator": {
                        "execution": "api", "provider": "custom", "model": "arbitrator",
                        "api_key_env": "ARBITRATOR_KEY",
                    },
                },
                "proposer": {"execution": "current_session"},
                "skill_builder": {"execution": "current_session"},
                "auditor": {"execution": "current_session"},
            },
        }


class PrdReferenceTests(unittest.TestCase):
    def test_all_requirements_and_related_utterances_are_preserved(self):
        reference, report = build_reference({
            "task": "车载音乐控制",
            "domain": "car-music",
            "source_inventory": [{"file": "prd.md", "sections_reviewed": ["播放", "异常"]}],
            "unmapped_sections": [],
            "mvp_flow": [
                {
                    "id": "MVP-001",
                    "name": "用户提出播放需求",
                    "description": "用户表达要播放某个歌手或歌曲",
                    "actor": "user",
                    "user_goal": "听到指定音乐",
                    "system_behavior": "识别播放意图并提取实体",
                    "required_requirements": ["FR-001"],
                    "source_refs": [{"file": "prd.md", "section": "播放"}],
                }
            ],
            "functional_requirements": [
                {
                    "id": "FR-001",
                    "parent_id": None,
                    "name": "播放歌手歌曲",
                    "description": "播放指定歌手的歌曲",
                    "source_refs": [{"file": "prd.md", "section": "播放"}],
                    "expected_behaviors": ["开始播放"],
                    "utterances": [
                        {"text": "放周杰伦", "type": "prd_example"},
                        {"text": "播放周杰伦", "type": "prd_example"},
                    ],
                },
                {
                    "id": "FR-002",
                    "parent_id": None,
                    "name": "无结果处理",
                    "description": "搜索无结果时进行提示",
                    "source_refs": [{"file": "prd.md", "section": "异常"}],
                    "utterances": [],
                },
            ],
        })
        self.assertEqual(report["requirement_count"], 2)
        self.assertEqual(report["source_document_count"], 1)
        self.assertEqual(report["utterance_count"], 2)
        self.assertEqual(report["requirements_without_utterances"], ["FR-002"])
        self.assertEqual(len(reference["functional_requirements"]), 2)
        self.assertEqual(report["mvp_flow_step_count"], 1)
        self.assertEqual(report["mvp_flow_step_ids"], ["MVP-001"])
        self.assertEqual(reference["mvp_flow"][0]["required_requirements"], ["FR-001"])

    def test_mvp_flow_without_source_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            build_reference({
                "source_inventory": [{"file": "prd.md", "sections_reviewed": ["流程"]}],
                "mvp_flow": [{
                    "id": "MVP-001", "name": "开始", "description": "用户开始任务",
                    "source_refs": [],
                }],
                "functional_requirements": [{
                    "id": "FR-001", "name": "x", "description": "y",
                    "source_refs": [{"file": "prd.md", "section": "功能"}], "utterances": [],
                }],
            })

    def test_requirement_without_source_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            build_reference({
                "source_inventory": [{"file": "prd.md", "sections_reviewed": ["功能"]}],
                "functional_requirements": [{
                    "id": "FR-001", "name": "x", "description": "y",
                    "source_refs": [], "utterances": [],
                }]
            })

    def test_missing_source_inventory_is_rejected(self):
        with self.assertRaises(ValueError):
            build_reference({"functional_requirements": []})


if __name__ == "__main__":
    unittest.main()
