"""
excel-sidecar: FastAPI service for Excel/CSV analysis
Mounts the Open WebUI uploads volume and processes files directly by path.

Endpoints:
  GET  /health       -- liveness check
  POST /analyze      -- shape, column types, null counts, numeric stats + sums
  POST /query        -- filter, group, aggregate
  POST /to-markdown  -- render as markdown table
  POST /execute      -- natural language -> pandas code gen -> execute -> result
"""

import os
import io
import json
import re
import textwrap
import traceback
from pathlib import Path
from typing import Optional

import pandas as pd
import requests as http_requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Excel Sidecar", version="2.0.0")

UPLOADS_BASE = Path(os.getenv("UPLOADS_DIR", "/app/backend/data/uploads"))
LLAMA_URL    = os.getenv("LLAMA_URL", "http://llamacpp-llama:8001/v1/chat/completions")
LLAMA_MODEL  = os.getenv("LLAMA_MODEL", "llama-3.1-8b-instruct")


# ── helpers ───────────────────────────────────────────────────────────────────

def resolve_path(filename: str) -> Path:
    """
    Resolve a filename to an absolute path under UPLOADS_BASE.
    Handles three cases:
      1. Exact match (absolute or relative path)
      2. UUID-prefixed file: Open WebUI stores files as <uuid> with no extension
         when process=false -- search for a file whose name starts with the UUID
      3. Display name match: search all files for one whose name contains the
         stem of the requested filename (case-insensitive)
    """
    p = Path(filename)

    # case 1: exact match
    resolved = p if p.is_absolute() else UPLOADS_BASE / p
    if resolved.exists():
        return resolved

    # case 2: UUID prefix match -- filename IS a UUID, file stored without extension
    candidates = list(UPLOADS_BASE.iterdir()) if UPLOADS_BASE.exists() else []
    stem = p.stem  # e.g. "155e9d67-e758-42bb-ae5e-2fa3219b4de3"
    for f in candidates:
        if f.name.startswith(stem):
            return f

    # case 3: fuzzy display-name match -- model passed "foo.xlsx", file stored as UUID
    # match any file whose stem contains the requested stem (case-insensitive)
    lower_stem = p.stem.lower()
    for f in candidates:
        if lower_stem in f.name.lower():
            return f

    # case 4: scan for files with matching extension as last resort
    ext = p.suffix.lower()
    if ext:
        ext_matches = [f for f in candidates if f.suffix.lower() == ext]
        if len(ext_matches) == 1:
            return ext_matches[0]

    raise HTTPException(
        status_code=404,
        detail=f"File not found: '{filename}'. Available: {[f.name for f in candidates[:10]]}"
    )


