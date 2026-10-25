"""Talks to a local LM Studio (OpenAI-compatible) server. Standard library only."""
import json
import re
import threading
import time
import urllib.error
import urllib.request
import pandas as pd

AUTO = "auto-detect model"

SCHEMA_SYSTEM = (
    "You are an expert Data Architect, Database Modeler, and Tableau Certified Data Specialist.\n"
    "Your objective is to analyze the user's opened files and data tables to design the correct Tableau Logical Data Model (Schema) with complete business logic.\n\n"
    "REQUIRED OUTPUT STRUCTURE (Follow this structure strictly):\n\n"
    "### 1. TABLE ROLES & BUSINESS GRAIN\n"
    "For each table/sheet:\n"
    "* **[Table Name]**: [Fact / Dimension / Lookup / Bridge / Union Candidate]\n"
    "  * **Grain**: What exactly 1 record (row) represents.\n"
    "  * **Primary Key**: The column(s) that uniquely identify each record.\n\n"
    "### 2. LOGICAL RELATIONSHIPS & BUSINESS LOGIC\n"
    "For each relationship between tables:\n"
    "* **[Table A] <---> [Table B]**\n"
    "  * **Relating Fields**: `[Table A].[Field A]` = `[Table B].[Field B]`\n"
    "  * **Cardinality**: Many-to-One (N:1), One-to-Many (1:N), One-to-One (1:1), or Many-to-Many (N:M)\n"
    "  * **Business Logic**: Explain WHY these tables connect in the real world and what business questions this relationship answers.\n"
    "  * **Tableau Model**: Recommend whether to use Tableau Logical Relationship (noodles, default) or Physical Join/Union.\n\n"
    "### 3. STEP-BY-STEP TABLEAU CANVAS DRAG GUIDE\n"
    "1. Drag `[Primary Fact/Transaction Table]` onto the canvas first as the base.\n"
    "2. Drag `[Next Table]` to the right of `[Table]` to create a relationship noodle. Set relationship field: `[Field]` = `[Field]`.\n"
    "3. [Continue numbered steps for all tables in logical dependency order].\n\n"
    "### 4. DATA MODELING & EXAM ADVICE\n"
    "* [Key advice on preventing duplicate rows, managing different grains, handling missing keys, or table calculation considerations]\n\n"
    "### 5. STRUCTURED SCHEMA DEFINITION\n"
    "Provide the relationship graph in this exact JSON format so the application canvas can render it:\n"
    "```json\n"
    "[\n"
    "  {\n"
    "    \"Table A\": \"...\",\n"
    "    \"Field A\": \"...\",\n"
    "    \"Table B\": \"...\",\n"
    "    \"Field B\": \"...\",\n"
    "    \"Cardinality\": \"MANY-to-ONE\",\n"
    "    \"Reason\": \"...\"\n"
    "  }\n"
    "]\n"
    "```\n"
)

