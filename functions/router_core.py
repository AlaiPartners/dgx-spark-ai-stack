"""
router_core.py
--------------
Shared routing logic for both the chat Filter and the Knowledge Pipe.
Handles file type detection, sidecar calls, Docling calls, and direct extraction.

NOT installed in Open WebUI directly -- imported by the filter and pipe.
In practice, copy this logic inline into each Open WebUI function since
Open WebUI doesn't support multi-file installs.
"""

import re
import io
import requests
from pathlib import Path
from typing import Optional

# ── constants ─────────────────────────────────────────────────────────────────

SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv", ".tsv"}
PLAIN_TEXT_EXTENSIONS  = {".txt", ".md", ".rst", ".log"}
WORD_EXTENSIONS        = {".docx"}
PDF_EXTENSIONS         = {".pdf"}
IMAGE_EXTENSIONS       = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff"}

UPLOADS_DIR = Path("/app/backend/data/uploads")


# ── file resolution ───────────────────────────────────────────────────────────

def find_upload(filename: str) -> Optional[Path]:
    """
    Open WebUI prefixes uploaded files with a UUID: <uuid>_<originalname>
    Try exact match first, then scan for suffix/stem match.
    """
    exact = UPLOADS_DIR / filename
    if exact.exists():
        return exact
    for f in UPLOADS_DIR.iterdir():
        if f.name.endswith("_" + filename) or f.name == filename:
            return f
    stem = Path(filename).stem.lower()
    for f in UPLOADS_DIR.iterdir():
        if stem in f.name.lower():
            return f
    return None


def classify(filename: str) -> str:
    """Return routing class for a filename."""
    ext = Path(filename).suffix.lower()
    if ext in SPREADSHEET_EXTENSIONS:
        return "spreadsheet"
    if ext in PLAIN_TEXT_EXTENSIONS:
        return "plaintext"
    if ext in WORD_EXTENSIONS:
        return "word"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "unknown"


# ── routers ───────────────────────────────────────────────────────────────────

def route_spreadsheet(resolved: Path, filename: str, sidecar_url: str, max_rows: int = 20) -> str:
    """Call excel sidecar: analyze + markdown preview."""
    lines = [f"## Spreadsheet: `{filename}`\n"]

    def post(endpoint, payload):
        try:
            r = requests.post(f"{sidecar_url}{endpoint}", json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    analysis = post("/analyze", {"filename": resolved.name})
    if "error" not in analysis:
        lines.append(f"**Shape:** {analysis.get('rows')} rows x {analysis.get('columns')} columns")
        sheets = analysis.get("sheet_names", [])
        if sheets:
            lines.append(f"**Sheets:** {', '.join(sheets)}")
        col_info = analysis.get("column_info", {})
        if col_info:
            cols = ", ".join(f"`{c}` ({i['dtype']})" for c, i in col_info.items())
            lines.append(f"**Columns:** {cols}")
        stats = analysis.get("numeric_stats", {})
        if stats:
            lines.append("\n**Numeric Summary:**")
            for col, s in stats.items():
                if isinstance(s, dict):
                    mean = s.get("mean", "")
                    mn   = s.get("min", "")
                    mx   = s.get("max", "")
                    val  = f"mean={mean:.2f}, min={mn}, max={mx}" if isinstance(mean, float) else str(s)
                    lines.append(f"- `{col}`: {val}")
    else:
        lines.append(f"_Analysis error: {analysis['error']}_")

    preview = post("/to-markdown", {"filename": resolved.name, "limit": max_rows})
    if preview and "error" not in preview:
        lines.append(f"\n**First {max_rows} rows:**\n")
        lines.append(preview.get("markdown", ""))
        if preview.get("truncated"):
            lines.append(f"\n_(use the query tool for filtered views of the full dataset)_")
    else:
        lines.append(f"_Preview error: {preview.get('error') if preview else 'no response'}_")

    lines.append(
        "\n_Processed by Excel sidecar (real computation). "
        "Use the query tool for aggregations, group-by, and filters._"
    )
    return "\n".join(lines)


def route_plaintext(resolved: Path, filename: str) -> str:
    """Read plain text files directly -- no Docling needed."""
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
        preview = text[:8000]
        truncated = len(text) > 8000
        result = f"## File: `{filename}`\n\n{preview}"
        if truncated:
            result += f"\n\n_(truncated -- file is {len(text)} chars total)_"
        return result
    except Exception as e:
        return f"## File: `{filename}`\n\n_Read error: {e}_"


def route_word(resolved: Path, filename: str) -> str:
    """Extract text from .docx using python-docx (legacy). Prefer content-extraction service (MarkItDown) when available."""
    try:
        from docx import Document
        doc = Document(str(resolved))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n\n".join(paragraphs)
        preview = text[:8000]
        truncated = len(text) > 8000
        result = f"## Document: `{filename}`\n\n{preview}"
        if truncated:
            result += f"\n\n_(truncated -- {len(paragraphs)} paragraphs total)_"
        return result
    except ImportError:
        return route_docling(resolved, filename)
    except Exception as e:
        return f"## Document: `{filename}`\n\n_Read error: {e} -- falling back to Docling_"


def route_docling(resolved: Path, filename: str, docling_url: str = "http://docling:5001") -> str:
    """Send file to Docling API for full processing (PDFs, images, fallback)."""
    try:
        with open(resolved, "rb") as f:
            files = {"files": (filename, f, "application/octet-stream")}
            r = requests.post(
                f"{docling_url}/v1alpha/convert/file",
                files=files,
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            # Docling returns converted markdown in document.md_content
            content = (
                data.get("document", {}).get("md_content")
                or data.get("output", "")
                or str(data)
            )
            return f"## Document: `{filename}`\n\n{content}"
    except Exception as e:
        return f"## Document: `{filename}`\n\n_Docling error: {e}_"


def route_file(
    filename: str,
    sidecar_url: str = "http://excel-sidecar:9000",
    docling_url: str  = "http://docling:5001",
    max_rows: int     = 20,
) -> str:
    """
    Main entry point. Classify the file and dispatch to the right handler.
    Returns a markdown string ready to inject into context.
    """
    resolved = find_upload(filename)
    if not resolved:
        available = [f.name for f in UPLOADS_DIR.iterdir() if not f.name.startswith(".")]
        return (
            f"## File: `{filename}`\n\n"
            f"_File not found in uploads directory._\n"
            f"_Available files: {available}_"
        )

    kind = classify(filename)

    if kind == "spreadsheet":
        return route_spreadsheet(resolved, filename, sidecar_url, max_rows)
    elif kind == "plaintext":
        return route_plaintext(resolved, filename)
    elif kind == "word":
        return route_word(resolved, filename)
    elif kind in ("pdf", "image", "unknown"):
        return route_docling(resolved, filename, docling_url)
    else:
        return route_docling(resolved, filename, docling_url)
