"""Tableau Offline AI — Exam Helper Formatter & Cheat Sheet Module.

Provides:
1. FORMULAS: Curated, verified catalog of Tableau exam formulas grouped by category.
2. Dataset validation: Checks whether formulas can be directly used on the active dataset.
3. Exam Markdown Renderer: Renders structured, beautiful exam cheat sheets in Tkinter Text widgets
   without raw markdown symbols (###, **, `, etc.), with visual shelf pills, field tags,
   and clean typography.
4. Extractors: Extracts clean text, steps-only, and formulas for 1-click exam copying.
"""
import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Categories for the Formula Cheat Sheet
FORMULA_CATEGORIES = [
    "All Categories",
    "Aggregation & LOD",
    "Table Calculations",
    "Date Functions",
    "Conditional Logic & Text",
    "Financial & Business Ratios",
]

# Comprehensive Formula Catalog for Tableau Practical Exams
FORMULAS: List[Dict[str, Any]] = [
    # 1. Aggregation & LOD
    {
        "category": "Aggregation & LOD",
        "name": "Sum of Measure",
        "formula": "SUM([Sales])",
        "purpose": "Calculates total sum across rows. Default aggregation for measures in Tableau.",
        "fields": ["Sales"],
        "compute_using": None,
    },
    {
        "category": "Aggregation & LOD",
        "name": "Average (Arithmetic Mean)",
        "formula": "AVG([Profit])",
        "purpose": "Calculates arithmetic mean; ignores NULL rows automatically.",
        "fields": ["Profit"],
        "compute_using": None,
    },
    {
        "category": "Aggregation & LOD",
        "name": "Distinct Count (Unique)",
        "formula": "COUNTD([Customer ID])",
        "purpose": "Counts unique items; essential for customer, order, or session counts without duplicates.",
        "fields": ["Customer ID"],
        "compute_using": None,
    },
    {
        "category": "Aggregation & LOD",
        "name": "Row Count (Non-null)",
        "formula": "COUNT([Order ID])",
        "purpose": "Counts total non-null occurrences; does not deduplicate repeat IDs.",
        "fields": ["Order ID"],
        "compute_using": None,
    },
    {
        "category": "Aggregation & LOD",
        "name": "Fixed LOD (Exact Level)",
        "formula": "{ FIXED [Region] : SUM([Sales]) }",
        "purpose": "Aggregates at an exact specified dimension level regardless of dimensions placed on view shelves.",
        "fields": ["Region", "Sales"],
        "compute_using": None,
    },
    {
        "category": "Aggregation & LOD",
        "name": "Exclude LOD (Omit Level)",
        "formula": "{ EXCLUDE [Category] : SUM([Sales]) }",
        "purpose": "Omits specific dimensions from the level of detail present on the view shelves.",
        "fields": ["Category", "Sales"],
        "compute_using": None,
    },
    {
        "category": "Aggregation & LOD",
        "name": "Include LOD (Finer Level)",
        "formula": "{ INCLUDE [Customer ID] : AVG([Sales]) }",
        "purpose": "Computes aggregate at a finer dimension level in addition to whatever dimensions are on the shelves.",
        "fields": ["Customer ID", "Sales"],
        "compute_using": None,
    },
    {
        "category": "Aggregation & LOD",
        "name": "Zero-Null Replacement (ZN)",
        "formula": "ZN([Sales])",
        "purpose": "Converts NULL measure values to 0 to prevent broken totals or missing visual bars.",
        "fields": ["Sales"],
        "compute_using": None,
    },

    # 2. Table Calculations
    {
        "category": "Table Calculations",
        "name": "Percent of Total",
        "formula": "SUM([Sales]) / TOTAL(SUM([Sales]))",
        "purpose": "Proportion of each dimension slice relative to the grand total. Format field as Percentage.",
        "fields": ["Sales"],
        "compute_using": "Table (across/down) or Specific Dimension",
    },
    {
        "category": "Table Calculations",
        "name": "Standard Rank (with ties)",
        "formula": "RANK(SUM([Sales]), 'desc')",
        "purpose": "Assigns standard ranks (1, 2, 2, 4); skips rank numbers on ties. Configure Compute Using.",
        "fields": ["Sales"],
        "compute_using": "Dimension being ranked",
    },
    {
        "category": "Table Calculations",
        "name": "Dense Rank (no gaps)",
        "formula": "RANK_DENSE(SUM([Sales]), 'desc')",
        "purpose": "Assigns consecutive ranks (1, 2, 2, 3) without skipping numbers on tied values.",
        "fields": ["Sales"],
        "compute_using": "Dimension being ranked",
    },
    {
        "category": "Table Calculations",
        "name": "Running Sum (Cumulative)",
        "formula": "RUNNING_SUM(SUM([Sales]))",
        "purpose": "Calculates cumulative sum from the first record to current row across the table/date view.",
        "fields": ["Sales"],
        "compute_using": "Date or Sequence Dimension",
    },
    {
        "category": "Table Calculations",
        "name": "Percent Difference (Growth)",
        "formula": "(SUM([Sales]) - LOOKUP(SUM([Sales]), -1)) / ABS(LOOKUP(SUM([Sales]), -1))",
        "purpose": "Period-over-period percentage growth (e.g. Month-over-Month or Year-over-Year change).",
        "fields": ["Sales"],
        "compute_using": "Date Dimension",
    },
    {
        "category": "Table Calculations",
        "name": "Moving Average (3-Period)",
        "formula": "WINDOW_AVG(SUM([Sales]), -2, 0)",
        "purpose": "Smoothes noisy trends by averaging current period and previous 2 periods.",
        "fields": ["Sales"],
        "compute_using": "Date Dimension",
    },

    # 3. Date Functions
    {
        "category": "Date Functions",
        "name": "Date Truncation (Start of Month)",
        "formula": "DATETRUNC('month', [Order Date])",
        "purpose": "Rounds date to first day of month as a continuous date (green pill for trend lines).",
        "fields": ["Order Date"],
        "compute_using": None,
    },
    {
        "category": "Date Functions",
        "name": "Date Part (Discrete Month 1-12)",
        "formula": "DATEPART('month', [Order Date])",
        "purpose": "Extracts integer month (1 to 12) for discrete seasonality bar charts and tables.",
        "fields": ["Order Date"],
        "compute_using": None,
    },
    {
        "category": "Date Functions",
        "name": "Date Difference (Days / Hours)",
        "formula": "DATEDIFF('day', [Order Date], [Ship Date])",
        "purpose": "Elapsed duration between two dates (e.g., shipping lag or turnaround time).",
        "fields": ["Order Date", "Ship Date"],
        "compute_using": None,
    },
    {
        "category": "Date Functions",
        "name": "Add Date Interval",
        "formula": "DATEADD('day', 30, [Order Date])",
        "purpose": "Adds 30 days or months to a date field for target deadlines.",
        "fields": ["Order Date"],
        "compute_using": None,
    },
    {
        "category": "Date Functions",
        "name": "Year Extraction",
        "formula": "YEAR([Order Date])",
        "purpose": "Extracts 4-digit calendar year as an integer (e.g. 2024).",
        "fields": ["Order Date"],
        "compute_using": None,
    },

    # 4. Conditional Logic & Text
    {
        "category": "Conditional Logic & Text",
        "name": "Conditional Threshold (IF)",
        "formula": "IF SUM([Sales]) >= 10000 THEN 'High' ELSE 'Low' END",
        "purpose": "Segments dimension groups into high vs low performance tiers.",
        "fields": ["Sales"],
        "compute_using": None,
    },
    {
        "category": "Conditional Logic & Text",
        "name": "Inline Condition (IIF)",
        "formula": "IIF([Profit] > 0, 'Profitable', 'Loss')",
        "purpose": "Shorthand IF-THEN-ELSE for binary classifications.",
        "fields": ["Profit"],
        "compute_using": None,
    },
    {
        "category": "Conditional Logic & Text",
        "name": "Null String Replacement",
        "formula": "IFNULL([Category], 'Unspecified')",
        "purpose": "Replaces NULL text values with a designated clean fallback label.",
        "fields": ["Category"],
        "compute_using": None,
    },
    {
        "category": "Conditional Logic & Text",
        "name": "Case Statement Remap",
        "formula": "CASE [Segment]\n  WHEN 'Consumer' THEN 1\n  WHEN 'Corporate' THEN 2\n  ELSE 3\nEND",
        "purpose": "Exact matching for clean categorical remapping or priority grouping.",
        "fields": ["Segment"],
        "compute_using": None,
    },
    {
        "category": "Conditional Logic & Text",
        "name": "String Contains Search",
        "formula": "CONTAINS([Product Name], 'Wireless')",
        "purpose": "Boolean True/False filter for substring keyword matches.",
        "fields": ["Product Name"],
        "compute_using": None,
    },

    # 5. Financial & Business Ratios
    {
        "category": "Financial & Business Ratios",
        "name": "Profit Margin %",
        "formula": "SUM([Profit]) / SUM([Sales])",
        "purpose": "Core business metric: profit divided by revenue. Format field as Percentage.",
        "fields": ["Profit", "Sales"],
        "compute_using": None,
    },
    {
        "category": "Financial & Business Ratios",
        "name": "Actual vs Target / Quota",
        "formula": "SUM([Sales]) / MIN([Target])",
        "purpose": "Compares actual performance against fixed quota when target is one value per group.",
        "fields": ["Sales", "Target"],
        "compute_using": None,
    },
    {
        "category": "Financial & Business Ratios",
        "name": "Discounted Net Price",
        "formula": "[Unit Price] * (1 - [Discount])",
        "purpose": "Row-level calculated net price per item after discount deduction.",
        "fields": ["Unit Price", "Discount"],
        "compute_using": None,
    },
]

