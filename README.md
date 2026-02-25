# Spark Deploy

Clean deployment for Open WebUI, Docling, llama.cpp, and Nginx.

## Quick Start

1. **Set llama.cpp path and deploy:**
   ```bash
   export LLAMA_CPP_PATH=/path/to/llama.cpp
   ./scripts/deploy.sh
   ```

   The deploy script will:
   - Download default vision model if needed
   - Copy llama.cpp to build context
   - Build and start all services

## Manual Setup

### 1. Download Models

```bash
./scripts/download-models.sh [model] [quantization]
```

Examples:
```bash
./scripts/download-models.sh granite-vision-3.3-2b Q4_K_M
./scripts/download-models.sh llava-1.5-7b Q4_K_M
```

Available models:
- `granite-vision-3.3-2b` (recommended, ~1.3GB)
- `granite-vision-3.2-2b` (~1.3GB)
- `llava-1.5-7b` (~4.2GB)
- `llava-1.5-13b` (~7.4GB)

Quantization options: `Q4_K_M`, `Q5_K_M`, `Q6_K`

### 2. Install llama.cpp

If llama.cpp is not already built:

```bash
./scripts/install-llamacpp.sh /path/to/llama.cpp
```

### 3. Configure Environment

Copy `.env.example` to `.env` and set:

```bash
cp .env.example .env
# Edit .env with your paths
```

### 4. Start Services

```bash
docker compose up -d
```

## Services

- **Open WebUI**: http://localhost:3000
- **Docling**: http://localhost:5001
- **llama.cpp**: http://localhost:8001
- **Nginx**: http://localhost

## Configuration

### Docling Picture Description

Configure in Open WebUI settings:

```json
{
  "picture_description_api": "{\"url\": \"http://llamacpp:8001/v1/chat/completions\", \"params\": {\"model\": \"granite-2b-vision\", \"max_tokens\": 4096}, \"timeout\": 60, \"prompt\": \"You are analyzing a technical documentation page from an industrial automation system. For each image or diagram on the page, provide a structured description that includes: (1) the type of visual (flowchart, screenshot, annotated UI, diagram, etc.), (2) the key elements visible and their relationships or layout, (3) any text labels, callouts, or annotations present and what they point to, and (4) the functional purpose of the image in context of the surrounding documentation. Be precise and literal — avoid inference beyond what is visually present.\"}"
}
```

## Logs

```bash
docker compose logs -f [service]
```

## Requirements

- Docker & Docker Compose
- NVIDIA GPU with CUDA support
- llama.cpp source code
- `huggingface-cli` (installed automatically)
