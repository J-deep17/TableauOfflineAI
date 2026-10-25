"""Smart loader and cleaner for Tableau Offline AI.

Handles:
1. Multi-sheet Excel files (.xlsx, .xlsm, .xls): Reads every sheet as its own table.
2. Header detection: Finds real headers below title rows (e.g., 'SuperStore Report 1-1-2019')
   and skips banner, blank, and metadata rows.
3. Data cleaning: Drops empty rows/columns, removes summary/total rows at the bottom,
   cleans column names (no 'Unnamed: X', no duplicate names), and parses numeric currency formats.
4. Detailed audit reporting: Records exactly what changed for each table.
"""
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from relationship_engine import is_key_name, tokenize

# Keywords that commonly appear in table header rows
HEADER_KEYWORDS = {
    "id", "name", "date", "time", "sales", "profit", "amount", "qty", "quantity",
    "discount", "cost", "price", "total", "category", "subcategory", "sub-category",
    "segment", "region", "state", "city", "country", "postal", "zip", "zipcode",
    "customer", "product", "order", "status", "type", "mode", "address", "code",
    "year", "month", "quarter", "day", "rate", "ratio", "margin", "target", "revenue",
    "value", "number", "num", "percent", "pct", "department", "dept", "manager",
    "person", "group", "unit", "units", "ship", "shipping", "return", "returned",
    "description", "desc", "key", "brand", "item", "row", "rowid", "vendor",
    "latitude", "longitude", "lat", "lng", "store", "quota", "budget", "actual"
}

# Words indicating a bottom summary row to remove
SUMMARY_ROW_WORDS = ("grand total", "total", "subtotal", "summary", "average", "overall")

# Currency and number formatting regex
_CURRENCY_RE = re.compile(r"^\s*[$€£¥₹]?\s*\(?-?\s*[$€£¥₹]?\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*\)?\s*$")


def _is_empty_cell(val: Any) -> bool:
    if val is None or pd.isna(val):
        return True
    s = str(val).strip()
    return s == "" or s.lower() in ("nan", "none", "null", "nat")


def _is_number_like(val: Any) -> bool:
    if isinstance(val, (int, float)) and not pd.isna(val):
        return True
    s = str(val).strip()
    if not s:
        return False
    # Clean currency/thousands formatting
    s = re.sub(r"[\$,€£¥₹\s]", "", s)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        float(s)
        return True
    except ValueError:
        return False


def _to_clean_number(val: Any) -> Any:
    if isinstance(val, (int, float)):
        return val
    s = str(val).strip()
    if not s:
        return None
    is_neg = False
    if s.startswith("(") and s.endswith(")"):
        is_neg = True
        s = s[1:-1]
    s = re.sub(r"[\$,€£¥₹\s]", "", s)
    try:
        n = float(s)
        return -n if is_neg else n
    except ValueError:
        return val