# Tableau Shelf names to highlight visually
TABLEAU_SHELVES: Set[str] = {
    "Rows", "Columns", "Filters", "Marks", "Color", "Size",
    "Detail", "Tooltip", "Label", "Pages", "Shape", "Text"
}

# Regex to match tokens inside text lines
TOKEN_PATTERN = re.compile(
    r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]|->|→|\b(?:"
    + "|".join(TABLEAU_SHELVES)
    + r")\b)"
)


def validate_formula_fields(formula_item: Dict[str, Any], active_columns: Set[str]) -> Tuple[str, str]:
    """Validate whether formula fields exist in the active dataset.

    Returns (status_code, badge_label).
    status_code is one of: 'ready', 'table_calc', 'missing'.
    """
    if not active_columns:
        if formula_item.get("compute_using"):
            return "table_calc", f"⚙️ {formula_item['compute_using']}"
        return "neutral", "Select table to validate"

    missing = []
    norm_active = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in active_columns}

    for req in formula_item.get("fields", []):
        norm_req = re.sub(r"[^a-z0-9]", "", req.lower())
        matched = False
        # Direct match or substring match (e.g. 'sales' in 'totalsales')
        if norm_req in norm_active:
            matched = True
        else:
            for act_norm in norm_active:
                if norm_req in act_norm or act_norm in norm_req:
                    matched = True
                    break
        if not matched:
            missing.append(req)

    if formula_item.get("compute_using"):
        cu = formula_item["compute_using"]
        if missing:
            return "missing", f"⚠️ Needs [{', '.join(missing)}] | ⚙️ Compute Using: {cu}"
        return "table_calc", f"✓ Ready | ⚙️ Compute Using: {cu}"

    if missing:
        return "missing", f"⚠️ Needs [{', '.join(missing)}] (substitute with your field)"

    return "ready", "✓ Ready in dataset"


