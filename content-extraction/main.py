"""
content-extraction (doc-router): Custom content extraction service for Open WebUI.

Replaces Docling as the default extraction engine for all uploads.
Routes by file type -- fast local extraction for most formats,
calls Docling for PDFs, images, and other document types.

Open WebUI config:
  CONTENT_EXTRACTION_ENGINE=external
  EXTERNAL_DOCUMENT_LOADER_URL=http://content-extraction:8000

Contract (Open WebUI external loader):
  PUT /process
  Body: raw file bytes
  Headers:
    Content-Type: <mime type>
    X-File-Name: <original filename>  (added by Open WebUI)
  Response:
    Single doc:  {"page_content": "...", "metadata": {}}
    Multi-chunk: [{"page_content": "...", "metadata": {...}}, ...]
"""

import io
import logging
import os
import mimetypes
from pathlib import Path
from typing import Optional
import requests as http_requests_sync
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("doc-router")

app = FastAPI(title="doc-router", version="1.0.0")

DOCLING_URL = os.getenv("DOCLING_URL", "http://docling:5001")
# Minimum ratio of characters-to-pages to consider a PDF "text-based"
# Below this threshold, route to Docling (likely scanned)
PDF_TEXT_THRESHOLD = float(os.getenv("PDF_TEXT_THRESHOLD", "50"))

# Picture description via llamacpp-vision -- disabled by default
# Set DOCLING_PICTURE_DESCRIPTION=true to enable
PICTURE_DESCRIPTION_ENABLED = os.getenv("DOCLING_PICTURE_DESCRIPTION", "false").lower() == "true"
VISION_URL     = os.getenv("VISION_URL", "http://llamacpp-vision:8001/v1/chat/completions")
VISION_MODEL   = os.getenv("VISION_MODEL", "granite-vision-3.3-2b")
VISION_MAX_TOKENS = int(os.getenv("VISION_MAX_TOKENS", "8152"))
VISION_TIMEOUT = int(os.getenv("VISION_TIMEOUT", "300"))
VISION_PROMPT  = os.getenv(
    "VISION_PROMPT",
    "You are analyzing a technical documentation page from an industrial automation system. "
    "For each image or diagram on the page, provide a structured description that includes: "
    "(1) the type of visual (flowchart, screenshot, annotated UI, diagram, etc.), "
    "(2) the key elements visible and their relationships or layout, "
    "(3) any text labels, callouts, or annotations present and what they point to, and "
    "(4) the functional purpose of the image in context of the surrounding documentation, "
    "(5) Include the page number and approximate location on the page. "
    "Be precise and literal - avoid inference beyond what is visually present."
)
PDF_FAST_PATH_ENABLED = os.getenv("PDF_FAST_PATH", "false").lower() == "true"



def build_docling_params() -> dict:
    """Build Docling request params. Picture description toggled by DOCLING_PICTURE_DESCRIPTION env var."""
    params = {
        "do_ocr": True,
        "ocr_engine": "easyocr",
        "ocr_lang": ["en"],
        "pdf_backend": "dlparse_v4",
        "table_mode": "accurate",
        "include_images": True,
        "image_export_mode": "placeholder",
        "do_picture_description": False,
    }
    if PICTURE_DESCRIPTION_ENABLED:
        params["do_picture_description"] = True
        params["picture_description_api"] = {
            "url": VISION_URL,
            "params": {"model": VISION_MODEL, "max_tokens": VISION_MAX_TOKENS},
            "timeout": VISION_TIMEOUT,
            "prompt": VISION_PROMPT,
        }
        log.debug("Docling picture description: ENABLED (model=%s)", VISION_MODEL)
    else:
        log.debug("Docling picture description: DISABLED")
    return params

# File extensions handled locally without Docling
FAST_TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv",
    ".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp",
    ".c", ".cs", ".sh", ".bat", ".yaml", ".yml", ".json",
    ".xml", ".html", ".htm", ".toml", ".ini", ".cfg",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def is_text_based_pdf(data: bytes) -> bool:
    """
    Quick heuristic: extract text from first 5 pages via pymupdf.
    If average chars/page > threshold, it's a digital PDF.
    Returns False (route to Docling) if pymupdf unavailable.
    """
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=data, filetype="pdf")
        pages = min(5, len(doc))
        if pages == 0:
            return False
        total_chars = sum(len(doc[i].get_text()) for i in range(pages))
        avg = total_chars / pages
        doc.close()
        log.debug(f"PDF text check: {avg:.0f} chars/page (threshold={PDF_TEXT_THRESHOLD})")
        return avg > PDF_TEXT_THRESHOLD
    except Exception as e:
        log.warning(f"pymupdf check failed, routing to Docling: {e}")
        return False


def extract_pdf_fast(data: bytes) -> list[dict]:
    """Extract text from a digital PDF using pymupdf, one chunk per page."""
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    chunks = []
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if text:
            chunks.append({
                "page_content": text,
                "metadata": {"page": i + 1, "extractor": "pymupdf"},
            })
    doc.close()
    return chunks if chunks else [{"page_content": "", "metadata": {"extractor": "pymupdf"}}]


def extract_docx(data: bytes, file_extension: str = ".docx") -> list[dict]:
    """Extract Word document to Markdown using Microsoft MarkItDown."""
    from markitdown import MarkItDown
    md = MarkItDown()
    result = md.convert_stream(io.BytesIO(data), file_extension=file_extension)
    text = (result.text_content or "").strip()
    if not text:
        return [{"page_content": "", "metadata": {"extractor": "markitdown"}}]
    return [{"page_content": text, "metadata": {"extractor": "markitdown"}}]


def extract_text(data: bytes, encoding: str = "utf-8") -> list[dict]:
    """Direct decode for plain text files."""
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return [{"page_content": text, "metadata": {"extractor": "direct"}}]