def find_header_row(raw_df: pd.DataFrame) -> Tuple[int, List[str]]:
    """Scan the top rows of raw_df to determine the real header row index.

    Returns (best_row_index, list_of_reasons_or_notes).
    """
    if raw_df.empty:
        return 0, ["Empty table"]

    max_scan = min(30, len(raw_df))
    num_cols = raw_df.shape[1]
    if num_cols == 0:
        return 0, ["No columns"]

    scores = []
    notes_per_row = {}

    for r in range(max_scan):
        row_vals = [raw_df.iat[r, c] for c in range(num_cols)]
        non_empty = [v for v in row_vals if not _is_empty_cell(v)]
        count = len(non_empty)

        if count == 0:
            scores.append(-9999.0)
            notes_per_row[r] = "Completely empty row"
            continue

        fill_ratio = count / num_cols
        # Check string vs numeric/date
        str_cells = [str(v).strip() for v in non_empty if not isinstance(v, (int, float)) or isinstance(v, bool)]
        # Check how many are numbers
        num_cells = [v for v in non_empty if _is_number_like(v)]
        str_ratio = len(str_cells) / count
        num_ratio = len(num_cells) / count

        # Uniqueness of values (headers should be unique)
        lower_vals = [s.lower() for s in str_cells]
        unique_ratio = len(set(lower_vals)) / max(len(lower_vals), 1)

        # Keyword match
        matched_kw = 0
        for s in lower_vals:
            norm_word = re.sub(r"[^a-z0-9]", "", s)
            if any(kw == norm_word or norm_word.endswith(kw) or norm_word.startswith(kw) for kw in HEADER_KEYWORDS):
                matched_kw += 1

        # Average cell character length (headers are usually short; titles or disclaimers are long)
        avg_len = sum(len(s) for s in str_cells) / max(len(str_cells), 1)

        score = 0.0
        score += fill_ratio * 45.0
        score += str_ratio * 35.0
        score += unique_ratio * 25.0
        score += min(matched_kw, 10) * 8.0

        # Title/metadata row penalties:
        if count <= 1 and num_cols >= 3:
            # Single non-empty cell in wide row: classic title row (e.g. "SuperStore Report 1-1-2019")
            score -= 300.0
            notes_per_row[r] = f"Title row ('{str_cells[0][:50]}')"
        elif fill_ratio < 0.25 and num_cols >= 4:
            score -= 150.0
            notes_per_row[r] = "Sparse row (< 25% filled)"
        elif avg_len > 60:
            score -= 80.0
            notes_per_row[r] = "Long text banner / disclaimer"

        # Check raw float cells in header candidate
        float_count = sum(1 for v in non_empty if isinstance(v, float) and not pd.isna(v) and not v.is_integer())
        score -= float_count * 20.0

        # Contrast with subsequent rows:
        if r + 1 < len(raw_df):
            next_vals = [raw_df.iat[r + 1, c] for c in range(num_cols)]
            next_non_empty = [v for v in next_vals if not _is_empty_cell(v)]
            next_nums = [v for v in next_non_empty if _is_number_like(v)]
            # If this row is mostly strings, but next row has real numbers or dates, strong header signal
            if str_ratio >= 0.7 and len(next_nums) >= 1:
                score += 40.0
            if len(next_non_empty) >= count * 0.8:
                score += 15.0

        scores.append(score)
        if r not in notes_per_row:
            notes_per_row[r] = f"Candidate (fill={fill_ratio:.0%}, strings={str_ratio:.0%}, kw={matched_kw})"

    best_r = int(pd.Series(scores).idxmax()) if scores else 0
    return best_r, [notes_per_row.get(r, "") for r in range(best_r)]


