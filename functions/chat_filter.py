"""
Open WebUI Filter: Document Router
------------------------------------
Install in Open WebUI:
  Workspace → Functions → + New Function → select "Filter" → paste this file

Intercepts ALL chat file uploads and sends them to the content-extraction
service, which handles routing internally:

  .xlsx / .xls / .csv / .tsv  →  Excel sidecar (analysis + preview)
  .txt / .md / source code    →  Direct text read
  digital PDF                 →  pymupdf
  scanned PDF / images        →  Docling
  .docx                       →  content-extraction (MarkItDown)
  unknown                     →  Docling fallback
"""

import requests
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

UPLOADS_DIR = Path("/app/backend/data/uploads")


def find_upload(filename: str, file_id: Optional[str] = None) -> Optional[Path]:
    if not UPLOADS_DIR.exists():
        return None
    if file_id:
        for f in UPLOADS_DIR.iterdir():
            if f.name.startswith(file_id):
                return f
        exact = UPLOADS_DIR / file_id
        if exact.exists():
            return exact
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


def extract(filename: str, file_id: Optional[str], extractor_url: str) -> str:
    resolved = find_upload(filename, file_id=file_id)
    if not resolved:
        available = [f.name for f in UPLOADS_DIR.iterdir() if not f.name.startswith(".")][:10]
        return f"## File: `{filename}`\n\n_File not found (id={file_id}). Available: {available}_"

    try:
        with open(resolved, "rb") as f:
            data = f.read()
        r = requests.put(
            f"{extractor_url}/process",
            data=data,
            headers={
                "X-Filename": filename,
                "Content-Type": "application/octet-stream",
            },
            timeout=300,
        )
        r.raise_for_status()
        result = r.json()
        if isinstance(result, list):
            content = "\n\n---\n\n".join(doc.get("page_content", "") for doc in result)
        else:
            content = result.get("page_content", "")
        if not content.strip():
            return f"## File: `{filename}`\n\n_No content extracted._"
        return f"## File: `{filename}`\n\n{content}"
    except Exception as e:
        return f"## File: `{filename}`\n\n_Extraction error: {e}_"


class Filter:

    class Valves(BaseModel):
        enabled: bool = Field(default=True, description="Enable document router")
        extractor_url: str = Field(
            default="http://content-extraction:8000",
            description="Content extraction service URL"
        )

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user: Optional[dict] = None) -> dict:
        if not self.valves.enabled:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        last_message = messages[-1]
        files = (
            last_message.get("files")
            or last_message.get("uploads")
            or body.get("files")
            or []
        )
        if not files:
            return body

        handled_content = []

        for file_info in files:
            filename = (
                file_info.get("name")
                or file_info.get("filename")
                or file_info.get("file", {}).get("filename")
                or ""
            )
            file_id = (
                file_info.get("id")
                or file_info.get("file", {}).get("id")
                or None
            )

            if not filename:
                continue

            print(f"ROUTER: file={filename} id={file_id}")
            content = extract(filename, file_id, self.valves.extractor_url)
            handled_content.append(content)

        print(f"ROUTER: found {len(files)} files, handled={len(handled_content)}")

        if handled_content:
            injection = (
                "The following files have been processed. "
                "Use this content to answer the user's question accurately. "
                "Do NOT attempt to re-read or re-process the files.\n\n"
                + "\n\n---\n\n".join(handled_content)
            )
            system_messages = [m for m in messages if m.get("role") == "system"]
            if system_messages:
                system_messages[0]["content"] += "\n\n" + injection
            else:
                messages.insert(0, {"role": "system", "content": injection})

            last_message["files"] = []
            body["files"] = []
            body["messages"] = messages

        return body

    def outlet(self, body: dict, __user: Optional[dict] = None) -> dict:
        return body