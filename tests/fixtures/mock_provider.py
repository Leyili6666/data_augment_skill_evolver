import json


class MockProvider:
    def generate(self, messages, model, temperature=0.0, max_tokens=2048, response_format=None):
        if model == "invalid":
            return "not-json"
        prompt = messages[-1]["content"]
        if model == "arbitrator":
            return json.dumps({
                "naturalness": 3,
                "relevance": 5,
                "format": 5,
                "diversity": 4,
                "issues": "综合评委意见后的最终问题",
                "highlight": "仲裁保留了格式优势",
                "failure_tags": ["judge_disagreement"],
                "verdict": "revise",
                "confidence": 0.75,
                "disagreements": ["naturalness"],
            }, ensure_ascii=False)
        if "候选样本" in prompt:
            naturalness = 1 if model == "judge-low" else 5 if model == "judge-high" else 2
            return json.dumps({
                "naturalness": naturalness,
                "relevance": 4,
                "format": 5,
                "diversity": 3,
                "issues": "表达略显模板化",
                "highlight": "格式正确",
                "failure_tags": ["unnatural_language"],
            }, ensure_ascii=False)
        count_marker = "COUNT="
        count = 1
        if count_marker in prompt:
            count = int(prompt.split(count_marker, 1)[1].split()[0])
        return "```json\n" + json.dumps({
            "examples": [
                {"messages": [
                    {"role": "user", "content": "测试问题{}".format(i)},
                    {"role": "assistant", "content": "测试回答{}".format(i)},
                ]}
                for i in range(count)
            ]
        }, ensure_ascii=False) + "\n```"


def create_provider(config):
    return MockProvider()