def configure_exam_tags(text_widget: Any) -> None:
    """Configure rich typography, shelf badges, and card tags on a Tkinter Text widget."""
    # Base configuration
    text_widget.tag_configure("base", font=("Segoe UI", 10), foreground="#1e293b")

    # Section Headers
    text_widget.tag_configure("h_task", font=("Segoe UI", 11, "bold"), foreground="#0f2d59",
                              background="#f1f5f9", spacing1=12, spacing3=4, lmargin1=8, lmargin2=8)
    text_widget.tag_configure("h_fields", font=("Segoe UI", 11, "bold"), foreground="#1e3a8a",
                              background="#eff6ff", spacing1=12, spacing3=4, lmargin1=8, lmargin2=8)
    text_widget.tag_configure("h_steps", font=("Segoe UI", 11, "bold"), foreground="#065f46",
                              background="#ecfdf5", spacing1=12, spacing3=4, lmargin1=8, lmargin2=8)
    text_widget.tag_configure("h_result", font=("Segoe UI", 11, "bold"), foreground="#1e293b",
                              background="#f8fafc", spacing1=12, spacing3=4, lmargin1=8, lmargin2=8)
    text_widget.tag_configure("h_calc", font=("Segoe UI", 11, "bold"), foreground="#581c87",
                              background="#faf5ff", spacing1=12, spacing3=4, lmargin1=8, lmargin2=8)
    text_widget.tag_configure("h_tip", font=("Segoe UI", 11, "bold"), foreground="#92400e",
                              background="#fffbeb", spacing1=12, spacing3=4, lmargin1=8, lmargin2=8)
    text_widget.tag_configure("h_generic", font=("Segoe UI", 11, "bold"), foreground="#0f172a",
                              background="#f1f5f9", spacing1=10, spacing3=4, lmargin1=8, lmargin2=8)

    # Numbered Steps & Bullets
    text_widget.tag_configure("step_num", font=("Segoe UI", 10, "bold"), foreground="#2563eb")
    text_widget.tag_configure("step_row", font=("Segoe UI", 10), foreground="#1e293b",
                              lmargin1=14, lmargin2=38, spacing1=3, spacing3=3)
    text_widget.tag_configure("bullet_dot", font=("Segoe UI", 10, "bold"), foreground="#3b82f6")
    text_widget.tag_configure("bullet_row", font=("Segoe UI", 10), foreground="#1e293b",
                              lmargin1=14, lmargin2=28, spacing1=2, spacing3=2)

    # Visual Badges & Inline Elements
    text_widget.tag_configure("shelf_pill", font=("Segoe UI", 9, "bold"), foreground="#1e40af",
                              background="#dbeafe")
    text_widget.tag_configure("field_pill", font=("Consolas", 10, "bold"), foreground="#0f172a",
                              background="#e2e8f0")
    text_widget.tag_configure("arrow", font=("Segoe UI", 10, "bold"), foreground="#64748b")
    text_widget.tag_configure("bold_inline", font=("Segoe UI", 10, "bold"), foreground="#0f172a")
    text_widget.tag_configure("normal_inline", font=("Segoe UI", 10), foreground="#1e293b")

    # Formula & Callout Cards
    text_widget.tag_configure("code_block", font=("Consolas", 10), foreground="#0f172a",
                              background="#f1f5f9", lmargin1=24, lmargin2=24, spacing1=3, spacing3=3)
    text_widget.tag_configure("tip_box", font=("Segoe UI", 10), foreground="#78350f",
                              background="#fffbeb", lmargin1=14, lmargin2=14, spacing1=4, spacing3=4, rmargin=14)
    text_widget.tag_configure("calc_none", font=("Segoe UI", 10, "bold"), foreground="#15803d",
                              background="#f0fdf4", lmargin1=14, lmargin2=14, spacing1=4, spacing3=4)
    text_widget.tag_configure("result_box", font=("Segoe UI", 10), foreground="#0f172a",
                              background="#f8fafc", lmargin1=14, lmargin2=14, spacing1=4, spacing3=4)

    # Chat Transcript Tags
    text_widget.tag_configure("chat_user_hdr", font=("Segoe UI", 10, "bold"), foreground="#1e40af",
                              background="#eff6ff", spacing1=10, spacing3=2, lmargin1=8, lmargin2=8)
    text_widget.tag_configure("chat_user_msg", font=("Segoe UI", 11), foreground="#0f172a",
                              background="#f8fafc", lmargin1=14, lmargin2=14, spacing1=2, spacing3=6)
    text_widget.tag_configure("chat_bot_hdr", font=("Segoe UI", 10, "bold"), foreground="#065f46",
                              background="#ecfdf5", spacing1=10, spacing3=2, lmargin1=8, lmargin2=8)
    text_widget.tag_configure("chat_divider", font=("Segoe UI", 9), foreground="#cbd5e1",
                              spacing1=6, spacing3=6)


