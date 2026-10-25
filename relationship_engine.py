"""Robust, General-Purpose Tableau Relationship Detection Engine (v2).

What changed vs v1 (all of these caused wrong schemas / wrong relationships):
 * Column-type detection no longer uses substring tests ("Candidate ID" contains "date",
   "Timesheet ID" contains "time", "Amount Paid" ends with "id"). Names are split into
   words (camelCase aware) and dates must also *look* like dates.
 * Fuzzy name matching is much stricter: "Job ID" no longer matches "Job Role ID",
   "Customer ID" no longer matches "Customer Group ID". Extra words must name the table.
   Abbreviations (Cand ID = Candidate ID, Emp = Employee, Dept = Department) are understood.
 * Measures, dates and calendar columns (Year, Month ...) can never be join keys.
 * Overlap is judged by *containment* (is the smaller key set inside the larger one?),
   so an optional lookup table such as Returns (only returned orders) still connects.
 * Many-to-many is only allowed for strongly matching ID columns - never for plain
   categorical columns like Region/Category that merely repeat on both sides.
 * Spanning tree prefers real parent->child keys over many-to-many "sibling" links
   (Candidate.[Job Position ID] = Employee.[Job Position ID] is no longer chosen
   instead of linking both to Job Position).
 * Union candidates (Orders / Orders Add-On) are merged BEFORE profiling and are never
   given relationships of their own, so the model is not double counted.
 * Composite keys ignore names/dates/measures and are only used when no good single key exists.
 * Disconnected tables now explain the closest rejected candidate and why it was rejected.
"""
import datetime
import re
import warnings
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
_RAW_GENERIC = {
    "name", "date", "status", "type", "description", "desc", "notes", "note",
    "city", "state", "country", "comment", "comments", "value", "total",
    "summary", "count", "title", "gender", "email", "phone", "address", "remark",
    "remarks", "age", "flag", "year", "month", "quarter", "week", "day", "fy",
    "currency", "unit", "level", "priority",
}
_RAW_DESCRIPTIVE_LAST = {
    "name", "date", "status", "type", "description", "desc", "title", "email",
    "phone", "address", "comment", "note", "gender", "remark", "city", "state",
    "country", "time",
}
_RAW_MEASURE_WORDS = {
    "goal", "target", "sales", "profit", "revenue", "cost", "discount", "amount",
    "budget", "salary", "price", "margin", "quantity", "qty", "experience", "exp",
    "fee", "tax", "rate", "ratio", "score", "balance", "weight", "height", "latitude",
    "longitude", "lat", "lng", "percent", "pct", "stock", "units", "wage", "pay",
}
KEY_TOKENS = {"id", "code", "key", "num", "number", "no", "pk", "fk", "sku", "uid",
              "guid", "ref", "nbr", "identifier"}
DATE_TOKENS = {"date", "dt", "time", "timestamp", "datetime", "dob"}

KNOWN_ALIAS_FAMILIES = [
    {"postalcode", "zip", "zipcode", "postcode"},
    {"customerid", "custid", "clientid", "customerno", "customernumber"},
    {"productid", "prodid", "itemid", "sku", "productcode"},
    {"employeeid", "empid", "workerid", "staffid", "staffnumber", "employeeno", "employeenumber", "empno"},
    {"orderid", "ordernum", "ordernumber", "invoicenumber", "invoiceid", "orderno"},
    {"state", "province", "stateprovince"},
    {"country", "countryregion", "nation"},
    {"categoryid", "catid"},
    {"vendorid", "supplierid"},
    {"storeid", "shopid"},
    {"roleid", "jobroleid", "positionroleid"},
    {"jobid", "jobpositionid", "positionid"},
]


def norm_str(x: Any) -> str:
    """Lowercase alphanumeric only."""
    return re.sub(r"[^a-z0-9]", "", str(x).lower())


_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def split_words(text: Any) -> List[str]:
    """'EmployeeID' -> ['employee','id'];  'Job Position ID' -> ['job','position','id']."""
    return re.findall(r"[a-z0-9]+", _CAMEL.sub(" ", str(text)).lower())


def _sing(w: str) -> str:
    if w in ("ids", "nos"):
        return w[:-1]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def tokenize(text: Any) -> Set[str]:
    """Singularised word tokens of a column / table name."""
    return {_sing(w) for w in split_words(text) if len(w) > 1}