SYSTEM = (
    "You are an elite, concise Tableau Practical Exam Assistant.\n"
    "Your job is to provide direct, step-by-step instructions for Tableau Desktop practical exams.\n"
    "Do NOT act like a chatty tutor. Do NOT provide lengthy theoretical explanations or unrequested business analysis.\n"
    "Assume the student is in a timed practical examination and needs to know EXACTLY what to click and drag immediately.\n\n"
    "REQUIRED ANSWER STRUCTURE (Follow this structure strictly and consistently):\n\n"
    "### QUESTION\n"
    "[Rewrite the task as a 1-line crisp objective]\n\n"
    "### FIELDS TO USE\n"
    "* Dimension: `[Exact Field Name]`\n"
    "* Measure: `[Exact Field Name]` (aggregation, e.g. SUM, AVG, COUNTD, MIN, MAX)\n"
    "(Only include fields needed for this question. Never invent field names.)\n\n"
    "### STEP-BY-STEP SOLUTION\n"
    "1. Drag `[Field]` -> Rows.\n"
    "2. Drag `[Field]` -> Columns.\n"
    "3. Set Marks to [Bar / Line / Square / Map / Pie / Scatter].\n"
    "4. [Sort / Filter / Top N / Table Calculation action if needed].\n"
    "5. [Additional necessary actions].\n"
    "(Aim for 5 to 7 concise numbered steps. One clear action per step. Always specify Tableau shelves: Rows, Columns, Marks, Filters, Color, Size, Detail, Tooltip.)\n\n"
    "### FINAL RESULT\n"
    "[1-2 sentences stating what the final chart/view displays. If exact figures were verified in the facts, include them concisely, e.g.: 'Top 5 cities ranked: New York ($256k), Los Angeles ($175k)...']\n\n"
    "### CALCULATED FIELD\n"
    "Not required.\n"
    "[OR IF REQUIRED:\n"
    "Field Name: [Name]\n"
    "Formula:\n"
    "```tableau\n"
    "[Valid Tableau formula syntax using exact [Field] names]\n"
    "```\n"
    "Steps:\n"
    "1. Right-click Data pane -> Create Calculated Field.\n"
    "2. Name it `[Name]`.\n"
    "3. Paste formula and click OK.\n"
    "4. Drag `[Name]` to [Shelf].]\n\n"
    "### EXAM TIP\n"
    "[1 short sentence warning, common exam mistake, or memory aid (e.g., 'Sales value means SUM(Sales); if asking for volume of items sold, use SUM(Quantity).')]\n\n"
    "STRICT RULES:\n"
    "1. ONLY use fields that actually exist in the provided dataset facts. NEVER invent fields.\n"
    "2. ONLY quote numbers from the VERIFIED FACTS. Never invent or hallucinate totals.\n"
    "3. Keep steps short, clear, and action-oriented. Use '->' to indicate dragging to shelves or selecting menu items.\n"
    "4. Never suggest a calculated field when standard Tableau operations (drag, sort, Quick Table Calc, Top N filter) suffice.\n"
    "5. If question asks for Top N: specify Drag [Dimension] -> Filters -> Top tab -> By Field: Top N by [Measure].\n"
    "6. If question asks for distinct count: specify COUNTD([Field]), NOT COUNT([Field]).\n"
    "7. If a calculated field is not needed, you MUST write 'Not required.' under CALCULATED FIELD.\n"
)


def build_prompt(question, facts):
    return (
        f"VERIFIED DATASET SCHEMA & FACTS:\n{facts}\n\n"
        f"EXAM QUESTION:\n{question}\n\n"
        "Provide the practical exam solution using the EXACT required structure:\n"
        "### QUESTION\n"
        "### FIELDS TO USE\n"
        "### STEP-BY-STEP SOLUTION\n"
        "### FINAL RESULT\n"
        "### CALCULATED FIELD\n"
        "### EXAM TIP"
    )