def _tokenize_inline_text(text: str) -> List[Tuple[str, str]]:
    """Parse text into tokens: bold, field, shelf, arrow, or plain text."""
    tokens: List[Tuple[str, str]] = []
    last = 0
    for m in TOKEN_PATTERN.finditer(text):
        if m.start() > last:
            tokens.append(("normal_inline", text[last:m.start()]))
        raw = m.group(0)
        if raw.startswith("**") and raw.endswith("**") and len(raw) >= 4:
            tokens.append(("bold_inline", raw[2:-2]))
        elif raw.startswith("`") and raw.endswith("`") and len(raw) >= 2:
            tokens.append(("field_pill", f" {raw[1:-1]} "))
        elif raw.startswith("[") and raw.endswith("]") and len(raw) >= 2:
            tokens.append(("field_pill", f" {raw} "))
        elif raw in ("->", "→"):
            tokens.append(("arrow", " → "))
        elif raw in TABLEAU_SHELVES:
            tokens.append(("shelf_pill", f" {raw} "))
        else:
            tokens.append(("normal_inline", raw))
        last = m.end()
    if last < len(text):
        tokens.append(("normal_inline", text[last:]))
    return tokens


def append_user_message(text_widget: Any, query: str, timestamp: str = "") -> None:
    """Append a styled user query bubble to the chat transcript."""
    configure_exam_tags(text_widget)
    text_widget.config(state="normal")
    time_str = f" [{timestamp}]" if timestamp else ""
    text_widget.insert("end", f"\n💬  You{time_str}:\n", ("chat_user_hdr",))
    text_widget.insert("end", f"  {query.strip()}\n\n", ("chat_user_msg",))
    text_widget.config(state="disabled")
    text_widget.see("end")