GENERIC_SING = {_sing(w) for w in _RAW_GENERIC}
DESCRIPTIVE_LAST = {_sing(w) for w in _RAW_DESCRIPTIVE_LAST}
MEASURE_SING = {_sing(w) for w in _RAW_MEASURE_WORDS}
# longer measure words are also accepted as substrings of compact names ("totalsales")
_LONG_MEASURE = [w for w in MEASURE_SING if len(w) >= 5]

# compact (no separators) key spellings such as 'empid', 'custid', 'sku'
COMPACT_KEYS = {m for g in KNOWN_ALIAS_FAMILIES for m in g
                if m.endswith(("id", "num", "number", "no", "sku", "code"))}


def is_key_name(col: Any) -> bool:
    """True if the column NAME says it is an identifier (word based, not substring based)."""
    return bool(tokenize(col) & KEY_TOKENS) or norm_str(col) in COMPACT_KEYS


def key_core(col: Any) -> Set[str]:
    return tokenize(col) - KEY_TOKENS


# --------------------------------------------------------------------------
# Token comparison helpers (tolerate abbreviations)
# --------------------------------------------------------------------------
def _is_subseq(s: str, l: str) -> bool:
    it = iter(l)
    return all(ch in it for ch in s)


def _tok_eq(a: str, b: str) -> bool:
    if a == b:
        return True
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if len(s) < 3:
        return False
    if l.startswith(s):                       # cand -> candidate, emp -> employee
        return True
    return s[0] == l[0] and len(s) >= 3 and _is_subseq(s, l)   # dept -> department, mgr -> manager


def _subset(a: Set[str], b: Set[str]) -> bool:
    return bool(a) and all(any(_tok_eq(x, y) for y in b) for x in a)


def _set_eq(a: Set[str], b: Set[str]) -> bool:
    return _subset(a, b) and _subset(b, a)


def _extra(long_core: Set[str], short_core: Set[str]) -> Set[str]:
    return {t for t in long_core if not any(_tok_eq(t, s) for s in short_core)}


# --------------------------------------------------------------------------
# Value normalisation
# --------------------------------------------------------------------------
_PLAIN_NUM = r"[+-]?\d+(?:\.\d+)?"


def norm_series(s: pd.Series) -> pd.Series:
    """Normalise values for key matching: trim, lowercase, '007'==7==7.0, '1E5' stays text."""
    try:
        text = s.astype(str).str.strip()
        out = text.str.lower()
        isnum = text.str.fullmatch(_PLAIN_NUM).fillna(False).astype(bool)
        if isnum.any():
            num = pd.to_numeric(text[isnum], errors="coerce")
            isint = (num % 1 == 0) & (num.abs() < 1e15)
            if isint.any():
                ints = num[isint].astype("int64").astype(str)
                out.loc[ints.index] = ints
            if (~isint).any():
                fl = num[~isint].astype(str)
                out.loc[fl.index] = fl
        return out.where(s.notna())
    except Exception:
        return s.astype(str).str.strip().str.lower().where(s.notna())


# --------------------------------------------------------------------------
# Column type inference
# --------------------------------------------------------------------------
_DATE_PAT = r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?\s*$"


def _looks_date(non_null: pd.Series, name: str) -> bool:
    sample = non_null.head(200)
    if len(sample) == 0:
        return False
    py_dates = sample.map(lambda v: isinstance(v, (pd.Timestamp, datetime.datetime, datetime.date)))
    if py_dates.mean() >= 0.9:
        return True
    strs = sample[sample.map(lambda v: isinstance(v, str))]
    if len(strs) < 0.9 * len(sample):
        return False
    if strs.str.match(_DATE_PAT).mean() >= 0.9:
        return True
    if tokenize(name) & DATE_TOKENS:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                parsed = pd.to_datetime(strs, errors="coerce", format="mixed")
            return bool(parsed.notna().mean() >= 0.8)
        except Exception:
            return False
    return False


def _numeric_ratio(non_null: pd.Series) -> float:
    sample = non_null.head(200)
    if len(sample) == 0:
        return 0.0
    def ok(v):
        if isinstance(v, bool):
            return False
        if isinstance(v, (int, float)):
            return True
        return bool(re.fullmatch(_PLAIN_NUM, str(v).strip()))
    return float(sample.map(ok).mean())


def _dtype_kind(s: pd.Series, non_null: pd.Series, name: str) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    if len(non_null) == 0:
        return "string"
    if _looks_date(non_null, name):
        return "date"
    if _numeric_ratio(non_null) >= 0.95:
        return "numeric"
    return "string"


