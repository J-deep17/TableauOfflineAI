"""Data-model and facts engine for Tableau Offline AI (no Streamlit imports).

Responsibilities
1. Decide which uploaded files are real tables (skip data dictionaries / readmes).
2. Detect relationships and keep only a loop-free tree (like a Tableau logical model).
3. Merge the tree into one fact table and compute EXACT numbers with pandas,
   so the local LLM copies verified numbers instead of guessing.
4. Check numbers in the model's answer against those facts.
"""
import math
import re
from collections import deque

import pandas as pd

SKIP_FILE_WORDS = ("dictionary", "readme", "data_dict", "metadata", "notes")
# Columns that are different spellings of the same thing.
ALIAS_GROUPS = [
    {"postalcode", "zip", "zipcode", "postcode"},
    {"customerid", "custid", "clientid"},
    {"productid", "prodid", "itemid", "sku"},
    {"employeeid", "empid", "workerid"},
    {"orderid", "ordernum", "ordernumber", "invoicenumber", "invoiceid"},
    {"state", "province", "stateprovince"},
    {"country", "countryregion", "nation"},
    {"categoryid", "catid"},
    {"vendorid", "supplierid"},
    {"storeid", "shopid"},
]
STOP_KEYS = {"", "id", "name", "date", "status", "type", "notes", "description"}
ID_WORDS = ("id", "zip", "postal", "code", "rowid", "lat", "lng", "latitude", "longitude")


def norm(x):
    return re.sub(r"[^a-z0-9]", "", str(x).lower())


def is_doc_file(name):
    n = name.lower()
    return any(w in n for w in SKIP_FILE_WORDS)


def default_selected(names):
    return [n for n in names if not is_doc_file(n)]


# --------------------------------------------------------------------------
# Key normalisation (so "06103" == 6103 and "ABC " == "abc")
# --------------------------------------------------------------------------
def norm_series(s):
    try:
        text = s.astype(str).str.strip()
        out = text.str.lower()
        num = pd.to_numeric(text, errors="coerce")
        mask = num.notna() & num.abs().lt(1e15)
        if mask.any():
            out.loc[mask] = num[mask].round().astype("int64").astype(str)
        return out.where(s.notna())
    except Exception:
        return s.astype(str).str.strip().str.lower()


def is_unique(s):
    try:
        clean = s.dropna()
        if len(clean) == 0:
            return False
        return bool(clean.nunique() == len(clean) and (s.isna().mean() < 0.05))
    except Exception:
        return False


def same_family(a, b):
    na, nb = norm(a), norm(b)
    if na == nb:
        return True
    return any(na in g and nb in g for g in ALIAS_GROUPS)


# --------------------------------------------------------------------------
# Relationship detection using robust relationship_engine
# --------------------------------------------------------------------------
import relationship_engine


def detect_pairs(tables):
    """Return candidate relationships detected and validated by relationship_engine."""
    if not tables or len(tables) < 2:
        return []
    res = relationship_engine.detect_all_relationships(tables)
    return res.get("pairs", [])


def spanning_tree(tables, pairs=None):
    """Loop-free tree of the best relationships (same rules as relationship_engine)."""
    if not tables or len(tables) < 2:
        return []
    if pairs is None:
        return relationship_engine.detect_all_relationships(tables).get("tree", [])
    parent = {n: n for n in tables}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    tree = []
    for p in sorted(pairs, key=lambda p: (p.get("_tier", 0), -p.get("_score", 0))):
        if p.get("Confidence", 0.0) < 0.50 or p["Table A"] not in parent or p["Table B"] not in parent:
            continue
        a, b = find(p["Table A"]), find(p["Table B"])
        if a != b:
            parent[a] = b
            tree.append(p)
    return tree


def get_model_analysis(tables):
    """Full data model analysis: tree, candidate pairs, profiles, union candidates, and disconnected explanations."""
    if not tables:
        return {"pairs": [], "tree": [], "profiles": {}, "union_candidates": {}, "disconnected": {}, "connected_tables": set()}
    return relationship_engine.detect_all_relationships(tables)