def append_assistant_message(text_widget: Any, raw_markdown: str) -> None:
    """Append a styled assistant answer to the chat transcript."""
    configure_exam_tags(text_widget)
    text_widget.config(state="normal")
    text_widget.insert("end", "🎓  Tableau Exam Helper:\n", ("chat_bot_hdr",))
    render_exam_answer(text_widget, raw_markdown, clear=False)
    text_widget.config(state="normal")
    text_widget.insert("end", "\n" + "─" * 70 + "\n", ("chat_divider",))
    text_widget.config(state="disabled")
    text_widget.see("end")


def render_exam_answer(text_widget: Any, raw_markdown: str, clear: bool = True) -> None:
    """Parse raw markdown from AI and render a clean, professional exam cheat-sheet view."""
    configure_exam_tags(text_widget)
    text_widget.config(state="normal")
    if clear:
        text_widget.delete("1.0", "end")

    if not raw_markdown or not raw_markdown.strip():
        text_widget.config(state="disabled")
        return

    lines = raw_markdown.strip().splitlines()
    cur_section = ""
    in_code_block = False

    for line in lines:
        raw_line = line.strip()

        # Handle code block toggle
        if raw_line.startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            text_widget.insert("end", f"   {line}\n", ("code_block",))
            continue

        # Blank lines
        if not raw_line:
            text_widget.insert("end", "\n")
            continue

        # Section Headings
        header_norm = raw_line.lstrip("#").strip().upper()
        if raw_line.startswith("#") or (raw_line.endswith(":") and len(raw_line) <= 30 and header_norm in (
            "QUESTION", "TASK", "FIELDS TO USE", "FIELDS REQUIRED", "STEP-BY-STEP SOLUTION",
            "STEPS", "FINAL RESULT", "RESULT", "CALCULATED FIELD", "EXAM TIP", "TIP"
        )):
            if "QUESTION" in header_norm or "TASK" in header_norm:
                cur_section = "task"
                text_widget.insert("end", "\n🎯  EXAM TASK\n", ("h_task",))
            elif "FIELD" in header_norm and ("USE" in header_norm or "REQ" in header_norm or "TO" in header_norm):
                cur_section = "fields"
                text_widget.insert("end", "\n📋  FIELDS REQUIRED\n", ("h_fields",))
            elif "STEP" in header_norm:
                cur_section = "steps"
                text_widget.insert("end", "\n⚡  STEP-BY-STEP SOLUTION\n", ("h_steps",))
            elif "RESULT" in header_norm:
                cur_section = "result"
                text_widget.insert("end", "\n📊  FINAL RESULT\n", ("h_result",))
            elif "CALC" in header_norm:
                cur_section = "calc"
                text_widget.insert("end", "\n🧮  CALCULATED FIELD\n", ("h_calc",))
            elif "TIP" in header_norm:
                cur_section = "tip"
                text_widget.insert("end", "\n💡  EXAM TIP\n", ("h_tip",))
            else:
                cur_section = "generic"
                text_widget.insert("end", f"\n📌  {header_norm.title()}\n", ("h_generic",))
            continue

        # Handle Calculated Field: Not required
        if cur_section == "calc" and any(w in raw_line.lower() for w in ("not required", "none", "not needed")):
            text_widget.insert("end", "  ✓ Calculated field: Not required (standard Tableau drag-and-drop handles this).\n", ("calc_none",))
            continue

        # Numbered Steps (e.g., 1. Drag City -> Rows.)
        step_match = re.match(r"^(\d+)\.\s+(.*)$", raw_line)
        if step_match:
            num_str, rest = step_match.group(1), step_match.group(2)
            text_widget.insert("end", f"  {num_str}. ", ("step_num", "step_row"))
            for tag, val in _tokenize_inline_text(rest):
                text_widget.insert("end", val, (tag, "step_row"))
            text_widget.insert("end", "\n")
            continue

        # Bullet Items (e.g., * Dimension: City)
        bullet_match = re.match(r"^[\*\-]\s+(.*)$", raw_line)
        if bullet_match:
            rest = bullet_match.group(1)
            text_widget.insert("end", "  • ", ("bullet_dot", "bullet_row"))
            for tag, val in _tokenize_inline_text(rest):
                text_widget.insert("end", val, (tag, "bullet_row"))
            text_widget.insert("end", "\n")
            continue

        # Section specific styling
        if cur_section == "tip":
            text_widget.insert("end", "  ", ("tip_box",))
            for tag, val in _tokenize_inline_text(raw_line):
                text_widget.insert("end", val, (tag, "tip_box"))
            text_widget.insert("end", "\n")
        elif cur_section == "result":
            text_widget.insert("end", "  ", ("result_box",))
            for tag, val in _tokenize_inline_text(raw_line):
                text_widget.insert("end", val, (tag, "result_box"))
            text_widget.insert("end", "\n")
        else:
            text_widget.insert("end", "  ")
            for tag, val in _tokenize_inline_text(raw_line):
                text_widget.insert("end", val, (tag,))
            text_widget.insert("end", "\n")

    text_widget.config(state="disabled")


