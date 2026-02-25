# Single Router vs Multi-Container: Comparison

## Current Approach: Multiple Containers

### Architecture
```
┌─────────────────┐
│   llama-swap    │  (Proxy/router)
└────────┬────────┘
         │
    ┌────┴────┬──────────┬──────────┐
    │         │          │          │
┌───▼───┐ ┌──▼───┐ ┌───▼───┐ ┌───▼───┐
│vision │ │llama │ │  gpt  │ │claude │
│:8001  │ │:8001 │ │ :8001 │ │ :8001 │
└───────┘ └──────┘ └───────┘ └───────┘
```

### Pros ✅
- **Isolation**: Each model runs independently
- **Resource Control**: Per-model limits (memory, GPU, CPU)
- **Independent Scaling**: Scale models separately
- **Easier Debugging**: Separate logs and monitoring
- **Independent Restarts**: Restart one without affecting others
- **Different Configs**: Per-model settings (ctx-size, threads, etc.)
- **No Model Switching Overhead**: Models stay loaded
- **Works with llama-swap**: Already integrated

### Cons ❌
- **Higher Memory Usage**: Each container has base overhead (~100-200MB per container)
- **More Containers to Manage**: More services in docker-compose
- **More Ports**: Each needs a port (or routing via llama-swap)
- **More Complex Compose File**: More services to define

---

## Alternative: Single Router Instance

### Architecture
```
┌─────────────────────────────────┐
│   llama-server (router mode)    │
│   --models-dir /models          │
│   Port: 8001                    │
└──────────────┬──────────────────┘
               │
    ┌──────────┼──────────┐
    │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐
│vision │ │llama │ │  gpt  │  (subprocesses)
│:8002  │ │:8003 │ │ :8004 │  (dynamic ports)
└───────┘ └───────┘ └───────┘
```

### How It Works
1. Start `llama-server` **without** `--model` flag
2. Use `--models-dir` to point to directory with GGUF files
3. Router discovers models automatically
4. Each model runs as a subprocess on dynamic port
5. Router forwards requests based on `"model"` field in JSON

### Configuration Example

**docker-compose.yml:**
```yaml
llamacpp-router:
  image: cslev/llamacpp-cuda-arm64:latest
  container_name: llamacpp-router
  restart: unless-stopped
  volumes:
    - ${MODELS_DIR:-./models}:/models:ro
    - ./logs:/logs
  environment:
    - CUDA_VISIBLE_DEVICES=0
  command: >
    --host 0.0.0.0
    --port 8001
    --models-dir /models
    --ctx-size 16384
    --threads 8
    --n-gpu-layers 99
    --models-autoload
  networks:
    - spark-network
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            device_ids: ['0']
            capabilities: [gpu]
```

**models.ini (optional preset):**
```ini
[*]
ctx-size = 16384
threads = 8
n-gpu-layers = 99

[granite-vision-3.3-2b]
model = /models/granite-vision-3.3-2b/granite-vision-3.3-2b-Q8_0.gguf
mmproj = /models/granite-vision-3.3-2b/mmproj-model-f16.gguf
ctx-size = 32768
load-on-startup = true

[llama-3.1-8b-instruct]
model = /models/llama-3.1-8b-instruct/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
ctx-size = 16384
load-on-startup = true

[gpt-oss-20b]
model = /models/gpt-oss-20b/gpt-oss-20b-Q5_K_S.gguf
ctx-size = 16384
flash-attn = on

[claude-4-5-opus]
model = /models/glm-4.7-flash-claude-4.5-opus.iq2_m.gguf
ctx-size = 16384
flash-attn = on
```

### Pros ✅
- **Single Container**: Simpler docker-compose
- **Dynamic Model Loading**: Load/unload models via API without restart
- **Automatic Routing**: Router handles model selection
- **Lower Base Overhead**: One container instead of many
- **Built-in Model Management**: `/models` API for listing/loading/unloading
- **Preset Support**: `.ini` files for model configurations
- **LRU Unloading**: Automatically unloads least recently used models

### Cons ❌
- **Shared Resources**: All models share the same GPU/CPU limits
- **Single Point of Failure**: Router crash affects all models
- **Model Switching Latency**: Loading a model takes time (first request)
- **Complex Configuration**: Need to understand router mode and presets
- **Less Isolation**: One misbehaving model can impact others
- **Memory Management**: Need to configure LRU limits carefully
- **Port Management**: Router assigns dynamic ports internally

---

## Comparison Table

| Feature | Multi-Container | Single Router |
|---------|----------------|---------------|
| **Container Count** | 4+ containers | 1 container |
| **Memory Overhead** | ~400-800MB (base) | ~100-200MB (base) |
| **Isolation** | ✅ Excellent | ❌ Shared process |
| **Resource Control** | ✅ Per-model | ❌ Shared |
| **Model Loading** | ✅ Always loaded | ⚠️ On-demand (latency) |
| **Dynamic Loading** | ❌ Requires restart | ✅ Via API |
| **Debugging** | ✅ Separate logs | ⚠️ Combined logs |
| **Failure Impact** | ✅ Isolated | ❌ Affects all |
| **Configuration** | ✅ Simple per-service | ⚠️ Complex presets |
| **Scaling** | ✅ Independent | ❌ Shared |
| **Port Management** | ⚠️ Manual | ✅ Automatic |

---

## Recommendation

### Keep Multi-Container If:
- ✅ You have 4+ models with different requirements
- ✅ You need models always loaded (no latency)
- ✅ You want isolation and reliability
- ✅ You need per-model resource limits
- ✅ You're already using llama-swap successfully

### Use Single Router If:
- ✅ You have many small, rarely-used models
- ✅ You want dynamic model loading/unloading
- ✅ You prefer simpler docker-compose
- ✅ You're okay with model loading latency
- ✅ You want built-in model management API

### Hybrid Approach:
- Keep critical/hot models in separate containers (always loaded)
- Use router mode for less-used models (loaded on demand)

---

## Migration Path (if switching to router mode)

1. **Create models.ini** with all model configurations
2. **Replace multiple containers** with single router container
3. **Update llama-swap config** to point to router (or remove llama-swap)
4. **Test model loading/unloading** via `/models` API
5. **Monitor memory usage** and configure LRU limits

---

## References

- [llama.cpp Router Mode Documentation](https://github.com/ggerganov/llama.cpp/blob/master/tools/server/README.md#using-multiple-models)
- [cslev/llamacpp-cuda-arm64-docker](https://github.com/cslev/llamacpp-cuda-arm64-docker)