def guide_text(tree, disconnected=None, junction_tables=None):
    """Generate clear, step-by-step instructions for Tableau Data Source canvas."""
    return relationship_engine.generate_tableau_guide(tree, disconnected or {}, junction_tables)


# --------------------------------------------------------------------------
# Merged model + exact facts
# --------------------------------------------------------------------------
def pick_fact(tables, tree):
    """Fact table = MANY side of the most relationships; ties go to the table that has measures, then size."""
    if not tables:
        return ""
    many = {n: 0 for n in tables}
    for p in tree:
        m = p.get("MANY side")
        if m in many:
            many[m] += 1
    return max(tables, key=lambda n: (many[n], len(_measures(tables[n])) > 0, len(tables[n])))


def layout(tables, tree):
    """Tree layout so connector lines never cross cards. Disconnected tables placed cleanly below.
    Returns {table: (depth, row)}; depth = column, row may be fractional."""
    if not tables:
        return {}
    adj = {n: [] for n in tables}
    for e in tree:
        adj[e["Table A"]].append(e["Table B"])
        adj[e["Table B"]].append(e["Table A"])

    root = pick_fact(tables, tree)
    seen, pos, counter = set(), {}, [0]

    def place(n, depth):
        seen.add(n)
        children = [k for k in adj[n] if k not in seen]
        rows = [place(k, depth + 1) for k in children]
        row = sum(rows) / len(rows) if rows else float(counter[0])
        if not rows:
            counter[0] += 1
        pos[n] = (depth, row)
        return row

    # 1. Place connected components starting with root
    if root in tables:
        place(root, 0)

    # 2. Place any other connected sub-graphs
    for n in tables:
        if n not in seen and adj[n]:
            place(n, 0)

    # 3. Place disconnected tables neatly in column 0 with dedicated row index
    for n in tables:
        if n not in seen:
            seen.add(n)
            row = float(counter[0])
            counter[0] += 1
            pos[n] = (0, row)

    return pos


def _join_key(df, cols):
    """Normalised join key (case/space/'007'==7==7.0 safe); NaN if any part is missing."""
    parts = [norm_series(df[c]) for c in cols]
    key = parts[0]
    for p in parts[1:]:
        key = key + "\x1f" + p
    return key


def build_merged(tables, tree):
    """Left-join tables onto the fact table along the tree (ONE side only, supporting composite keys)."""
    if not tables:
        return None, []
    fact = pick_fact(tables, tree)
    merged = tables[fact].copy()
    visited = {fact}
    queue = deque([fact])

    while queue:
        cur = queue.popleft()
        for p in tree:
            if p["Table A"] == cur:
                other = p["Table B"]
                my_cols = p.get("Fields A", [p["Field A"]])
                other_cols = p.get("Fields B", [p["Field B"]])
            elif p["Table B"] == cur:
                other = p["Table A"]
                my_cols = p.get("Fields B", [p["Field B"]])
                other_cols = p.get("Fields A", [p["Field A"]])
            else:
                continue

            if other in visited or other not in tables:
                continue
            visited.add(other)
            queue.append(other)
            od = tables[other]

            if not all(c in od.columns for c in other_cols) or not all(c in merged.columns for c in my_cols):
                continue
            # only merge a ONE side (unique key) so the row count never changes
            if od.duplicated(subset=other_cols).sum() > 0:
                continue

            right = od.copy()
            right["__key"] = _join_key(right, other_cols)
            right = right.dropna(subset=["__key"])
            merged["__key"] = _join_key(merged, my_cols)
            keep = [c for c in right.columns if c != "__key" and c not in other_cols and c not in merged.columns]
            right = right[["__key"] + keep].drop_duplicates("__key")
            merged = merged.merge(right, on="__key", how="left").drop(columns="__key")

    return merged, [fact] + [t for t in visited if t != fact]


_NON_MEASURE_WORDS = {"zip", "postal", "lat", "lng", "latitude", "longitude", "year", "month", "quarter", "day"}


