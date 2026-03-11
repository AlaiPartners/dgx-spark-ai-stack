"""
Open WebUI Pipe: Knowledge Document Router
-------------------------------------------
Install in Open WebUI:
  Workspace → Functions → + New Function → select "Pipe" → paste this file

Intercepts Knowledge base file uploads and routes them through the same
logic as the chat Filter, giving full parity:

  .xlsx / .xls / .csv / .tsv  →  Excel sidecar
  .txt / .md / .rst            →  Direct text read
  .docx                        →  content-extraction (MarkItDown)
  .pdf / images                →  Docling API

How Knowledge pipes work in Open WebUI:
  - Open WebUI calls pipe() when a file is added to a Knowledge collection
  - The pipe receives the raw file bytes and metadata
  - It returns processed text that gets stored in the vector DB (RAG)
  - This replaces Docling's RAG ingestion for the file types we handle

Prerequisites:
  - excel-sidecar running (for spreadsheets)
  - content-extraction service running (for .docx, PDF, images; uses MarkItDown + Docling)
  - Docling running at http://docling:5001 (already in stack)

NOTE: Knowledge pipes interact with the RAG ingestion pipeline, which
varies between Open WebUI versions. If this pipe doesn't fire on upload,
check Admin → Settings → Documents → Content Extraction Engine -- it may
need to be set to "Default" (not "Docling") for the pipe to intercept.
"""

import requests
from pathlib import Path
from typing import Optional, Generator, Iterator
from pydantic import BaseModel, Field


# ─── inline router core ───────────────────────────────────────────────────────

SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv", ".tsv"}
PLAIN_TEXT_EXTENSIONS  = {".txt", ".md", ".rst", ".log"}
WORD_EXTENSIONS        = {".docx"}
PDF_EXTENSIONS         = {".pdf"}
IMAGE_EXTENSIONS       = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff"}
UPLOADS_DIR = Path("/app/backend/data/uploads")


def find_upload(filename: str) -> Optional[Path]:
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
    ext = Path(filename).suffix.lower()
    if ext in SPREADSHEET_EXTENSIONS: return "spreadsheet"
    if ext in PLAIN_TEXT_EXTENSIONS:  return "plaintext"
    if ext in WORD_EXTENSIONS:        return "word"
    if ext in PDF_EXTENSIONS:         return "pdf"
    if ext in IMAGE_EXTENSIONS:       return "image"
    return "unknown"


def route_spreadsheet(resolved, filename, sidecar_url, max_rows=20):
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
                    mn = s.get("min", "")
                    mx = s.get("max", "")
                    val = f"mean={mean:.2f}, min={mn}, max={mx}" if isinstance(mean, float) else str(s)
                    lines.append(f"- `{col}`: {val}")
    else:
        lines.append(f"_Analysis error: {analysis['error']}_")

    # for Knowledge/RAG, include ALL rows not just a preview
    query_result = post("/query", {"filename": resolved.name, "limit": 5000})
    if query_result and "error" not in query_result:
        import json
        lines.append("\n**Full Data (for RAG indexing):**\n")
        rows = query_result.get("data", [])
        cols = query_result.get("columns", [])
        lines.append(" | ".join(cols))
        lines.append(" | ".join(["---"] * len(cols)))
        for row in rows:
            lines.append(" | ".join(str(row.get(c, "")) for c in cols))
    else:
        lines.append(f"_Full data error: {query_result.get('error') if query_result else 'no response'}_")

    return "\n".join(lines)


def route_plaintext(resolved, filename):
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
        return f"## File: `{filename}`\n\n{text}"
    except Exception as e:
        return f"## File: `{filename}`\n\n_Read error: {e}_"


def route_word(resolved, filename):
    try:
        from docx import Document
        doc = Document(str(resolved))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n\n".join(paragraphs)
        return f"## Document: `{filename}`\n\n{text}"
    except ImportError:
        return route_docling(resolved, filename)
    except Exception as e:
        return f"## Document: `{filename}`\n\n_Read error: {e} -- routed to Docling_"


def route_docling(resolved, filename, docling_url="http://docling:5001"):
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
            content = (
                data.get("document", {}).get("md_content")
                or data.get("output", "")
                or str(data)
            )
            return f"## Document: `{filename}`\n\n{content}"
    except Exception as e:
        return f"## Document: `{filename}`\n\n_Docling error: {e}_"


def route_file(filename, sidecar_url="http://excel-sidecar:9000", docling_url="http://docling:5001", max_rows=20):
    resolved = find_upload(filename)
    if not resolved:
        available = [f.name for f in UPLOADS_DIR.iterdir() if not f.name.startswith(".")]
        return f"## File: `{filename}`\n\n_File not found._\n_Available: {available}_"

    kind = classify(filename)
    if kind == "spreadsheet":  return route_spreadsheet(resolved, filename, sidecar_url, max_rows)
    if kind == "plaintext":    return route_plaintext(resolved, filename)
    if kind == "word":         return route_word(resolved, filename)
    return route_docling(resolved, filename, docling_url)


# ─── pipe ─────────────────────────────────────────────────────────────────────

class Pipe:

    class Valves(BaseModel):
        enabled: bool = Field(default=True, description="Enable knowledge document router")
        sidecar_url: str = Field(
            default="http://excel-sidecar:9000",
            description="Excel sidecar base URL"
        )
        docling_url: str = Field(
            default="http://docling:5001",
            description="Docling API base URL"
        )

    def __init__(self):
        self.valves = self.Valves()
        self.type = "manifold"

    def pipes(self):
        """
        Declare which document types this pipe handles.
        Open WebUI uses this to decide when to invoke the pipe.
        """
        return [
            {"id": "doc-router-spreadsheet", "name": "Document Router: Spreadsheet"},
            {"id": "doc-router-text",        "name": "Document Router: Plain Text"},
            {"id": "doc-router-word",        "name": "Document Router: Word Doc"},
            {"id": "doc-router-pdf",         "name": "Document Router: PDF"},
            {"id": "doc-router-image",       "name": "Document Router: Image"},
        ]

    def pipe(self, body: dict) -> str:
        """
        Called by Open WebUI during Knowledge ingestion.
        body contains file metadata and the upload path.
        Returns processed text for RAG indexing.
        """
        if not self.valves.enabled:
            return ""

        # Extract filename from body -- Open WebUI passes it in various shapes
        filename = (
            body.get("filename")
            or body.get("file", {}).get("filename")
            or body.get("name")
            or ""
        )

        if not filename:
            return "_Document router: no filename in body_"

        return route_file(
            filename,
            sidecar_url=self.valves.sidecar_url,
            docling_url=self.valves.docling_url,
        )