def build_schema_prompt(tables, analysis=None):
    """Build a comprehensive architectural prompt describing all opened tables, types, and data samples."""
    lines = [
        "ANALYZE THE FOLLOWING OPENED FILES AND BUILD THE OPTIMAL TABLEAU LOGICAL DATA MODEL (SCHEMA) WITH BUSINESS LOGICS.\n"
    ]
    for tname, df in tables.items():
        lines.append(f"=== TABLE: {tname} ({len(df):,} rows, {len(df.columns)} columns) ===")
        col_desc = []
        for c in df.columns:
            s = df[c]
            nn = s.dropna()
            uniq = nn.nunique()
            uniq_pct = (uniq / len(nn) * 100) if len(nn) > 0 else 0

            # infer type
            is_num = pd.api.types.is_numeric_dtype(s)
            is_date = pd.api.types.is_datetime64_any_dtype(s) or any(w in str(c).lower() for w in ("date", "time", "year", "month", "day"))
            if is_date:
                col_type = "Dimension (date)"
            elif is_num and (uniq_pct > 80 or any(w in str(c).lower() for w in ("id", "key", "code", "num", "no", "pk", "fk"))):
                col_type = "Dimension (ID/numeric)"
            elif is_num:
                col_type = "Measure (number)"
            else:
                col_type = "Dimension (text)"

            samples = [str(v) for v in nn.unique()[:4]]
            sample_str = ", ".join(f"'{val[:30]}'" for val in samples)
            extra = ""
            if uniq_pct == 100 and len(nn) > 0:
                extra = " [100% Unique - Primary Key Candidate]"
            elif uniq_pct > 90 and len(nn) > 0:
                extra = f" [{uniq_pct:.0f}% Unique]"
            col_desc.append(f"  * [{c}] - {col_type} - {uniq:,} unique values{extra} - Samples: [{sample_str}]")
        lines.append("\n".join(col_desc))

        if len(df) > 0:
            sample_rows = df.head(2).to_dict(orient="records")
            lines.append("  Sample Rows:")
            for r in sample_rows:
                short_r = {str(k): (str(v)[:30] if pd.notna(v) else "null") for k, v in list(r.items())[:8]}
                lines.append(f"    {short_r}")
        lines.append("")

    if analysis:
        pairs = analysis.get("pairs", [])
        if pairs:
            lines.append("HEURISTIC CANDIDATE RELATIONSHIPS (Detected from column names and value overlaps):")
            for p in pairs[:8]:
                lines.append(f"  * {p.get('Table A')}.[{p.get('Field A')}] <-> {p.get('Table B')}.[{p.get('Field B')}] (Overlap: {p.get('Overlap', 0):.0%}, Suggested Cardinality: {p.get('Cardinality', 'Unknown')})")
            lines.append("")
        unions = analysis.get("union_candidates", {})
        if unions:
            lines.append("HEURISTIC UNION CANDIDATES (Same schema / structure):")
            for child, parent in unions.items():
                lines.append(f"  * {child} appears to be appended rows of {parent}")
            lines.append("")

    lines.append(
        "TASK:\n"
        "1. Identify the core Fact/Transaction table vs Dimension/Lookup tables.\n"
        "2. Define the logical relationships with exact join/relationship keys.\n"
        "3. Detail the real-world Business Logic explaining WHY these tables connect and what business insights they produce.\n"
        "4. Provide step-by-step instructions for the Tableau Data Source canvas (drag-and-drop order).\n"
        "5. Include a structured JSON array at the end inside ```json ... ``` with the exact relationship definitions."
    )
    return "\n".join(lines)


def extract_schema_model(text, tables):
    """Extract and validate structured schema relationship tree from AI response."""
    if not text or not tables:
        return []

    patterns = [
        r"```(?:json)?\s*(\[\s*\{.*?\}\s*\])\s*```",
        r"(\[\s*\{[\s\S]*?\}\s*\])"
    ]
    raw_json = None
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            raw_json = m.group(1).strip()
            break

    if not raw_json:
        return []

    try:
        data = json.loads(raw_json)
        if not isinstance(data, list):
            return []
    except Exception:
        return []

    tbl_lookup = {t.lower(): t for t in tables}
    tree = []
    seen_pairs = set()
    for item in data:
        if not isinstance(item, dict):
            continue

        t_a_raw = str(item.get("Table A") or item.get("table_a") or item.get("from_table") or "").strip()
        t_b_raw = str(item.get("Table B") or item.get("table_b") or item.get("to_table") or "").strip()
        f_a_raw = str(item.get("Field A") or item.get("field_a") or item.get("from_field") or "").strip().strip("[]`'\"")
        f_b_raw = str(item.get("Field B") or item.get("field_b") or item.get("to_field") or "").strip().strip("[]`'\"")

        t_a = tbl_lookup.get(t_a_raw.lower())
        t_b = tbl_lookup.get(t_b_raw.lower())
        if not t_a or not t_b or t_a == t_b:
            continue

        pair_key = frozenset((t_a, t_b))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        cols_a = {str(c).lower(): str(c) for c in tables[t_a].columns}
        cols_b = {str(c).lower(): str(c) for c in tables[t_b].columns}

        f_a = cols_a.get(f_a_raw.lower())
        f_b = cols_b.get(f_b_raw.lower())
        if not f_a or not f_b:
            continue

        card_raw = str(item.get("Cardinality") or item.get("cardinality") or "MANY-to-ONE").upper()
        if "1:M" in card_raw or "ONE-TO-MANY" in card_raw:
            card = "ONE-to-MANY"
            many_side = t_b
        elif "1:1" in card_raw or "ONE-TO-ONE" in card_raw:
            card = "ONE-to-ONE"
            many_side = t_a
        elif "M:M" in card_raw or "MANY-TO-MANY" in card_raw:
            card = "MANY-to-MANY"
            many_side = t_a
        else:
            card = "MANY-to-ONE"
            many_side = t_a

        tree.append({
            "Table A": t_a,
            "Field A": f_a,
            "Fields A": [f_a],
            "Table B": t_b,
            "Field B": f_b,
            "Fields B": [f_b],
            "Cardinality": card,
            "MANY side": many_side,
            "Status": "Confirmed",
            "Confidence": 0.95,
            "is_composite": False,
            "Overlap": 1.0,
            "Reason": str(item.get("Reason") or item.get("reason") or "AI verified relationship"),
        })

    return tree