def _is_date_series(s):
    try:
        return relationship_engine._dtype_kind(s, s.dropna(), str(s.name)) == "date"
    except Exception:
        return False


def _measures(fact_df):
    out = []
    for c in fact_df.columns:
        if not pd.api.types.is_numeric_dtype(fact_df[c]):
            continue
        if relationship_engine.is_key_name(c) or (relationship_engine.tokenize(c) & _NON_MEASURE_WORDS):
            continue
        out.append(c)
    return out


def _tokens(text):
    toks = set()
    for t in re.findall(r"[a-z0-9]+", str(text).lower()):
        if len(t) > 2:
            toks.add(t)
            if t.endswith("ies"):
                toks.add(t[:-3] + "y")
            elif t.endswith("s"):
                toks.add(t[:-1])
    return toks


def _fmt(df):
    return df.to_csv(index=False, float_format="%.2f").strip()


def _primary(measures):
    for key in ("sales", "revenue", "amount"):
        for m in measures:
            if key in m.lower():
                return m
    return measures[0] if measures else None


def _group_table(df, dims, measures, primary, profit):
    agg = {m: "sum" for m in measures}
    g = df.groupby(dims, dropna=False).agg(agg)
    g.insert(0, "Rows", df.groupby(dims, dropna=False).size())
    if primary:
        tot = g[primary].sum()
        g[f"{primary} % of total"] = (g[primary] / tot * 100) if tot else float("nan")
    if profit and primary and profit in g.columns:
        g["Margin %"] = g[profit] / g[primary].replace(0, float("nan")) * 100
    g = g.reset_index().sort_values(primary or "Rows", ascending=False)
    return g


