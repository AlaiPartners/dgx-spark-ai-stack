# Add Model CLI

Simple Python CLI to add new models to your docker-compose setup. Downloads quantized models from HuggingFace and automatically configures services.

## Installation

Set up the virtualenv (required):

```bash
./setup_venv.sh
```

This installs:
- `huggingface-hub` - for downloading models
- `ruamel.yaml` - for YAML editing (preserves formatting)

Or manually:

```bash
python3 -m venv venv
source venv/bin/activate
pip install huggingface-hub ruamel.yaml
```

## Usage

**Important**: Always activate the virtualenv first:

```bash
source venv/bin/activate
```

### Interactive Mode (Recommended)

Simply run the script without arguments - it will walk you through each step:

```bash
python add_model.py
```

The interactive mode will:
1. Prompt for HuggingFace repository ID
2. Auto-detect available quantizations
3. Let you choose quantization level
4. Auto-detect if it's a vision model
5. Generate service name (with option to customize)
6. Ask about llama-swap integration
7. Ask about auto-starting the service
8. Show a summary and confirm before proceeding

### Non-Interactive Mode

For automation or scripts, you can still use command-line arguments:

```bash
# Add a text model
python add_model.py meta-llama/Meta-Llama-3.1-8B-Instruct-GGUF --quant Q4_K_M

# Add a vision model (auto-detects mmproj)
python add_model.py ibm-granite/granite-vision-3.3-2b-GGUF --quant Q4_K_M
```

### Options

```bash
python add_model.py <repo_id> [options]

Arguments:
  repo_id              HuggingFace repo ID (e.g., meta-llama/Meta-Llama-3.1-8B-Instruct-GGUF)

Options:
  --quant, --quantization QUANT
                        Quantization level (default: Q4_K_M)
                        Common: Q4_K_M, Q5_K_M, Q6_K, Q8_0

  --name NAME           Custom service/container name
                        (auto-generated from repo if not provided)

  --models-dir DIR      Models directory (default: ./models)

  --compose FILE        docker-compose.yml path (default: docker-compose.yml)

  --swap-config FILE    llama-swap config path (default: config/llama-swap.yaml)

  --no-swap             Skip updating llama-swap config

  --no-start            Skip starting the service after adding
```

## Examples

### Add Llama 3.1 70B

```bash
python add_model.py meta-llama/Meta-Llama-3.1-70B-Instruct-GGUF --quant Q4_K_M
```

### Add with Custom Name

```bash
python add_model.py meta-llama/Meta-Llama-3.1-8B-Instruct-GGUF \
  --name llama-8b-instruct \
  --quant Q4_K_M
```

### Add Vision Model

```bash
python add_model.py ibm-granite/granite-vision-3.3-2b-GGUF --quant Q8_0
```

### Add Without llama-swap

```bash
python add_model.py meta-llama/Meta-Llama-3.1-8B-Instruct-GGUF \
  --quant Q4_K_M \
  --no-swap
```

### Add Without Auto-Start

```bash
python add_model.py meta-llama/Meta-Llama-3.1-8B-Instruct-GGUF \
  --quant Q4_K_M \
  --no-start
```

## What It Does

1. **Prompts for information** (in interactive mode) or uses command-line args
2. **Detects available quantizations** from the HuggingFace repo
3. **Downloads model** from HuggingFace (and mmproj if vision model)
4. **Detects model type** (vision vs text) by checking for mmproj
5. **Generates service name** from repo ID (or uses `--name`)
6. **Adds service** to the compose setup: if the root file uses `include` (split layout), creates a new fragment under `compose/<service_name>.yml` and appends it to the `include` list; otherwise appends the service to the single `docker-compose.yml`.
7. **Updates llama-swap** config (unless `--no-swap`)
8. **Starts service** (unless `--no-start`)
9. **Shows connection details** for the new model

## Service Naming

Service names are auto-generated from the repo ID:
- `meta-llama/Meta-Llama-3.1-8B-Instruct-GGUF` → `llamacpp-meta-llama-3-1-8b-instruct`
- `ibm-granite/granite-vision-3.3-2b-GGUF` → `llamacpp-ibm-granite-granite-vision-3-3-2b`

Use `--name` to customize.

## Model Detection

The script automatically:
- Detects if a model is vision-capable (has mmproj file)
- Configures the service with `MM_PROJ_PATH` if vision
- Sets up proper environment variables

## Connecting to Models

After adding a model, you can connect to it:

### Direct Connection

```bash
# Service name from output
http://llamacpp-<model-name>:8001/v1
```

### Via llama-swap

If you didn't use `--no-swap`, the model is available through llama-swap:

```bash
# Model ID (shown in output)
http://llama-swap:8080/v1
# Use model ID in requests
```

## Troubleshooting

### Model File Not Found

If the script can't find a model file with your quantization:

1. Check available files in the repo:
   ```bash
   huggingface-cli repo-files <repo_id>
   ```

2. The script looks for files matching the quantization pattern. If files are named differently, you may need to download manually.

### Port Conflicts

All models use port 8001 internally (no host mapping). If you need multiple models running, they each get their own container on the same internal port - this is fine since they're accessed via service names.

### YAML Formatting

The script uses `ruamel.yaml` to preserve YAML formatting. If you manually edit `docker-compose.yml`, make sure to maintain proper indentation.

## Notes

- Models are downloaded to `--models-dir` (default: `./models`)
- All services use the pre-built image `cslev/llamacpp-cuda-arm64:latest`
- Services are added to the `spark-network`
- GPU access is configured automatically
- Port 8001 is used internally (no host mapping)