def _has_fraction(non_null: pd.Series) -> bool:
    try:
        num = pd.to_numeric(non_null, errors="coerce").dropna()
        return bool(len(num) and ((num % 1) != 0).any())
    except Exception:
        return False


# --------------------------------------------------------------------------
# Table & Column Profiling
# --------------------------------------------------------------------------
def profile_table(name: str, df: pd.DataFrame) -> Dict[str, Any]:
    total_rows = len(df)
    cols: Dict[str, Dict[str, Any]] = {}

    for c in df.columns:
        s = df[c]
        non_null = s.dropna()
        non_null_count = len(non_null)
        null_count = int(s.isna().sum())
        null_rate = null_count / max(total_rows, 1)
        c_norm = norm_str(c)
        toks = tokenize(c)

        kind = _dtype_kind(s, non_null, str(c))
        key_name = is_key_name(c)

        is_measure = False
        if kind == "numeric" and not key_name:
            by_name = bool(toks & MEASURE_SING) or any(w in c_norm for w in _LONG_MEASURE)
            is_measure = by_name or _has_fraction(non_null)

        distinct = int(non_null.nunique()) if non_null_count else 0
        ratio = distinct / max(non_null_count, 1)
        unusable = is_measure or kind in ("date", "boolean")
        is_unique = bool(non_null_count >= 2 and ratio >= 0.98 and null_rate < 0.05 and not unusable)

        # alphanumeric codes like JP001, CA-2019-1001 (needs letters AND digits)
        has_id_values = False
        if non_null_count and kind == "string":
            sample = [str(v).strip() for v in non_null.head(50)]
            hits = sum(1 for v in sample
                       if re.fullmatch(r"[A-Za-z0-9_\-]{2,30}", v) and any(ch.isdigit() for ch in v)
                       and any(ch.isalpha() for ch in v))
            has_id_values = hits / max(len(sample), 1) >= 0.70

        is_id_like = (key_name or has_id_values) and distinct > 1 and not unusable
        words = [_sing(w) for w in split_words(c) if len(w) > 1]
        is_generic = bool(words) and set(words) <= GENERIC_SING and not key_name
        is_descriptive = bool(words) and words[-1] in DESCRIPTIVE_LAST and not key_name

        values_set: Set[str] = set()
        if non_null_count and not unusable:
            values_set = set(norm_series(non_null).dropna().unique())

        cols[c] = {
            "name": c, "norm_name": c_norm, "tokens": toks, "dtype_kind": kind,
            "null_count": null_count, "null_rate": round(null_rate, 4),
            "distinct_count": distinct, "non_null_count": non_null_count,
            "uniqueness_ratio": round(ratio, 4), "is_unique": is_unique,
            "is_measure": is_measure, "is_id_like": is_id_like, "is_generic": is_generic,
            "is_descriptive": is_descriptive, "is_key_name": key_name, "values_set": values_set,
        }

    single_pks = [c for c, p in cols.items() if p["is_unique"] and p["is_id_like"]]
    if not single_pks:
        single_pks = [c for c, p in cols.items()
                      if p["is_unique"] and not p["is_generic"] and not p["is_descriptive"]]

    # composite key candidates: dimension-like columns only (no names, dates, measures)
    composite_pks: List[Tuple[str, ...]] = []
    if total_rows > 1 and len(df.columns) >= 2:
        cand = [c for c, p in cols.items()
                if not p["is_measure"] and p["dtype_kind"] not in ("date", "boolean")
                and not p["is_generic"] and not p["is_descriptive"]
                and p["distinct_count"] > 1 and p["null_rate"] < 0.05
                and p["distinct_count"] < total_rows]
        cand.sort(key=lambda c: (not cols[c]["is_key_name"], cols[c]["distinct_count"]))
        cand = cand[:7]
        for i in range(len(cand)):
            for j in range(i + 1, len(cand)):
                c1, c2 = cand[i], cand[j]
                if df[[c1, c2]].dropna().drop_duplicates().shape[0] == total_rows:
                    composite_pks.append((c1, c2))

    return {
        "table_name": name, "norm_name": norm_str(name), "tokens": tokenize(name),
        "total_rows": total_rows, "columns": cols, "single_pks": single_pks,
        "primary_keys": single_pks,          # the UI reads this key
        "composite_pks": composite_pks,
    }