def build_facts(tables, tree, question, max_chars=9000):
    """Exact, compact facts for the prompt. Returns (facts_text, notes)."""
    notes = []
    # Tableau-style UNION: same-schema tables (Orders + Orders Add-On) are appended, not related.
    union_map = relationship_engine.detect_union_candidates(tables)
    if union_map:
        tables = relationship_engine.apply_unions(tables, union_map)
        tree = [e for e in tree if e["Table A"] in tables and e["Table B"] in tables]
        notes.append("Unioned: " + "; ".join(f"{m} appended to {t}" for m, t in union_map.items()))
    merged, order = build_merged(tables, tree)
    if merged is None:
        return "No data.", []
    q = question.lower()
    qtok = _tokens(q)
    fact_name = order[0]
    fact_df = tables[fact_name]
    measures = _measures(fact_df)
    primary = _primary(measures)
    profit = next((m for m in measures if "profit" in m.lower()), None)

    sections = []

    # 0. model summary
    sections.append(
        "MODEL: fact table = %s (%d rows). Related: %s.%s"
        % (fact_name, len(fact_df), ", ".join(order[1:]) or "none",
           (" Unioned into a table: " + ", ".join(f"{m} -> {t}" for m, t in union_map.items()) + ".") if union_map else "")
    )

    # 1. grand totals (exact)
    tot_lines = [f"Rows: {len(merged)}"]
    for m in measures:
        s = pd.to_numeric(merged[m], errors="coerce")
        tot_lines.append(f"SUM({m}) = {s.sum():.2f}; AVG({m}) = {s.mean():.4f}; MIN = {s.min():.2f}; MAX = {s.max():.2f}")
    if primary and profit:
        sp = pd.to_numeric(merged[primary], errors="coerce").sum()
        pp = pd.to_numeric(merged[profit], errors="coerce").sum()
        if sp:
            tot_lines.append(f"{profit}/{primary} margin = {pp / sp * 100:.2f}%")
    for c in fact_df.columns:
        if (relationship_engine.is_key_name(c) or relationship_engine.tokenize(c) & {"name", "city", "state", "country", "region", "division", "mode"}) \
                and not pd.api.types.is_float_dtype(fact_df[c]):
            tot_lines.append(f"COUNTD({c}) = {fact_df[c].nunique(dropna=True)}")
    sections.append("GRAND TOTALS (exact):\n" + "\n".join(tot_lines[:40]))

    # 2. dimension candidates in merged model
    date_cols = [c for c in merged.columns if _is_date_series(merged[c])]
    time_words = {"year", "month", "quarter", "trend", "time", "date", "monthly", "yearly", "daily", "week"}
    wants_time = bool(qtok & time_words) or any(w in q for w in ("over time", "per year", "per month"))
    work = merged
    derived = []
    if date_cols and wants_time:
        pick = next((c for c in date_cols if _tokens(c) & qtok), date_cols[0])
        dt = pd.to_datetime(work[pick], errors="coerce", dayfirst=False)
        if dt.notna().mean() < 0.5:
            dt = pd.to_datetime(work[pick], errors="coerce", dayfirst=True)
        work = work.copy()
        work[f"{pick} Year"] = dt.dt.year
        work[f"{pick} Quarter"] = dt.dt.year.astype("Int64").astype(str) + "-Q" + dt.dt.quarter.astype("Int64").astype(str)
        work[f"{pick} Month"] = dt.dt.to_period("M").astype(str)
        derived = [f"{pick} Year", f"{pick} Quarter", f"{pick} Month"]

    dims = []
    for c in work.columns:
        if c in measures or c in date_cols:
            continue
        if norm(c) == "rowid" or relationship_engine.tokenize(c) & {"latitude", "longitude", "lat", "lng"}:
            continue
        # numbers that came from lookup tables (Goal, Target, Quota ...) are measures, not dimensions
        if c not in fact_df.columns and pd.api.types.is_numeric_dtype(work[c]) and not relationship_engine.is_key_name(c):
            continue
        nun = work[c].nunique(dropna=True)
        if 1 < nun <= 400 or c in derived:
            dims.append((c, nun))

    # relevance by question words
    relevant = []
    for c, nun in dims:
        ctoks = _tokens(c)
        if c in derived:
            kind = c.split()[-1].lower()
            if kind in qtok or (kind + "s") in qtok or ("monthly" in qtok and kind == "month") or ("yearly" in qtok and kind == "year") or "trend" in qtok:
                relevant.append(c)
            continue
        if ctoks & qtok:
            relevant.append(c)
    # id-like dims only if explicitly asked (e.g. "by customer id")
    if not relevant:
        small = [c for c, nun in dims if nun <= 12 and c not in derived]
        relevant = small[:3]
        if relevant:
            notes.append("No dimension named in question; showing small dimensions: " + ", ".join(relevant))

    relevant = relevant[:4]
    # single-dimension tables
    for c in relevant:
        g = _group_table(work, [c], measures, primary, profit)
        n = len(g)
        if n > 50:
            body = pd.concat([g.head(40), g.tail(10)])
            label = f"BY {c} (exact; top 40 and bottom 10 of {n} groups, sorted by {primary or 'Rows'} desc)"
        else:
            body = g
            label = f"BY {c} (exact; all {n} groups, sorted by {primary or 'Rows'} desc)"
        sections.append(label + ":\n" + _fmt(body))

    # two-dimension cross table when exactly two are asked
    if len(relevant) >= 2:
        a, b = relevant[0], relevant[1]
        if work[a].nunique() * work[b].nunique() <= 120:
            g2 = _group_table(work, [a, b], measures, primary, profit)
            sections.append(f"BY {a} x {b} (exact):\n" + _fmt(g2))

    # 3. targets vs actual - joined through the detected relationship (incl. composite keys)
    for tname, tdf in tables.items():
        tcols = [c for c in tdf.columns if "target" in c.lower() or "goal" in c.lower() or "quota" in c.lower()]
        tcols = [c for c in tcols if pd.api.types.is_numeric_dtype(tdf[c])]
        if not tcols or not primary or tname == fact_name:
            continue
        edge = next((e for e in tree if tname in (e["Table A"], e["Table B"])), None)
        if edge is None:
            continue
        if edge["Table A"] == tname:
            t_cols, o_cols = edge.get("Fields A", [edge["Field A"]]), edge.get("Fields B", [edge["Field B"]])
        else:
            t_cols, o_cols = edge.get("Fields B", [edge["Field B"]]), edge.get("Fields A", [edge["Field A"]])
        if not all(c in merged.columns for c in o_cols) or not all(c in tdf.columns for c in t_cols):
            continue
        act = merged[o_cols + [primary]].copy()
        act["__k"] = _join_key(act, o_cols)
        act = act.groupby("__k")[primary].sum().rename(f"Actual {primary}")
        t = tdf[t_cols + tcols].copy()
        t["__k"] = _join_key(tdf, t_cols)
        cmp_ = t.merge(act, left_on="__k", right_index=True, how="left").drop(columns="__k")
        for tc in tcols:
            cmp_[f"{primary}/{tc} %"] = cmp_[f"Actual {primary}"] / cmp_[tc].replace(0, float("nan")) * 100
            cmp_[f"Gap ({primary}-{tc})"] = cmp_[f"Actual {primary}"] - cmp_[tc]
        sections.append(f"ACTUAL vs TARGET from {tname} joined on {' & '.join(t_cols)} (exact):\n" + _fmt(cmp_))

    # 4. small reference tables in full
    for tname, tdf in tables.items():
        if tname == fact_name:
            continue
        if len(tdf) <= 20 and len(tdf.columns) <= 8:
            sections.append(f"TABLE {tname} (all {len(tdf)} rows):\n" + _fmt(tdf))

    # 5. columns + 3 sample rows of every table (names are exact, use them in steps)
    schema_lines = []
    for tname, tdf in tables.items():
        cols = ", ".join(f"[{c}] ({_ttype(tdf[c])})" for c in tdf.columns)
        schema_lines.append(f"{tname} ({len(tdf)} rows): {cols}")
    sections.append("TABLES AND FIELDS (use these exact names):\n" + "\n".join(schema_lines))

    text = ""
    for sec in sections:
        if len(text) + len(sec) + 2 > max_chars:
            notes.append("Some facts were cut to fit the size limit; raise it in the sidebar if the model needs more.")
            continue
        text += sec + "\n\n"
    return text.strip(), notes