def extract_clean_text(raw_markdown: str) -> str:
    """Format the markdown into clean, professional plain text for copying to notes/scratchpad."""
    if not raw_markdown:
        return ""
    lines = []
    in_code = False
    for line in raw_markdown.strip().splitlines():
        line_s = line.strip()
        if line_s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            lines.append(f"    {line}")
            continue
        # Clean markdown symbols
        cleaned = re.sub(r"^###\s*", "", line)
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        cleaned = cleaned.replace("->", "→")
        lines.append(cleaned)
    return "\n".join(lines).strip()


def extract_steps(raw_markdown: str) -> str:
    """Extract only the numbered steps (1 to N) from the solution."""
    steps = []
    in_steps = False
    for line in raw_markdown.splitlines():
        line_s = line.strip()
        if "STEP" in line_s.upper() and ("###" in line_s or "SOLUTION" in line_s or "STEPS" in line_s):
            in_steps = True
            continue
        elif line_s.startswith("###") or "RESULT" in line_s.upper() or "CALCULATED" in line_s.upper():
            if in_steps:
                break
        if in_steps:
            m = re.match(r"^(\d+)\.\s+(.*)$", line_s)
            if m:
                step_num = m.group(1)
                text = m.group(2)
                text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
                text = re.sub(r"`([^`]+)`", r"\1", text)
                text = text.replace("->", "→")
                steps.append(f"{step_num}. {text}")

    if not steps:
        # Fallback: scan for any numbered steps anywhere in text
        for line in raw_markdown.splitlines():
            m = re.match(r"^(\d+)\.\s+(.*)$", line.strip())
            if m:
                text = re.sub(r"[`*]", "", m.group(2)).replace("->", "→")
                steps.append(f"{m.group(1)}. {text}")

    return "\n".join(steps).strip()