# --------------------------------------------------------------------------
# Semantic matching of two column names
# --------------------------------------------------------------------------
def _semantic(t1: str, c1: str, t2: str, c2: str) -> Tuple[bool, float, str, str]:
    """(matches, score, reason, strength) where strength is 'strong' or 'fuzzy'."""
    n1, n2 = norm_str(c1), norm_str(c2)
    if n1 == n2:
        return True, 1.0, f"Identical column names ('{c1}')", "strong"
    for g in KNOWN_ALIAS_FAMILIES:
        if n1 in g and n2 in g:
            return True, 0.95, f"Recognized business alias ('{c1}' <-> '{c2}')", "strong"

    if not (is_key_name(c1) and is_key_name(c2)):
        return False, 0.0, "No semantic similarity", ""

    core1, core2 = key_core(c1), key_core(c2)
    tt1, tt2 = tokenize(t1), tokenize(t2)

    if core1 and core2 and _set_eq(core1, core2):
        return True, 0.93, f"Same key entity ('{c1}' <-> '{c2}')", "strong"
    # one side is a bare 'ID' / 'Code' of the table the other column points to
    if core1 and not core2 and _subset(core1, tt2):
        return True, 0.90, f"'{c1}' references table '{t2}' (key '{c2}')", "fuzzy"
    if core2 and not core1 and _subset(core2, tt1):
        return True, 0.90, f"'{c2}' references table '{t1}' (key '{c1}')", "fuzzy"
    # 'Job ID' (table Job Position) <-> 'Job Position ID': extra words must name the owner table
    if core1 and core2:
        if _subset(core1, core2):
            extra = _extra(core2, core1)
            if extra and _subset(extra, tt1):
                return True, 0.88, f"Compatible key semantics ('{c1}' in '{t1}' <-> '{c2}')", "fuzzy"
        if _subset(core2, core1):
            extra = _extra(core1, core2)
            if extra and _subset(extra, tt2):
                return True, 0.88, f"Compatible key semantics ('{c2}' in '{t2}' <-> '{c1}')", "fuzzy"
    return False, 0.0, "No semantic similarity", ""


def check_semantic_match(t1_name: str, c1: str, t2_name: str, c2: str) -> Tuple[bool, float, str]:
    ok, score, reason, _ = _semantic(t1_name, c1, t2_name, c2)
    return ok, score, reason


def _owns_key(table: str, col: str) -> bool:
    """Column is the table's own identifier (Customers.[Customer ID], Job Position.[Job ID])."""
    core, tt = key_core(col), tokenize(table)
    return (not core) or _subset(core, tt)


