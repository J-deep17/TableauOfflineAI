"""Talks to a local LM Studio (OpenAI-compatible) server. Standard library only."""
import json
import threading
import time
import urllib.error
import urllib.request

AUTO = "auto-detect model"

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