def load_file(path: Path, sheet: Optional[str] = None) -> pd.DataFrame:
    """Load spreadsheet and drop completely empty rows (fixes Excel trailing blanks)."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls", ".xlsm"):
        df = pd.read_excel(path, sheet_name=sheet or 0)
    elif suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix == ".tsv":
        df = pd.read_csv(path, sep="\t")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
    return df.dropna(how="all").reset_index(drop=True)


def safe_json(obj):
    if isinstance(obj, dict):
        return {k: safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [safe_json(i) for i in obj]
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(obj, "item"):
        return obj.item()
    return obj


def schema_summary(df: pd.DataFrame) -> str:
    lines = [f"DataFrame with {len(df)} rows and {len(df.columns)} columns.", "Columns:"]
    for col in df.columns:
        dtype = str(df[col].dtype)
        sample = df[col].dropna().iloc[:3].tolist() if not df[col].dropna().empty else []
        lines.append(f"  - '{col}' ({dtype}), e.g. {sample}")
    return "\n".join(lines)


def extract_code(text: str) -> str:
    match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def call_llama(messages: list) -> str:
    try:
        resp = http_requests.post(
            LLAMA_URL,
            json={"model": LLAMA_MODEL, "messages": messages, "temperature": 0.0, "max_tokens": 512},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Code gen model error: {e}")


def run_pandas_code(code: str, df: pd.DataFrame) -> str:
    namespace = {"df": df.copy(), "pd": pd, "result": None}
    exec(compile(code, "<generated>", "exec"), namespace)
    result = namespace.get("result")
    if result is None:
        raise ValueError("Code did not assign anything to `result`.")
    if isinstance(result, pd.DataFrame):
        return result.to_markdown(index=False)
    if isinstance(result, pd.Series):
        return result.to_string()
    return str(result)


# ── request models ────────────────────────────────────────────────────────────

class FileRequest(BaseModel):
    filename: str
    sheet: Optional[str] = None

class QueryRequest(BaseModel):
    filename: str
    sheet: Optional[str] = None
    columns: Optional[list] = None
    filters: Optional[dict] = None
    group_by: Optional[str] = None
    agg: Optional[str] = "sum"
    limit: Optional[int] = 50

class ExecuteRequest(BaseModel):
    filename: str
    question: str
    sheet: Optional[str] = None


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(req: FileRequest):
    path = resolve_path(req.filename)
    df = load_file(path, req.sheet)

    sheet_names = []
    if path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
        sheet_names = pd.ExcelFile(path).sheet_names

    col_info = {}
    for col in df.columns:
        entry = {
            "dtype": str(df[col].dtype),
            "nulls": int(df[col].isna().sum()),
            "unique": int(df[col].nunique()),
        }
        if pd.api.types.is_numeric_dtype(df[col]):
            entry["sum"] = safe_json(df[col].sum())
        col_info[col] = entry

    numeric = df.select_dtypes(include="number")
    stats = safe_json(numeric.describe().to_dict()) if not numeric.empty else {}

    return safe_json({
        "filename": path.name,
        "rows": len(df),
        "columns": len(df.columns),
        "sheet_names": sheet_names,
        "column_info": col_info,
        "numeric_stats": stats,
    })


@app.post("/query")
def query(req: QueryRequest):
    path = resolve_path(req.filename)
    df = load_file(path, req.sheet)

    if req.columns:
        missing = [c for c in req.columns if c not in df.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown columns: {missing}")
        df = df[req.columns]

    if req.filters:
        for col, val in req.filters.items():
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Filter column not found: {col}")
            df = df[df[col] == val]

    if req.group_by:
        if req.group_by not in df.columns:
            raise HTTPException(status_code=400, detail=f"group_by column not found: {req.group_by}")
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        agg_fn = {"sum": "sum", "mean": "mean", "count": "count", "min": "min", "max": "max"}.get(req.agg, "sum")
        df = df.groupby(req.group_by)[numeric_cols].agg(agg_fn).reset_index()

    df = df.head(req.limit)
    return safe_json({"rows": len(df), "columns": df.columns.tolist(), "data": df.to_dict(orient="records")})


@app.post("/to-markdown")
def to_markdown(req: QueryRequest):
    path = resolve_path(req.filename)
    df = load_file(path, req.sheet)

    if req.columns:
        df = df[[c for c in req.columns if c in df.columns]]
    if req.filters:
        for col, val in req.filters.items():
            if col in df.columns:
                df = df[df[col] == val]

    limit = req.limit or 30
    total = len(df)
    truncated = total > limit
    df = df.head(limit)
    md = df.to_markdown(index=False)
    note = f"\n\n_(showing {limit} of {total} rows)_" if truncated else ""
    return {"markdown": md + note, "rows": len(df), "truncated": truncated}


@app.post("/execute")
def execute(req: ExecuteRequest):
    """
    Natural language -> pandas code gen (Llama 3.1 8B) -> execute -> result.
    On execution error, feeds the error back to the model for one retry.
    Returns success/failure + generated code + result or error for the chat
    model to reason over.
    """
    path = resolve_path(req.filename)
    df = load_file(path, req.sheet)
    schema = schema_summary(df)

    system_prompt = textwrap.dedent("""
        You are a Python/pandas code generator. Given a DataFrame schema and a question,
        write the shortest correct pandas snippet that answers the question.

        Rules:
        - The DataFrame is already loaded as `df`. Do NOT load any files.
        - Assign your final answer to `result`. Do NOT further aggregate or summarize
          `result` after computing it -- if the answer is a Series or DataFrame, leave
          it as-is. Never average a grouped result into a single scalar unless the
          question explicitly asks for an overall single number.
        - "average X per Y" means: groupby Y, then mean() of X. Result is a Series
          indexed by Y. Do not collapse it further.
        - "X per unit" or "X per Y" where both are columns means: compute the ratio
          column-wise (e.g. df['X'] / df['Y']), then aggregate as asked.
        - For filtered computations, filter df first, then compute on the filtered result.
        - Use only pandas and Python builtins. No imports needed.
        - Return ONLY the code inside a ```python block. No explanation outside the block.

        Examples:
        Q: average tenants per calc type
        A:
        ```python
        result = df.groupby('Calc Type')['Tenants'].mean().round(2)
        ```

        Q: average tenants per unit by calc type
        A:
        ```python
        result = df.groupby('Calc Type').apply(
            lambda g: g['Tenants'].sum() / g['Units'].sum()
        ).round(3)
        ```

        Q: total revenue for properties where city is Denver
        A:
        ```python
        filtered = df[df['City'] == 'Denver']
        result = filtered['Revenue'].sum()
        ```
    """).strip()

    def build_messages(error_feedback=None):
        content = f"DataFrame schema:\n{schema}\n\nQuestion: {req.question}"
        if error_feedback:
            content += f"\n\nYour previous code failed:\n{error_feedback}\nPlease fix it."
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}]

    # attempt 1
    code = extract_code(call_llama(build_messages()))
    error = None
    try:
        result_str = run_pandas_code(code, df)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

        # attempt 2 with error feedback
        code2 = extract_code(call_llama(build_messages(error_feedback=error)))
        try:
            result_str = run_pandas_code(code2, df)
            code = code2
            error = None
        except Exception as e2:
            return {
                "success": False,
                "question": req.question,
                "code": code2,
                "error": f"Both attempts failed. Attempt 1: {error} | Attempt 2: {type(e2).__name__}: {e2}",
                "result": None,
            }

    return {
        "success": True,
        "question": req.question,
        "code": code,
        "error": None,
        "result": result_str,
    }