# --------------------------------------------------------------------------
# Single-column relationship evaluation
# --------------------------------------------------------------------------
def evaluate_relationship(
    t1_name: str, c1: str, t2_name: str, c2: str,
    prof1: Dict[str, Any], prof2: Dict[str, Any],
    df1: Optional[pd.DataFrame] = None, df2: Optional[pd.DataFrame] = None,
    reject_log: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    p1, p2 = prof1["columns"][c1], prof2["columns"][c2]

    def reject(msg: str) -> None:
        if reject_log is not None:
            reject_log.append({"Table A": t1_name, "Field A": c1, "Table B": t2_name,
                               "Field B": c2, "reason": msg})
        return None

    # hard blocks: these can never be join keys
    if p1["is_measure"] or p2["is_measure"]:
        return None
    if "date" in (p1["dtype_kind"], p2["dtype_kind"]) or "boolean" in (p1["dtype_kind"], p2["dtype_kind"]):
        return None
    if p1["is_generic"] and p2["is_generic"]:
        return None
    if p1["distinct_count"] < 2 or p2["distinct_count"] < 2:
        return None

    is_sem, sem, sem_reason, strength = _semantic(t1_name, c1, t2_name, c2)
    if not is_sem:
        return None

    v1, v2 = p1["values_set"], p2["values_set"]
    if not v1 or not v2:
        return None
    ov = len(v1 & v2)
    if ov == 0:
        return reject("the two columns share no values")
    cov1, cov2 = ov / len(v1), ov / len(v2)
    containment = ov / min(len(v1), len(v2))      # is the smaller key set inside the larger?
    u1, u2 = p1["is_unique"], p2["is_unique"]
    keyed = p1["is_key_name"] and p2["is_key_name"]

    if u1 and not u2:
        cardinality, one_side, many_side, one_col, many_col = "ONE-to-MANY", t1_name, t2_name, c1, c2
    elif u2 and not u1:
        cardinality, one_side, many_side, one_col, many_col = "ONE-to-MANY", t2_name, t1_name, c2, c1
    elif u1 and u2:
        cardinality, one_side, many_side, one_col, many_col = "ONE-to-ONE", "Both", "Both", c1, c2
    else:
        cardinality, one_side, many_side, one_col, many_col = "MANY-to-MANY", "Many", "Many", c1, c2

    # ---- cardinality specific safety rules ---------------------------------
    if ov < 2:
        return reject("fewer than 2 matching values")
    if cardinality == "MANY-to-MANY":
        if strength != "strong" or not keyed:
            return reject("both columns repeat values and are not clear ID columns (would be a false many-to-many)")
        if containment < 0.5:
            return reject(f"only {containment:.0%} of the smaller key set is found in the other table")
    elif cardinality == "ONE-to-ONE":
        if not keyed:
            return reject("unique non-ID columns with the same name are usually unrelated")
        if containment < 0.5:
            return reject(f"only {containment:.0%} of the smaller key set is found in the other table")
    else:  # ONE-to-MANY
        if keyed:
            if containment < 0.5:
                return reject(f"only {containment:.0%} of the smaller key set is found in the other table")
        else:
            one_p = p1 if one_col == c1 and one_side == t1_name else p2
            if strength != "strong" or containment < 0.9 or one_p["uniqueness_ratio"] < 0.99:
                return reject("descriptive (non-ID) column with weak overlap")

    # ---- confidence --------------------------------------------------------
    conf = sem * 0.35 + containment * 0.35
    conf += 0.15 if (u1 or u2) else 0.08
    conf += 0.10 if (p1["is_id_like"] or p2["is_id_like"]) else 0.0
    conf += 0.05 if (p1["null_rate"] < 0.02 and p2["null_rate"] < 0.02) else 0.0
    if not keyed:
        conf = min(conf, 0.84)          # joining on a descriptive column is never "High"
    conf = min(round(conf, 3), 1.0)
    level = "High" if conf >= 0.85 else ("Medium" if conf >= 0.60 else "Low")
    status = "Confirmed" if conf >= 0.70 else "Uncertain / Suggested (Needs Review)"

    reasons = [sem_reason]
    if cardinality == "ONE-to-MANY":
        reasons.append(f"{many_side}.[{many_col}] matches {one_side}.[{one_col}] (unique key); "
                       f"{containment:.0%} of the smaller key set is found in the other table.")
    elif cardinality == "ONE-to-ONE":
        reasons.append(f"Unique keys on both sides ({ov} matching records, {containment:.0%} containment).")
    else:
        reasons.append(f"Many-to-many on a shared ID with {ov} matching keys ({containment:.0%} containment).")

    # ---- ranking -----------------------------------------------------------
    owns = (cardinality == "ONE-to-MANY" and _owns_key(one_side, one_col)) or \
           (cardinality == "ONE-to-ONE" and (_owns_key(t1_name, c1) or _owns_key(t2_name, c2)))
    score = conf * 100.0 + (15 if (p1["is_id_like"] and p2["is_id_like"]) else 0) + (12 if owns else 0)
    tier = 2 if cardinality == "MANY-to-MANY" else (0 if keyed else 1)

    return {
        "Table A": t1_name, "Field A": c1, "Table B": t2_name, "Field B": c2,
        "is_composite": False, "Fields A": [c1], "Fields B": [c2],
        "Matching sample values": ov,
        "ONE side": one_side, "MANY side": many_side, "Cardinality": cardinality,
        "Coverage": round(containment, 3), "Confidence": conf, "Confidence Level": level,
        "Key Uniqueness": f"{t1_name}.[{c1}]: {p1['uniqueness_ratio']:.1%}, {t2_name}.[{c2}]: {p2['uniqueness_ratio']:.1%}",
        "Null Rates": f"{t1_name}.[{c1}]: {p1['null_rate']:.1%}, {t2_name}.[{c2}]: {p2['null_rate']:.1%}",
        "Status": status,
        "Needs INT/STR cast": p1["dtype_kind"] != p2["dtype_kind"],
        "Initial assessment": f"{cardinality} ({status})",
        "Reason": " ".join(reasons),
        "_score": round(score, 2), "_tier": tier,
    }


# --------------------------------------------------------------------------
# Composite key relationships (e.g. Region + Segment)
# --------------------------------------------------------------------------
def _same_column(a: str, b: str) -> bool:
    na, nb = norm_str(a), norm_str(b)
    return na == nb or any(na in g and nb in g for g in KNOWN_ALIAS_FAMILIES)


def _composite_keys(df: pd.DataFrame, cols: List[str]) -> pd.Series:
    frame = pd.concat([norm_series(df[c]) for c in cols], axis=1).dropna()
    if frame.empty:
        return pd.Series([], dtype=str)
    key = frame.iloc[:, 0]
    for i in range(1, frame.shape[1]):
        key = key + "\x1f" + frame.iloc[:, i]
    return key


def detect_composite_relationships(
    t1_name: str, prof1: Dict[str, Any], df1: pd.DataFrame,
    t2_name: str, prof2: Dict[str, Any], df2: pd.DataFrame,
) -> List[Dict[str, Any]]:
    options = []
    if prof2["composite_pks"]:
        options.append((t2_name, prof2["composite_pks"], t1_name, df2, df1, prof1))
    if prof1["composite_pks"]:
        options.append((t1_name, prof1["composite_pks"], t2_name, df1, df2, prof2))

    found: List[Dict[str, Any]] = []
    for p_table, comps, c_table, p_df, c_df, c_prof in options:
        for pair in comps:
            matched, used = [], set()
            for col in pair:
                m = next((cc for cc in c_df.columns
                          if cc not in used and _same_column(col, cc)
                          and not c_prof["columns"][cc]["is_measure"]
                          and c_prof["columns"][cc]["dtype_kind"] not in ("date", "boolean")), None)
                if m is None:
                    break
                used.add(m)
                matched.append((col, m))
            if len(matched) != len(pair):
                continue
            p_cols, c_cols = [m[0] for m in matched], [m[1] for m in matched]
            p_keys, c_keys = _composite_keys(p_df, p_cols), _composite_keys(c_df, c_cols)
            p_set, c_set = set(p_keys.unique()), set(c_keys.unique())
            ov = len(p_set & c_set)
            if ov < 2 or not p_set or not c_set:
                continue
            containment = ov / min(len(p_set), len(c_set))
            if containment < 0.6:
                continue
            c_unique = len(c_keys) == len(c_set)
            conf = min(round(0.75 + containment * 0.20, 3), 1.0)
            fields_p = " & ".join(f"[{c}]" for c in p_cols)
            fields_c = " & ".join(f"[{c}]" for c in c_cols)
            found.append({
                "Table A": c_table, "Field A": ", ".join(c_cols),
                "Table B": p_table, "Field B": ", ".join(p_cols),
                "is_composite": True, "Fields A": c_cols, "Fields B": p_cols,
                "Matching sample values": ov,
                "ONE side": "Both" if c_unique else p_table,
                "MANY side": "Both" if c_unique else c_table,
                "Cardinality": "ONE-to-ONE" if c_unique else "ONE-to-MANY",
                "Coverage": round(containment, 3), "Confidence": conf,
                "Confidence Level": "High" if conf >= 0.85 else ("Medium" if conf >= 0.60 else "Low"),
                "Key Uniqueness": f"{p_table}.[composite]: 100% unique",
                "Null Rates": "0.0%", "Status": "Confirmed", "Needs INT/STR cast": False,
                "Initial assessment": "Composite key relationship",
                "Reason": f"Composite key {fields_c} = {fields_p} ({ov} combinations match, {containment:.0%} containment).",
                "_score": round(conf * 110.0, 2), "_tier": 0, "_parent_size": len(p_set),
            })
    if len(found) > 1:      # same table pair found from both directions: keep the larger parent
        found.sort(key=lambda r: -r["_parent_size"])
        found = found[:1]
    return found


# --------------------------------------------------------------------------
# Union candidates (same schema, appended rows) - merged BEFORE profiling
# --------------------------------------------------------------------------
def detect_union_candidates(tables: Dict[str, pd.DataFrame]) -> Dict[str, str]:
    names = list(tables)
    raw: Dict[str, str] = {}
    for i in range(len(names)):
        n1 = names[i]
        cols1 = [norm_str(c) for c in tables[n1].columns]
        for j in range(i + 1, len(names)):
            n2 = names[j]
            cols2 = [norm_str(c) for c in tables[n2].columns]
            common = set(cols1) & set(cols2)
            if len(common) < 3:
                continue
            if len(common) / len(set(cols1)) < 0.9 or len(common) / len(set(cols2)) < 0.9:
                continue
            # evidence it is an append and not two different entities with similar columns
            share_name = bool(tokenize(n1) & tokenize(n2))
            same_order = cols1 == cols2
            if not (share_name or same_order):
                continue
            smaller, larger = (n1, n2) if len(tables[n1]) <= len(tables[n2]) else (n2, n1)
            raw[smaller] = larger
    resolved: Dict[str, str] = {}
    for k, v in raw.items():          # follow chains (A->B->C  =>  A->C)
        seen = {k}
        while v in raw and v not in seen:
            seen.add(v)
            v = raw[v]
        resolved[k] = v
    return resolved


def apply_unions(tables: Dict[str, pd.DataFrame], union_candidates: Dict[str, str]) -> Dict[str, pd.DataFrame]:
    """Return tables with union members appended onto their target (members removed)."""
    if not union_candidates:
        return dict(tables)
    out = {n: d for n, d in tables.items() if n not in union_candidates}
    for target in set(union_candidates.values()):
        parts = [tables[target]] + [tables[m] for m, t in union_candidates.items() if t == target]
        norm_map = {norm_str(c): c for c in tables[target].columns}
        aligned = []
        for d in parts:
            d2 = d.rename(columns={c: norm_map.get(norm_str(c), c) for c in d.columns})
            aligned.append(d2.loc[:, ~d2.columns.duplicated()])
        out[target] = pd.concat(aligned, ignore_index=True, sort=False)
    return out


# --------------------------------------------------------------------------
# Main engine
# --------------------------------------------------------------------------
def detect_all_relationships(tables: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    table_names = list(tables.keys())
    union_candidates = detect_union_candidates(tables)
    work = apply_unions(tables, union_candidates)
    work_names = list(work.keys())

    profiles = {n: profile_table(n, work[n]) for n in work_names}
    for m in union_candidates:                       # UI cards still want a profile for members
        profiles[m] = profile_table(m, tables[m])

    candidate_pairs: List[Dict[str, Any]] = []
    near_misses: List[Dict[str, str]] = []

    for i in range(len(work_names)):
        n1, df1, prof1 = work_names[i], work[work_names[i]], profiles[work_names[i]]
        for j in range(i + 1, len(work_names)):
            n2, df2, prof2 = work_names[j], work[work_names[j]], profiles[work_names[j]]

            singles: List[Dict[str, Any]] = []
            for c1 in df1.columns:
                for c2 in df2.columns:
                    r = evaluate_relationship(n1, c1, n2, c2, prof1, prof2, df1, df2, near_misses)
                    if r is not None:
                        singles.append(r)
            candidate_pairs.extend(singles)

            # composite keys only when no good single key links these two tables
            has_good_single = any(s["_tier"] == 0 and s["Confidence"] >= 0.70 and s["Cardinality"] != "MANY-to-MANY"
                                  for s in singles)
            if not has_good_single:
                candidate_pairs.extend(detect_composite_relationships(n1, prof1, df1, n2, prof2, df2))

    # real parent->child keys first, descriptive joins next, many-to-many last
    candidate_pairs.sort(key=lambda p: (p["_tier"], -p["_score"]))

    parent = {n: n for n in work_names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    tree: List[Dict[str, Any]] = []
    for p in candidate_pairs:
        if p["Confidence"] < 0.50:
            continue
        a, b = find(p["Table A"]), find(p["Table B"])
        if a != b:
            parent[a] = b
            tree.append(p)

    # bridge / junction tables: link >=2 parents, hold no measures and (almost) no attributes
    junction_tables: Dict[str, List[str]] = {}
    for n in work_names:
        parents = []
        for p in tree:
            if p.get("MANY side") == n:
                parents.append(p["Table A"] if p["Table B"] == n else p["Table B"])
        if len(parents) < 2:
            continue
        cols = profiles[n]["columns"]
        has_measure = any(c["is_measure"] for c in cols.values())
        attrs = [c for c in cols.values()
                 if not c["is_key_name"] and not c["is_measure"] and c["dtype_kind"] != "date"]
        if not has_measure and len(attrs) <= 2:
            junction_tables[n] = parents

    connected = set()
    for e in tree:
        connected.add(e["Table A"])
        connected.add(e["Table B"])

    disconnected: Dict[str, str] = {}
    for n in table_names:
        if n in union_candidates:
            t = union_candidates[n]
            disconnected[n] = (f"Union candidate: has the same columns as '{t}'. In Tableau, drag '{n}' "
                               f"below '{t}' to Union the rows, then relate the union to the other tables.")
        elif n not in connected:
            mine = [m for m in near_misses if m["Table A"] == n or m["Table B"] == n]
            weak = [p for p in candidate_pairs if p["Table A"] == n or p["Table B"] == n]
            if weak:
                b = weak[0]
                other = b["Table B"] if b["Table A"] == n else b["Table A"]
                disconnected[n] = (f"Uncertain link with '{other}' on [{b['Field A']}] = [{b['Field B']}] "
                                   f"(confidence {b['Confidence']:.0%}); not safe enough to add automatically. "
                                   f"Verify manually.")
            elif mine:
                b = mine[0]
                other = b["Table B"] if b["Table A"] == n else b["Table A"]
                disconnected[n] = (f"No safe relationship: closest candidate was '{other}' on "
                                   f"[{b['Field A']}] = [{b['Field B']}], rejected because {b['reason']}. "
                                   f"Link manually if you know they are related.")
            else:
                disconnected[n] = "No relationship detected: no candidate key has sufficient matching values with any table."

    return {
        "pairs": candidate_pairs, "tree": tree, "profiles": profiles,
        "union_candidates": union_candidates, "disconnected": disconnected,
        "connected_tables": connected, "junction_tables": junction_tables,
        "rejected": near_misses,
    }


# --------------------------------------------------------------------------
# Guide text
# --------------------------------------------------------------------------
def generate_tableau_guide(tree: List[Dict[str, Any]], disconnected: Dict[str, str],
                           junction_tables: Optional[Dict[str, List[str]]] = None) -> str:
    lines = [
        "TABLEAU DATA MODEL - RELATIONSHIP GUIDE",
        "Open Tableau > Data Source. Connect your first table, then drag each related table next to it.",
        "-" * 70,
    ]
    if not tree and not disconnected:
        lines.append("Only one table loaded. No relationship needed.")
        return "\n".join(lines)

    for i, p in enumerate(tree, 1):
        if p.get("is_composite"):
            clause = " AND ".join(f"{p['Table A']}.[{ca}] = {p['Table B']}.[{cb}]"
                                  for ca, cb in zip(p["Fields A"], p["Fields B"]))
            match_str = f"Match {clause}"
        else:
            match_str = f"Match {p['Table A']}.[{p['Field A']}] = {p['Table B']}.[{p['Field B']}]"

        card = p["Cardinality"]
        if p["ONE side"] not in ("Both", "Many"):
            card += f" (ONE side: {p['ONE side']})"

        lvl = p.get("Confidence Level", "High" if p.get("Confidence", 1.0) >= 0.85 else "Medium")
        pct = p.get("Confidence", 1.0)
        flag = (f"[Confirmed | Confidence: {lvl} ({pct:.0%})]" if p["Status"] == "Confirmed"
                else f"[Uncertain / Suggested - Requires Review | Confidence: {lvl} ({pct:.0%})]")
        line = (f"{i}. Drag {p['Table B']} next to {p['Table A']}.\n"
                f"   {match_str}\n"
                f"   Relationship: {card} | {flag}\n"
                f"   Key Uniqueness: {p.get('Key Uniqueness', '')} | Key containment: {p.get('Coverage', 1.0):.0%}\n"
                f"   Why: {p['Reason']}")
        if p.get("Needs INT/STR cast"):
            line += "\n   Note: Data types differ. Use relationship calculation (e.g. INT([Field]))."
        lines.append(line)
        lines.append("")

    if junction_tables:
        lines.append("-" * 70)
        lines.append("DETECTED BRIDGE / JUNCTION TABLES:")
        for jt, parents in junction_tables.items():
            lines.append(f"- {jt}: bridge table connecting: {', '.join(parents)}")
        lines.append("")

    if disconnected:
        lines.append("-" * 70)
        lines.append("DISCONNECTED TABLES & NOTICES:")
        for tbl, exp in disconnected.items():
            lines.append(f"- {tbl}: {exp}")
        lines.append("")

    lines.append("Tableau Tip: Use Relationships (noodles) for related tables. Never relate on generic columns.")
    return "\n".join(lines)
