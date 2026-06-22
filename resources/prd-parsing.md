# PRD 解析指南

## Markdown / 纯文本

直接读取。重点寻找这些章节，名称可能不同：

- 背景 / Background / Overview → gives domain context
- 功能描述 / Feature Description / Requirements → defines task boundaries
- 输入输出 / Input/Output / 数据格式 → format spec
- 示例 / Examples / Sample Data → golden examples (very useful)
- 限制 / Constraints / Out of Scope → what NOT to generate

如果 PRD 用表格描述字段，逐列解析。

## Word (.docx)

```bash
pip install python-docx -q
python3 - << 'EOF'
from docx import Document
import sys

doc = Document(sys.argv[1])
for para in doc.paragraphs:
    if para.text.strip():
        print(para.text)

# Also dump tables
for table in doc.tables:
    for row in table.rows:
        cells = [c.text.strip() for c in row.cells]
        print(" | ".join(cells))
EOF
python3 - your_prd.docx
```

## PDF

```bash
pip install pypdf -q
python3 - << 'EOF'
from pypdf import PdfReader
import sys

reader = PdfReader(sys.argv[1])
for page in reader.pages:
    text = page.extract_text()
    if text:
        print(text)
EOF
python3 - your_prd.pdf
```

如果 `pypdf` 提取结果乱码，尤其是扫描版 PDF，尝试 `pdfminer.six`：

```bash
pip install pdfminer.six -q
python3 -m pdfminer.high_level.extract_text your_prd.pdf
```

## Excel (.xlsx)

Excel PRD 常见两种结构：

**需求列表**，每行一个需求：
```bash
pip install openpyxl -q
python3 - << 'EOF'
import openpyxl, sys

wb = openpyxl.load_workbook(sys.argv[1])
for sheet in wb.worksheets:
    print(f"\n=== Sheet: {sheet.title} ===")
    headers = [cell.value for cell in next(sheet.iter_rows())]
    print("Headers:", headers)
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if any(v for v in row):
            print(dict(zip(headers, row)))
EOF
python3 - your_prd.xlsx
```

**输入输出示例对**，每行一个输入/输出样例：
寻找类似 `输入`、`Input`、`Query`、`问题`、`输出`、`Output`、`Answer`、`回答` 的列。这些行可直接作为 seed 数据参考。

## 必需提取产物

不要只提取 Task Spec 就停止。必须产出：

1. `prd_analysis.json`：所有功能需求及其相关话术。
2. `prd_generation_reference.json`：经过校验的生成参考。
3. `prd_extraction_report.json`：覆盖统计和无话术需求列表。

当用户只提供 PRD、没有 seed JSONL 时，还必须在 `prd_analysis.json` 中提取 `mvp_flow`。MVP 流程
描述从用户发起任务到任务完成、异常处理或退出的完整最小可用路径，后续生成会按该流程创建多轮
对话。

Use [`../references/prd-analysis-agent.md`](../references/prd-analysis-agent.md) for the semantic
extraction contract, then run:

```bash
python3 <skill-dir>/scripts/build_prd_reference.py \
  --input <run-dir>/prd_analysis.json \
  --output <run-dir>/prd_generation_reference.json \
  --report <run-dir>/prd_extraction_report.json
```

每个功能需求都要提取：

- stable requirement ID and optional parent ID;
- complete requirement description and priority;
- 前置条件、输入、预期行为、边界情况和约束；
- 文件、章节、页码、表格或行级来源引用；
- 所有关联用户话术、示例 query、触发词和输入示例。

仅 PRD 输入时，每个 MVP 流程步骤还要提取：

- 步骤 ID、名称和描述；
- 参与方：用户、助手或系统；
- 用户目标和系统行为；
- 该步骤可能出现的用户话术；
- 助手回复要求；
- 关联功能需求 ID；
- 分支、异常和边界情况；
- 来源引用。

提取需求前，先在 `source_inventory` 中盘点每个源文档和已审阅章节。无法映射到需求的章节记录到
`unmapped_sections`；声明提取完成前必须复查这些章节。

没有话术的需求也要保留，用空数组表示。区分 PRD 原始话术和推断话术。助手回复和系统动作属于
`expected_behaviors`，不要放入 `utterances`。

## 提取 Task Spec

使用上面任意方式提取文本后，综合生成：

```
任务：[单句动宾短语，例如“将用户自然语言查询转换为 SQL”、“对用户评论做情感分类”]
输入空间：[典型用户消息，包括长度、领域、格式和风格]
输出空间：[典型助手响应，包括格式、必填字段和长度范围]
子任务：[列出 PRD 描述的 3-8 个独立场景或类别]
边界情况：[PRD 提到或可合理推断的边界输入]
不支持范围：[模型应拒绝或忽略的内容]
MVP 流程：[按步骤列出用户发起、澄清、执行、异常处理和完成反馈]
```

如果 PRD 包含输入/输出示例，把每对示例关联到所有相关功能需求。它们是判断任务真实含义的最可靠
信号，必须通过 `prd_generation_reference.json` 提供给后续生成阶段。

## 展示与用户确认

PRD 解析完成后，不得直接进入数据增强。必须先展示解析结果并征求用户确认。

展示内容至少包括：

- Task Spec：任务目标、输入空间、输出空间、数据契约；
- `source_inventory`：已审阅的文件和章节；
- 功能需求列表：ID、名称、优先级、来源引用；
- MVP 流程：步骤 ID、名称、参与方、用户目标、系统行为、关联需求、分支和边界；
- 每个需求关联的话术数量和代表性话术；
- 边界情况、约束、不支持范围和开放问题；
- `prd_extraction_report.json` 中的需求数、话术数、无话术需求；
- 后续生成计划如何覆盖这些需求。

如果用户确认，才可以继续编写 `generation_prompt.json` 和 `evaluation_prompt.json`。如果用户提出
修改要求，必须更新 `prd_analysis.json`，重新运行 `scripts/build_prd_reference.py`，再次展示修订结果。
用户未确认前，不得调用 `scripts/generate_data.py`。