def clean_dataframe(
    raw_df: pd.DataFrame,
    table_label: str = "Table",
    sheet_name: Optional[str] = None,
    file_name: Optional[str] = None
) -> Tuple[pd.DataFrame, List[str]]:
    """Clean a raw DataFrame (loaded with header=None).

    Detects headers, removes title/metadata rows, strips whitespace, drops empty
    columns/rows, removes summary rows, and parses numeric columns.
    Returns (cleaned_df, cleaning_actions_log).
    """
    log: List[str] = []
    raw_rows, raw_cols = raw_df.shape

    if raw_df.empty or raw_rows == 0 or raw_cols == 0:
        return pd.DataFrame(), [f"Table '{table_label}' is completely empty."]

    # Step 1: Detect header row
    header_idx, skipped_notes = find_header_row(raw_df)

    if header_idx > 0:
        skipped_titles = []
        for r in range(header_idx):
            non_empty = [str(raw_df.iat[r, c]).strip() for c in range(raw_cols) if not _is_empty_cell(raw_df.iat[r, c])]
            if non_empty:
                skipped_titles.append(f"'{non_empty[0][:45]}'")
        titles_str = f" (including {', '.join(skipped_titles)})" if skipped_titles else ""
        log.append(f"Found real header at row {header_idx + 1}; skipped {header_idx} title/metadata row(s){titles_str}.")
    else:
        log.append("Header found at row 1 (standard layout).")

    # Step 2: Extract header names and data slice
    header_raw = [raw_df.iat[header_idx, c] for c in range(raw_cols)]
    data_df = raw_df.iloc[header_idx + 1:].copy()

    # Step 3: Column name normalization & unnamed handling
    new_cols = []
    col_counts: Dict[str, int] = {}
    dropped_empty_cols = []
    renamed_unnamed = []

    for c_idx, h_val in enumerate(header_raw):
        s_val = "" if _is_empty_cell(h_val) else str(h_val).strip()
        # Clean newlines and consecutive whitespace
        s_val = re.sub(r"\s+", " ", s_val)

        # Check if the column is entirely empty
        col_series = data_df.iloc[:, c_idx]
        is_all_empty = col_series.apply(_is_empty_cell).all()

        if is_all_empty and (not s_val or s_val.lower().startswith("unnamed:")):
            dropped_empty_cols.append(c_idx)
            continue

        if not s_val or s_val.lower().startswith("unnamed:"):
            # Has data, but no header name
            s_val = f"Column_{c_idx + 1}"
            renamed_unnamed.append(s_val)

        # De-duplicate column names
        base_name = s_val
        if base_name in col_counts:
            col_counts[base_name] += 1
            s_val = f"{base_name} ({col_counts[base_name]})"
            log.append(f"Renamed duplicate column '{base_name}' to '{s_val}'.")
        else:
            col_counts[base_name] = 1

        new_cols.append((c_idx, s_val))

    if dropped_empty_cols:
        log.append(f"Dropped {len(dropped_empty_cols)} completely empty column(s) without headers.")
    if renamed_unnamed:
        log.append(f"Assigned names to unnamed columns with data: {', '.join(renamed_unnamed[:5])}.")

    # Apply kept columns
    keep_indices = [c[0] for c in new_cols]
    final_cols = [c[1] for c in new_cols]
    data_df = data_df.iloc[:, keep_indices]
    data_df.columns = final_cols

    # Step 4: Drop completely empty rows
    before_rows = len(data_df)
    data_df = data_df.dropna(how="all")
    # Also drop rows where all values are empty strings
    data_df = data_df[~data_df.apply(lambda r: all(_is_empty_cell(v) for v in r), axis=1)]
    dropped_empty_rows = before_rows - len(data_df)
    if dropped_empty_rows > 0:
        log.append(f"Dropped {dropped_empty_rows} empty row(s).")

    # Step 5: Check and remove trailing summary / total row(s)
    # E.g. row at bottom starting with 'Total', 'Grand Total', 'Summary'
    removed_summary_rows = 0
    while len(data_df) > 0:
        last_row = data_df.iloc[-1]
        first_non_empty = None
        for v in last_row:
            if not _is_empty_cell(v):
                first_non_empty = str(v).strip()
                break
        if first_non_empty:
            low_fne = first_non_empty.lower()
            if any(low_fne == w or low_fne.startswith(w + " ") or low_fne.startswith(w + ":") for w in SUMMARY_ROW_WORDS):
                data_df = data_df.iloc[:-1]
                removed_summary_rows += 1
                log.append(f"Removed summary/total row from bottom: '{first_non_empty}'.")
                continue
        break

    # Step 6: Clean values in string columns and detect formatted numeric columns
    converted_numeric = []
    trimmed_cols = 0
    for col in data_df.columns:
        s = data_df[col]
        non_null = s.dropna()
        if len(non_null) == 0:
            continue

        # Check if values are strings that need trimming
        if non_null.apply(lambda x: isinstance(x, str)).any():
            data_df[col] = s.apply(lambda x: x.strip() if isinstance(x, str) else x)
            trimmed_cols += 1

        # Check for currency or numbers stored as strings (e.g., "$1,234.56" or "(450.00)")
        # word based (not substring): "Candidate" / "Amount Paid" must not count as ID columns
        is_id_field = is_key_name(col) or bool(tokenize(col) & {"zip", "postal", "phone", "mobile", "pin", "pincode"})
        if not is_id_field and not pd.api.types.is_numeric_dtype(data_df[col]):
            sample = [v for v in non_null if not _is_empty_cell(v)][:100]
            if sample:
                num_matches = sum(1 for v in sample if _is_number_like(v))
                if num_matches / len(sample) >= 0.80:
                    cleaned_num = s.apply(_to_clean_number)
                    data_df[col] = pd.to_numeric(cleaned_num, errors="coerce")
                    converted_numeric.append(col)

    # Step 7: Auto-derive business metrics if missing
    # E.g. When a table has quantity and unit price, but lacks a Total Sales/Revenue column
    has_sales_col = any(
        re.search(r"\b(sales|revenue|total_amount|total_sales|total_bill|line_total|amount)\b", re.sub(r"[^a-z0-9]", " ", str(c).lower()))
        for c in data_df.columns
    )
    if not has_sales_col:
        qty_col = next((c for c in data_df.columns if pd.api.types.is_numeric_dtype(data_df[c]) and re.search(r"\b(qty|quantity|units|unit_count)\b", re.sub(r"[^a-z0-9]", " ", str(c).lower()))), None)
        price_col = next((c for c in data_df.columns if pd.api.types.is_numeric_dtype(data_df[c]) and re.search(r"\b(unit_price|price|rate|cost)\b", re.sub(r"[^a-z0-9]", " ", str(c).lower()))), None)
        if qty_col and price_col and qty_col != price_col:
            data_df["Total Sales"] = (data_df[qty_col].fillna(0) * data_df[price_col].fillna(0)).round(2)
            log.append(f"Auto-calculated 'Total Sales' from '{qty_col}' * '{price_col}' for accurate financial analysis.")

    final_rows, final_cols_count = data_df.shape
    log.append(f"Result: {final_rows:,} rows and {final_cols_count} columns ready.")
    return data_df.reset_index(drop=True), log


