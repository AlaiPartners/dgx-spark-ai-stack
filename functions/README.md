# Document Router

Smart file routing for Open WebUI on the DGX Spark stack. Tuned for **manufacturing and technical documentation** (specs, work orders, PDFs, spreadsheets). Replaces blanket Docling processing with per-type handlers.

## Routing Table

| Extension | Handler | Why |
|---|---|---|
| `.xlsx` `.xls` `.xlsm` `.csv` `.tsv` | Excel sidecar | Real computation, not cell-by-cell text |
| `.txt` `.md` `.rst` `.log` | Direct read | No processing needed |
| `.docx` | content-extraction (MarkItDown) | Word → Markdown, no vision |
| `.pdf` | Docling | May contain images/tables |
| `.png` `.jpg` `.jpeg` `.gif` `.webp` `.tiff` | Docling | Vision required |
| unknown | Docling | Safe fallback |

## Files

- `chat_filter.py` -- Open WebUI Filter (chat uploads)
- `knowledge_pipe.py` -- Open WebUI Pipe (Knowledge base uploads)
- `router_core.py` -- Shared logic (reference only, inlined in above)

## Install

### 1. Chat Filter
Workspace → Functions → + New Function → **Filter** → paste `chat_filter.py`

### 2. Knowledge Pipe
Workspace → Functions → + New Function → **Pipe** → paste `knowledge_pipe.py`

### 3. External content extraction (for .docx and others)
Set Open WebUI to use the content-extraction service so .docx and other types
are handled by the deploy stack (MarkItDown for Word, Docling for PDF/images):
  Admin → Settings → Documents → Content Extraction Engine → **External**
  EXTERNAL_DOCUMENT_LOADER_URL=http://content-extraction:8000

(If you use the Filter/Pipe only and keep Engine = Default, the pipe/filter
still need Docling and excel-sidecar; .docx would be handled by the pipe
calling content-extraction or Docling.)

### 4. Disable Docling auto-processing
Admin → Settings → Documents → Content Extraction Engine → set to **Default**

Docling is still used -- but only when the router explicitly calls it
(PDFs and images). This prevents double-processing.

## Key difference vs before

| Before | After |
|---|---|
| All uploads → Docling → text injected | Router decides handler per file type |
| Spreadsheets read as raw cell text | Spreadsheets computed by sidecar |
| Docling spins up vision for .txt files | .txt files read directly in milliseconds |
| Knowledge and chat handled differently | Full parity |

## Notes on the Knowledge pipe

Open WebUI's Knowledge ingestion pipeline varies by version. If the pipe
doesn't fire on upload:

1. Check Admin → Settings → Documents → Content Extraction Engine
   - Must be set to **Default**, not **Docling**, for the pipe to intercept
2. The pipe declares itself as `type = "manifold"` -- verify it appears
   in Workspace → Functions after install
3. Body shape passed to `pipe()` varies -- check Open WebUI container logs
   if filename isn't being extracted correctly
