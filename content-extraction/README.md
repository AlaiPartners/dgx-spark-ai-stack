# content-extraction (doc-router)

Custom content extraction service for Open WebUI on the DGX Spark AI stack.
Drop-in replacement for Docling as the default extraction engine. **Optimized for manufacturing-type documentation** (specs, work orders, PDFs, spreadsheets, and mixed-format knowledge bases) where fast extraction and per-type routing matter more than running a vision model on every file.

## Why

Docling runs a vision model on every upload -- fast for knowledge base builds
where you want maximum quality, but too slow for ad-hoc chat uploads where
you just need the text quickly.

## Routing logic

| File type | Handler | Speed |
|---|---|---|
| `.txt` `.md` `.rst` `.log` | Direct decode | ~1ms |
| Source code (`.py` `.js` etc.) | Direct decode | ~1ms |
| `.csv` `.tsv` | Direct decode | ~1ms |
| `.docx` `.doc` | [MarkItDown](https://github.com/microsoft/markitdown) → Markdown | ~50–200ms |
| PDF | Docling | 5-30s |
| `.png` `.jpg` `.jpeg` `.gif` `.webp` | Docling | 5-30s |
| Digital PDF (text layer detected) | pymupdf (if `PDF_FAST_PATH=true`) | ~100ms |
| Scanned / image-heavy PDF | Docling | 5-30s |
| `.xlsx` `.csv` (chat uploads) | Stub → excel-sidecar | instant |
| Unknown | Docling fallback | 5-30s |

PDF routing uses a text density heuristic: extract first 5 pages via pymupdf,
if average characters/page > `PDF_TEXT_THRESHOLD` (default 50), it's digital.
Below that, route to Docling for OCR.

## Setup

The stack uses the split compose layout (see repo root `docker-compose.yml` and `compose/`). The content-extraction service is built from this directory and included via `compose/sidecars/content-extraction.yml`.

### 1. Open WebUI: Document settings (External engine)

In Open WebUI, point document processing at this service:

- **Admin → Settings → Documents**
- **Content Extraction Engine** → **External**
- Set **External Document Loader URL** to `http://content-extraction:8000`  
  (or ensure the `open-webui` service has the env below so it uses this URL)

If using compose, set in `compose/web/open-webui.yml` (or your open-webui env):

```yaml
open-webui:
  environment:
    - CONTENT_EXTRACTION_ENGINE=external
    - EXTERNAL_DOCUMENT_LOADER_URL=http://content-extraction:8000
```

### 2. Open WebUI: Enable chat filter (optional but recommended)

For chat uploads (spreadsheets, routing to excel-sidecar, etc.), enable the router filter:

- **Workspace → Functions → + New Function → Filter**
- Paste the contents of `functions/chat_filter.py` from this repo
- Save and enable the function

Without the filter, chat uploads still use the external loader for extraction but won’t use the excel-sidecar or the same routing logic as the pipe.

### 3. Deploy

From the repo root:

```bash
docker compose build content-extraction
docker compose up -d content-extraction
# Restart open-webui if you changed its env
docker compose up -d open-webui
```

### 4. Verify

From the repo root (no port published by default; use exec or add a port in compose):

```bash
docker compose exec content-extraction curl -s http://localhost:8000/health
# Or from host if you add ports: 9002:8000 for content-extraction:
# curl http://localhost:9002/health
# curl -X PUT http://localhost:9002/process -H "X-File-Name: test.pdf" -H "Content-Type: application/pdf" --data-binary @your-file.pdf
```

## Configuration

| Env var | Default | Description |
|---|---|---|
| `DOCLING_URL` | `http://docling:5001` | Internal Docling service URL |
| `PDF_TEXT_THRESHOLD` | `50` | Avg chars/page below which PDF routes to Docling |

## Notes

- Knowledge base uploads still use whatever engine Open WebUI is configured
  for at the knowledge level -- this only affects the chat extraction path
- Spreadsheet stubs in RAG are intentional: the excel-sidecar filter handles
  actual analysis at chat time, so the RAG index just needs a pointer
- Docling container can remain in compose for scanned PDF handling --
  this service calls it internally, not Open WebUI directly
