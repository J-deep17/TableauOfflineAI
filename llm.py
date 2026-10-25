"""Talks to a local LM Studio (OpenAI-compatible) server. Standard library only."""
import json
import threading
import time
import urllib.error
import urllib.request

AUTO = "auto-detect model"

SYSTEM = (
    "You are a Tableau expert helping a user answer a question about their data. "
    "You are given VERIFIED FACTS computed exactly from the data. Rules:\n"
    "1. Use ONLY numbers that appear in the facts. Never calculate new totals or invent values.\n"
    "2. Give a short, direct answer first, then the exact Tableau steps: which fields go on "
    "Rows/Columns/Marks/Filters, and any calculated field formula in Tableau syntax.\n"
    "3. Use [Field Name] in square brackets for fields. If the facts do not contain what is "
    "needed, say so plainly instead of guessing.\n"
    "4. Keep it concise."
)


def build_prompt(question, facts):
    return (f"VERIFIED FACTS (exact, computed from the data):\n{facts}\n\n"
            f"QUESTION:\n{question}\n\n"
            "Answer using only the facts above, then explain how to build it in Tableau.")


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