def _ttype(s):
    col_name = str(s.name) if hasattr(s, "name") else ""
    if _is_date_series(s):
        return "Dimension (date)"
    if pd.api.types.is_numeric_dtype(s):
        if relationship_engine.is_key_name(col_name) or (relationship_engine.tokenize(col_name) & _NON_MEASURE_WORDS):
            return "Dimension (ID/numeric)"
        return "Measure (number)"
    return "Dimension (text)"


# --------------------------------------------------------------------------
# Answer checking
# --------------------------------------------------------------------------
_NUM_PLAIN = re.compile(r"-?\d+(?:\.\d+)?")
_NUM_THOUSANDS = re.compile(r"-?\d{1,3}(?:,\d{3})+(?!\d)(?:\.\d+)?|-?\d+(?:\.\d+)?")


def _numbers(text, thousands=False):
    """thousands=True: treat 1,234.5 as one number (answers). False: commas separate CSV cells (facts)."""
    rx = _NUM_THOUSANDS if thousands else _NUM_PLAIN
    vals = []
    for m in rx.findall(text):
        try:
            vals.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return vals


def unverified_numbers(answer, facts_text, question):
    """Numbers in the answer that appear nowhere in facts or question (possible invention)."""
    known = _numbers(facts_text) + _numbers(question, True) + _numbers(question)
    bad = []
    for v in _numbers(answer, True):
        if abs(v) < 10 or (1990 <= v <= 2100 and float(v).is_integer()):
            continue
        ok = False
        for k in known:
            tol = max(0.0051, abs(k) * 0.0006)
            if abs(v - k) <= tol or abs(round(v) - k) <= 0.51 and abs(v) >= 1000:
                ok = True
                break
        if not ok:
            bad.append(v)
    return bad[:5]
