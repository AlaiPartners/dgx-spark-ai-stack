# Open WebUI Configuration

This guide shows two options for connecting Open WebUI to your llama.cpp models:
1. **Direct connections** (simpler, two connections)
2. **llama-swap proxy** (one connection, automatic routing)

## Option 1: Direct Container Connections (Recommended for Simplicity)

Point directly to each llama.cpp container. You'll need **two connections**:

### Connection 1: Vision Model

- **Name**: `llama-vision` (or any name)
- **URL**: `http://llamacpp-vision:8001/v1`
- **API Key**: Leave blank

This gives you access to: `granite-vision-3.3-2b-Q8_0.gguf`

### Connection 2: Text Model

- **Name**: `llama-text` (or any name)
- **URL**: `http://llamacpp-llama:8001/v1`
- **API Key**: Leave blank

This gives you access to: `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf`

### Pros of Direct Connections
✅ Simpler - no proxy layer  
✅ Direct access to each server  
✅ Easier to debug  
✅ Lower latency (one less hop)

### Cons of Direct Connections
❌ Need to manually select which connection/model to use  
❌ Two separate connections to manage

---

## Option 2: llama-swap Proxy (Automatic Routing)

llama-swap automatically routes requests to the correct upstream server based on the model name:
- `granite-2b-vision` → routes to `llamacpp-vision:8001`
- `llama-3.1-8b-instruct` → routes to `llamacpp-llama:8001`

You only need **one connection** in Open WebUI - llama-swap handles the routing automatically.

## Step-by-Step Configuration

### 1. Access Open WebUI

Navigate to: `http://localhost:3000` (or `http://localhost/` if using Nginx)

### 2. Navigate to Connections Settings

1. Click the **⚙️ Settings** icon (top right)
2. Go to **Admin Settings**
3. Click **Connections** tab
4. Select **OpenAI** (or **Compatible** if available)

---

### Option 1: Direct Connections (Two Connections)

#### Add Vision Model Connection

Click **➕ Add Connection** and configure:

- **Name**: `llama-vision`
- **URL**: `http://llamacpp-vision:8001/v1`
  - ⚠️ **Important**: Must include `/v1` at the end!
- **API Key**: Leave blank
- **Connection Type**: Select **Standard / Compatible** if tabs are visible

Click **Save**

#### Add Text Model Connection

Click **➕ Add Connection** again and configure:

- **Name**: `llama-text`
- **URL**: `http://llamacpp-llama:8001/v1`
  - ⚠️ **Important**: Must include `/v1` at the end!
- **API Key**: Leave blank
- **Connection Type**: Select **Standard / Compatible** if tabs are visible

Click **Save**

#### Verify Models

After saving, Open WebUI will detect:
- From `llama-vision`: `granite-vision-3.3-2b-Q8_0.gguf`
- From `llama-text`: `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf`

---

### Option 2: llama-swap Proxy (One Connection)

Click **➕ Add Connection** and configure:

- **Name**: `llama-swap` (or any name you prefer)
- **URL**: `http://llama-swap:8080/v1`
  - ⚠️ **Important**: Must include `/v1` at the end!
  - This uses the Docker service name `llama-swap` (internal network)
- **API Key**: Leave **blank** (not required for local servers)
- **Connection Type**: Select **Standard / Compatible** if tabs are visible

Click **Save**

#### Verify Models

After saving, Open WebUI will automatically detect both models:
- `granite-2b-vision` (vision model for image descriptions)
- `llama-3.1-8b-instruct` (text model for chat)

---

### Test the Connection(s)

1. Start a new chat
2. Select a model from the dropdown
3. Send a test message

## Alternative: Using Nginx Route

If you prefer to use the Nginx route (external access):

- **URL**: `http://nginx/llama/v1`
  - This routes through Nginx to llama-swap
  - Still accessible from within Docker network

Or from the host machine:
- **URL**: `http://localhost/llama/v1`
  - Accessible from browser/host

## How It Works

1. **Open WebUI** sends request to `llama-swap:8080/v1/chat/completions` with model name
2. **llama-swap** reads the model name from the request
3. **llama-swap** automatically routes to the correct upstream:
   - `granite-2b-vision` → `llamacpp-vision:8001`
   - `llama-3.1-8b-instruct` → `llamacpp-llama:8001`
4. The upstream server processes the request and returns the response
5. **llama-swap** forwards the response back to Open WebUI

## Docling Picture Description Configuration

For Docling to use the vision model through llama-swap, configure in Open WebUI settings:

**Settings** → **Features** → **Document Processing** → **Picture Description API**

```json
{
  "url": "http://llama-swap:8080/v1/chat/completions",
  "params": {
    "model": "granite-2b-vision",
    "max_tokens": 4096
  },
  "timeout": 60,
  "prompt": "You are analyzing a technical documentation page from an industrial automation system. For each image or diagram on the page, provide a structured description that includes: (1) the type of visual (flowchart, screenshot, annotated UI, diagram, etc.), (2) the key elements visible and their relationships or layout, (3) any text labels, callouts, or annotations present and what they point to, and (4) the functional purpose of the image in context of the surrounding documentation. Be precise and literal — avoid inference beyond what is visually present."
}
```

## Troubleshooting

### Models Not Appearing

1. **Check llama-swap is running**:
   ```bash
   docker ps | grep llama-swap
   ```

2. **Verify models are available**:
   ```bash
   curl http://localhost:8002/v1/models
   ```

3. **Check llama-swap logs**:
   ```bash
   docker logs llama-swap
   ```

### Connection Timeout

If you see timeout errors:

1. **Increase timeout** in Open WebUI environment variables:
   ```yaml
   - AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST=30
   ```

2. **Verify network connectivity**:
   ```bash
   docker exec open-webui ping -c 2 llama-swap
   ```

### Wrong Model Selected

- Make sure you're using the exact model names:
  - `granite-2b-vision` (not `granite-vision-3.3-2b`)
  - `llama-3.1-8b-instruct` (not `llama-3.1-8b`)

## Summary

✅ **One connection** in Open WebUI pointing to `http://llama-swap:8080/v1`  
✅ **Both models** automatically available  
✅ **Automatic routing** based on model name  
✅ **No manual switching** needed - llama-swap handles it