def extract_formula(raw_markdown: str) -> str:
    """Extract calculated field formula from markdown, handling multiline, code blocks, or backticks."""
    if not raw_markdown or not raw_markdown.strip():
        return ""

    lines = raw_markdown.splitlines()

    # 1. Look for explicit CALCULATED FIELD / FORMULA section first
    in_calc = False
    in_code = False
    calc_code_lines: List[str] = []
    calc_formula_lines: List[str] = []
    capturing_formula = False

    for line in lines:
        raw = line.strip()
        header_norm = raw.lstrip("#").strip().upper()
        is_calc_header = (raw.startswith("#") and ("CALC" in header_norm or "FORMULA" in header_norm)) or header_norm in ("CALCULATED FIELD", "CALCULATED FIELD:")
        if is_calc_header:
            in_calc = True
            capturing_formula = False
            continue
        if in_calc:
            if (raw.startswith("#") and not is_calc_header) or (raw and header_norm in ("EXAM TIP", "EXAM TIP:", "STEPS", "STEPS:", "RESULT", "FINAL RESULT")):
                break
            # Skip "Not required"
            if any(w in raw.lower() for w in ("not required", "not needed", "none")):
                return ""
            if raw.startswith("```"):
                if in_code:
                    return "\n".join(calc_code_lines).strip()
                in_code = True
                continue
            if in_code:
                calc_code_lines.append(line)
                continue

            # Look for "Formula: ..." or "Formula:\n..."
            if raw.lower().startswith("formula:"):
                part = raw.split(":", 1)[1].strip().strip("`")
                if part and not any(w in part.lower() for w in ("not required", "none")):
                    return part
                capturing_formula = True
                continue
            elif capturing_formula:
                if raw and not raw.lower().startswith("step") and not raw.startswith("#"):
                    clean = raw.strip("`")
                    if clean:
                        calc_formula_lines.append(clean)
                else:
                    capturing_formula = False

    if calc_code_lines:
        return "\n".join(calc_code_lines).strip()
    if calc_formula_lines:
        return "\n".join(calc_formula_lines).strip()

    # 2. Search for any fenced code block containing Tableau functions or syntax
    code_blocks = re.findall(r"```(?:tableau|sql)?\s*([\s\S]*?)\s*```", raw_markdown, re.IGNORECASE)
    for block in code_blocks:
        b_str = block.strip()
        if any(w in b_str.upper() for w in (
            "SUM(", "AVG(", "COUNTD(", "FIXED", "INCLUDE", "EXCLUDE", "IF ", "CASE ",
            "ZN(", "DATEDIFF(", "DATEPART(", "RANK(", "WINDOW_", "ATTR(", "LOOKUP("
        )):
            return b_str

    # 3. Search for inline Formula: `...` or Formula: ... (horizontal whitespace only)
    m = re.search(r"(?:\bFormula\b|\bCalculation\b):[^\S\r\n]*`([^`]+)`", raw_markdown, re.IGNORECASE)
    if m:
        res = m.group(1).strip()
        res = re.sub(r"^(?:Formula|Calculation|Calculated Field):\s*", "", res, flags=re.IGNORECASE).strip()
        if res and not any(w in res.lower() for w in ("not required", "none", "n/a")):
            return res

    m = re.search(r"(?:\bFormula\b|\bCalculation\b):[^\S\r\n]*([^\r\n]+)", raw_markdown, re.IGNORECASE)
    if m:
        res = m.group(1).strip().strip("`'\"")
        res = re.sub(r"^(?:Formula|Calculation|Calculated Field):\s*", "", res, flags=re.IGNORECASE).strip()
        if res and not any(w in res.lower() for w in ("not required", "none", "n/a")):
            return res

    # 4. If any code block exists at all, return the first one
    if code_blocks:
        return code_blocks[0].strip()

    return ""