def extract_via_docling(data: bytes, filename: str, content_type: str) -> list[dict]:
    """Forward to Docling with configured params and parse response (sync)."""
    import json as _json
    url = f"{DOCLING_URL}/v1/convert/file"
    params = build_docling_params()

    # Docling /v1/convert/file accepts multipart form with flat field names
    # Use list of tuples to support repeated fields (ocr_lang)
    fields = [
        ("to_formats",        "md"),
        ("do_ocr",            str(params["do_ocr"]).lower()),
        ("ocr_engine",        params.get("ocr_engine", "easyocr")),
        ("pdf_backend",       params.get("pdf_backend", "dlparse_v4")),
        ("table_mode",        params.get("table_mode", "accurate")),
        ("include_images",    str(params.get("include_images", True)).lower()),
        ("image_export_mode", "placeholder"),
    ]
    for lang in params.get("ocr_lang", ["en"]):
        fields.append(("ocr_lang", lang))

    if params.get("do_picture_description") and params.get("picture_description_api"):
        fields.append(("do_picture_description", "true"))
        fields.append(("picture_description_api", _json.dumps(params["picture_description_api"])))

    timeout = max(VISION_TIMEOUT + 60, 300) if PICTURE_DESCRIPTION_ENABLED else 300
    try:
        resp = http_requests_sync.post(
            url,
            files={"files": (filename, io.BytesIO(data), content_type)},
            data=fields,
            timeout=timeout,
        )
        resp.raise_for_status()
        result = resp.json()
        md = result.get("document", {}).get("md_content", "") or result.get("md_content", "")
        if not md:
            md = result.get("content", "")
        return [{"page_content": md, "metadata": {"extractor": "docling", "filename": filename}}]
    except Exception as e:
        log.error(f"Docling extraction failed for {filename}: {e}")
        raise HTTPException(status_code=502, detail=f"Docling error: {e}")


# ── main endpoint ─────────────────────────────────────────────────────────────


def _extract_content_disposition_filename(header: str) -> str:
    """Pull filename= out of Content-Disposition header if present."""
    if not header:
        return ""
    for part in header.split(";"):
        part = part.strip()
        if part.startswith("filename="):
            return part[9:].strip('"\'\' ')
    return ""


def _route(ext: str, content_type: str) -> str:
    """Return route key from extension and content-type."""
    if ext in FAST_TEXT_EXTENSIONS or content_type.startswith("text/"):
        return "fast_text"
    if ext in (".docx", ".doc"):
        return "docx"
    if ext == ".pdf" or content_type == "application/pdf":
        return "pdf"
    if ext in (".xlsx", ".xls", ".xlsm", ".csv", ".tsv"):
        return "spreadsheet"
    return "docling"


def _handle_fast_text(data: bytes, _filename: str, _content_type: str) -> list[dict]:
    return extract_text(data)


def _handle_docx(data: bytes, filename: str, content_type: str) -> list[dict]:
    ext = Path(filename).suffix.lower() or ".docx"
    try:
        return extract_docx(data, file_extension=ext)
    except Exception as e:
        log.warning(f"markitdown failed ({e}), falling back to Docling")
        return extract_via_docling(data, filename, content_type)


def _handle_pdf(data: bytes, filename: str, content_type: str) -> list[dict]:
    if PDF_FAST_PATH_ENABLED and is_text_based_pdf(data):
        log.debug("Fast path: pymupdf (text-based PDF)")
        try:
            return extract_pdf_fast(data)
        except Exception as e:
            log.warning(f"pymupdf failed ({e}), falling back to Docling")
            return extract_via_docling(data, filename, content_type)
    log.debug("Docling path: PDF")
    return extract_via_docling(data, filename, content_type)


def _handle_spreadsheet(_data: bytes, filename: str, _content_type: str) -> list[dict]:
    return [{
        "page_content": f"[Spreadsheet: {filename}. Use the execute_spreadsheet_query tool to analyze this file.]",
        "metadata": {"extractor": "stub", "filename": filename},
    }]


def _handle_docling(data: bytes, filename: str, content_type: str) -> list[dict]:
    return extract_via_docling(data, filename, content_type)


ROUTE_HANDLERS = {
    "fast_text": _handle_fast_text,
    "docx": _handle_docx,
    "pdf": _handle_pdf,
    "spreadsheet": _handle_spreadsheet,
    "docling": _handle_docling,
}


@app.put("/process")
async def process(request: Request):
    data = await request.body()

    # Open WebUI sends filename in X-File-Name or as a Content-Disposition header
    filename = (
        request.headers.get("X-Filename")
        or request.headers.get("X-File-Name")
        or _extract_content_disposition_filename(request.headers.get("Content-Disposition", ""))
        or "upload"
    )
    content_type = request.headers.get("Content-Type", "application/octet-stream")
    # Strip multipart boundary etc from content-type if present
    content_type = content_type.split(";")[0].strip()

    # If no extension from filename, try to guess from content-type
    ext = Path(filename).suffix.lower()
    if not ext:
        import mimetypes as _mt
        guessed = _mt.guess_extension(content_type)
        if guessed:
            ext = guessed
            filename = f"upload{ext}"
    log.debug(f"Processing: {filename} ({len(data)} bytes, ext={ext}, ct={content_type})")

    route = _route(ext, content_type)
    chunks = ROUTE_HANDLERS[route](data, filename, content_type)

    log.debug(f"Done: {filename} → {len(chunks)} chunk(s) via {chunks[0]['metadata'].get('extractor')}")

    # Return single doc or array depending on chunk count
    return JSONResponse(chunks if len(chunks) > 1 else chunks[0])


@app.get("/health")
def health():
    return {"status": "ok"}