def _url(base, path):
    return base.rstrip("/") + path


def _request(url, api_key, data=None, timeout=15):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    return urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=timeout)


def get_models(base_url, api_key):
    with _request(_url(base_url, "/models"), api_key) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [m["id"] for m in data.get("data", []) if "embed" not in m["id"].lower()]


def choose_model(base_url, api_key, wanted):
    if wanted and wanted.strip().lower() != AUTO:
        return wanted.strip()
    models = get_models(base_url, api_key)
    if not models:
        raise RuntimeError("No model is loaded in LM Studio. Load one and start the local server.")
    return models[0]


def start(messages, base_url, api_key, model, limit, timeout):
    """Start streaming in a background thread; returns a state dict that the UI polls."""
    state = {"content": "", "reasoning": "", "tokens": 0, "done": False, "error": None,
             "finish": None, "stop": False, "t_start": time.time(), "t_first": None, "t_end": None}

    def work():
        try:
            payload = {"model": model, "messages": messages, "max_tokens": limit,
                       "temperature": 0.1, "stream": True}
            with _request(_url(base_url, "/chat/completions"), api_key, payload, timeout) as r:
                for raw in r:
                    if state["stop"]:
                        break
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        choice = json.loads(chunk)["choices"][0]
                    except (ValueError, KeyError, IndexError):
                        continue
                    delta = choice.get("delta") or {}
                    text, think = delta.get("content") or "", delta.get("reasoning_content") or ""
                    if text or think:
                        if state["t_first"] is None:
                            state["t_first"] = time.time()
                        state["tokens"] += 1
                        state["content"] += text
                        state["reasoning"] += think
                    if choice.get("finish_reason"):
                        state["finish"] = choice["finish_reason"]
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001
                detail = ""
            state["error"] = f"HTTP {e.code}: {detail}"
        except Exception as e:  # noqa: BLE001
            state["error"] = str(e)
        finally:
            state["t_end"] = time.time()
            state["done"] = True

    threading.Thread(target=work, daemon=True).start()
    return state


def progress_estimate(state, prompt_tokens, perf, limit):
    now = time.time()
    el = now - state["t_start"]
    if state["t_first"] is None:
        pre = perf.get("prefill_tps")
        eta = prompt_tokens / pre if pre else 20.0
        return min(0.18 + 0.2 * el / max(eta, 1.0), 0.38), "Reading the facts"
    expected = min(perf.get("avg_out") or 600, limit)
    frac = 0.4 + 0.58 * min(state["tokens"] / max(expected, 1), 1.0)
    return min(frac, 0.98), ("Thinking" if not state["content"] else "Writing answer")


def learn(state, prompt_tokens, perf):
    if state["error"] or not state["t_end"] or not state["t_first"]:
        return
    pre, gen = state["t_first"] - state["t_start"], state["t_end"] - state["t_first"]
    if pre > 0.2:
        perf["prefill_tps"] = prompt_tokens / pre
    if gen > 0.5 and state["tokens"] > 5:
        perf["gen_tps"] = state["tokens"] / gen
    if state["tokens"]:
        perf["avg_out"] = int(0.5 * perf.get("avg_out", 600) + 0.5 * state["tokens"])