def smart_load_file(path: str) -> List[Dict[str, Any]]:
    """Load an Excel or CSV file.

    For Excel (.xlsx, .xlsm, .xls), loads EVERY sheet as its own table.
    For CSV, loads the file with encoding fallbacks and auto-cleaning.

    Returns a list of table dictionaries:
    [
        {
            "name": table_name,
            "df": cleaned_df,
            "report": list_of_log_strings,
            "source_path": path,
            "sheet_name": sheet_name or None,
            "raw_shape": (r, c),
            "clean_shape": (r, c),
        },
        ...
    ]
    """
    results: List[Dict[str, Any]] = []
    file_name = os.path.basename(path)
    file_stem, ext = os.path.splitext(file_name)
    low_ext = ext.lower()

    if low_ext in (".xlsx", ".xlsm", ".xls"):
        # Excel: inspect sheets
        excel_engine = "openpyxl" if low_ext in (".xlsx", ".xlsm") else None
        excel = None
        try:
            try:
                excel = pd.ExcelFile(path, engine=excel_engine)
            except Exception:
                excel = pd.ExcelFile(path)

            sheet_names = excel.sheet_names
            multi_sheet = len(sheet_names) > 1

            for sheet in sheet_names:
                try:
                    # Read with header=None to preserve raw title rows for smart detection
                    try:
                        raw_df = pd.read_excel(excel, sheet_name=sheet, header=None, engine=excel_engine)
                    except Exception:
                        raw_df = pd.read_excel(excel, sheet_name=sheet, header=None)

                    # Skip completely blank sheets
                    if raw_df.empty or raw_df.dropna(how="all").empty:
                        continue

                    # Determine table name
                    if multi_sheet:
                        table_name = str(sheet).strip()
                    else:
                        low_sheet = str(sheet).strip().lower()
                        if low_sheet in ("sheet1", "sheet 1", "feuil1", "tabelle1", "hoja1", "data", "table1"):
                            table_name = file_stem
                        else:
                            table_name = str(sheet).strip()

                    cleaned_df, report = clean_dataframe(
                        raw_df,
                        table_label=f"{file_name} [{sheet}]",
                        sheet_name=sheet,
                        file_name=file_name
                    )

                    if cleaned_df.empty:
                        continue

                    results.append({
                        "name": table_name,
                        "df": cleaned_df,
                        "report": report,
                        "source_path": path,
                        "sheet_name": sheet,
                        "raw_shape": raw_df.shape,
                        "clean_shape": cleaned_df.shape,
                    })
                except Exception as e:
                    # If one sheet fails, record error but continue loading other sheets
                    results.append({
                        "name": f"{file_stem} - {sheet}",
                        "df": pd.DataFrame(),
                        "report": [f"Failed to read sheet '{sheet}': {e}"],
                        "source_path": path,
                        "sheet_name": sheet,
                        "raw_shape": (0, 0),
                        "clean_shape": (0, 0),
                        "error": str(e),
                    })
        finally:
            if excel is not None:
                try:
                    excel.close()
                except Exception:
                    pass

    elif low_ext == ".csv":
        # CSV loading with encoding fallbacks
        raw_df = None
        last_err = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                # Load with header=None to allow smart header detection
                df_candidate = pd.read_csv(path, header=None, encoding=enc)
                if df_candidate.shape[1] == 1:
                    # Might be semicolon or tab delimited
                    df_candidate = pd.read_csv(path, header=None, encoding=enc, sep=None, engine="python")
                raw_df = df_candidate
                break
            except Exception as e:
                last_err = e

        if raw_df is None:
            raise last_err or ValueError(f"Could not decode CSV: {file_name}")

        cleaned_df, report = clean_dataframe(
            raw_df,
            table_label=file_name,
            sheet_name=None,
            file_name=file_name
        )

        results.append({
            "name": file_stem,
            "df": cleaned_df,
            "report": report,
            "source_path": path,
            "sheet_name": None,
            "raw_shape": raw_df.shape,
            "clean_shape": cleaned_df.shape,
        })
    else:
        raise ValueError(f"Unsupported file type '{ext}'. Supported: CSV, XLSX, XLSM, XLS")

    return results
