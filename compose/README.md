# Compose fragments by domain

The stack is split by domain. The root `docker-compose.yml` uses Compose `include` to merge these files. Paths are relative to the repo root.

## Layout

```
compose/
├── base.yml              # Network + volumes (include first)
├── llm/                  # LLM inference services
│   ├── llamacpp-vision.yml
│   ├── llamacpp-llama.yml
│   └── llamacpp-qwen.yml
├── docling/              # Document processing
│   └── docling.yml
├── web/                  # Web UI, Ollama, and reverse proxy
│   ├── ollama.yml
│   ├── open-webui.yml
│   └── nginx.yml
├── sidecars/             # Supporting services
│   ├── content-extraction.yml
│   └── excel-sidecar.yml
└── README.md             # This file
```

## Domains

- **base.yml** – Defines `spark-network` and named volumes (`open-webui`, `open-webui-ollama`, `docling-models`, `docling-easyocr`). Must be included first.
- **llm/** – llama.cpp model servers (vision, llama, qwen). No cross-service dependencies. New models added via `add_model.py` go here.
- **docling/** – Docling service; `depends_on: llamacpp-vision`. Memory capped at 16GB due to known upstream leaks; if it hits the limit the container is OOM-killed and will show unhealthy (then restart). Use a cron to periodically restart as a workaround.
- **web/** – ollama (standalone, uses `open-webui-ollama` volume for models), **ollama-warmup** (one-shot: preloads `gpt-oss-20b` with keep_alive -1 after ollama is healthy; script `ollama-warmup.sh`), Open WebUI (2 replicas behind Nginx, no direct port), nginx; open-webui depends on ollama, docling, llamacpp-llama.
- **sidecars/** – content-extraction (doc-router, optimized for manufacturing documentation), excel-sidecar; share volumes or call other services via env.

## Usage

Run from the repo root:

```bash
docker compose up -d
docker compose build
docker compose logs -f <service>
```

Do not run `docker compose` from inside the `compose/` directory.

## External volumes (production)

If volumes are created and managed **outside** this stack (e.g. by another compose project, or `docker volume create`), nothing in the service definitions changes—they still reference the same volume names. In `compose/base.yml` set each such volume to external so Compose does not create or remove them:

```yaml
volumes:
  open-webui:
    external: true
  open-webui-ollama:
    external: true
  docling-models:
    external: true
  docling-easyocr:
    external: true
```

Ensure those volumes exist before `docker compose up` (e.g. `docker volume create open-webui`). With `external: true`, `docker compose down -v` will not delete these volumes.
