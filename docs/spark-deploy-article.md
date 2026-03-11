# Deploying a Secure, Air-Gap-Ready AI Server on NVIDIA DGX Spark

## A production-grade, on-premises AI stack for clients who need full data sovereignty

*By Daniel Lund, CTO, Alai Partners*

---

There is a class of enterprise client that has two things in common: they need powerful AI capabilities, and they need every byte of their data to stay on their own hardware. Defense contractors. Utilities. Manufacturing plants with air-gapped networks. Organizations in regulated industries where data leaving the premises is not a risk to be managed, it is a line that cannot be crossed.

For these clients, "just use the API" is not an answer. We needed a deployment that is fully self-contained, HTTPS-secured, manageable by a team that is not necessarily deep in AI infrastructure, and capable of running indefinitely without a network connection. This is the story of how we built it, and the open-source result: [**dgx-spark-ai-stack**](https://github.com/AlaiPartners/dgx-spark-ai-stack).

---

## The Hardware: NVIDIA DGX Spark

When NVIDIA released the DGX Spark (GB10 Superchip), it immediately stood out for on-premises deployments. It is not a rack server bristling with discrete GPUs. It is closer to an Apple Silicon Mac Studio in concept: a single unified chip integrating a 20-core ARM CPU with a Blackwell GPU, sharing 128GB of unified LPDDR5x memory. One box. Silent. Roughly the size of a Mac Pro. 1 PFLOP of FP4 AI compute.

For our clients, this form factor is a key selling point. It fits under a desk. It runs on standard office power. It ships to a facility, gets plugged in, and becomes a full AI server for the team. No data center. No cloud dependency. No vendor calling home.

That said, the DGX Spark is unusual hardware, and the AI tooling ecosystem had not fully caught up to it when we started this work.

---

## Challenge 1: ARM64 + CUDA 13 for llama.cpp

This is the challenge that will catch every DGX Spark user who tries to containerize their inference stack. It is worth documenting in detail because the path forward is not obvious, and the community is still catching up.

The llama.cpp project publishes Docker images for x86 with CUDA support. The DGX Spark runs ARM64. When you need both, you are in a narrow intersection that the official project does not cover. There are no published `ghcr.io/ggerganov/llama.cpp:server-cuda` images that will run on DGX Spark.

Our first instinct was to build from the upstream llama.cpp Dockerfile. This ran into a frustrating problem: Docker's CMake build was silently ignoring our `-DCMAKE_CUDA_ARCHITECTURES=121` build argument and falling back to its default. The Blackwell GPU in the DGX Spark has CUDA compute capability 12.1 (architecture code 121), which is a very new target. Compiling against the wrong CUDA architecture produces a binary that loads but does not actually leverage the GPU, which wastes the entire point of the hardware. The DGX Spark also ships with CUDA 13, and NVIDIA's CUDA 13 base images are a prerequisite for the build to work correctly.

You absolutely can build llama.cpp natively on the DGX Spark and it works well. The key build flags are:

```dockerfile
-DGGML_CUDA=ON
-DGGML_CUDA_F16=ON
-DCMAKE_CUDA_ARCHITECTURES=121
```

We chose to containerize rather than run natively for a specific reason: we wanted the Docker bridge network to create a clean, auditable network boundary between services. In an air-gapped deployment, you want certainty about which services can talk to each other and which cannot. Containers on a defined bridge network give you that control in a way that native processes on the host do not.

The solution to the ARM64 container problem was a community-maintained project by [cslev](https://github.com/cslev/llamacpp-cuda-arm64-docker). He has been publishing pre-built ARM64 + CUDA images to Docker Hub specifically for this hardware class, and the images are publicly available. This is what we use in spark-deploy's `docker-compose.yml` today:

```yaml
image: cslev/llamacpp-cuda-arm64:latest
```

This image saved us significant build time and, more importantly, it is maintained by someone who has already worked through the ARM64 + CUDA 13 compatibility problem. If you are building on DGX Spark, use it. The broader ecosystem is also moving in this direction: two weeks before publishing this post, Docling pushed official CUDA 13 images (`docling-serve-cu130`) for the first time, which we are also using in the stack. The ARM64 + CUDA 13 gap is closing, but community contributors like cslev have been ahead of the official projects.

---

## Challenge 2: Configuring Docling with Open WebUI

Docling is exceptional at what it does: structured extraction from PDFs, OCR, table parsing, and image description. Integrating it with Open WebUI for document processing is genuinely powerful, but the configuration is not well documented and took significant digging to get right.

The short version: Docling runs as a separate container exposing an API on port 5001. Open WebUI has a document processing engine setting that can be pointed at Docling, but the configuration requires a specific JSON payload that is not covered in the Open WebUI documentation. You have to navigate to Settings, then Features, then Document Processing, set the engine to `docling`, and then provide the API parameters as a JSON object.

The working configuration that handles OCR, table extraction, and AI image description is in the repository README, but here is the shape of it:

```json
{
  "do_ocr": true,
  "ocr_engine": "easyocr",
  "ocr_lang": ["en"],
  "pdf_backend": "dlparse_v4",
  "table_mode": "accurate",
  "include_images": true,
  "do_picture_description": true,
  "picture_description_api": "{\"url\": \"http://llamacpp-vision:8001/v1/chat/completions\", ...}"
}
```

Two things that are not obvious from the documentation and both caused real debugging time:

First, the `picture_description_api` field is a JSON string encoded inside the outer JSON object, not a nested object. It needs to be a stringified JSON blob with escaped quotes. This is not how you would expect it to work.

Second, when configuring connections in Open WebUI, you must use Docker service names rather than `localhost`. Open WebUI runs inside the Docker network, so `http://localhost:8001` will not reach your llama.cpp container. The correct address is `http://llamacpp-vision:8001/v1`. This catches almost everyone on first setup.

The `picture_description_api` field is also how Docling hands image and chart descriptions to the vision model. When a PDF comes in, Docling handles the structure and OCR, then calls out to the vision model for any embedded images or diagrams. This means the vision model workload from document processing goes through Docling, while direct image uploads in chat bypass Docling and go straight to the vision model. Keeping these paths separate matters for GPU scheduling.

---

## Challenge 3: Multi-Model Routing on Unified Memory

The 128GB unified memory on the DGX Spark is simultaneously its most compelling feature and the thing that requires the most thought to use well.

The upside is real. Running Llama 3.3 70B at high quantization on a single device, a model that would require multiple A100s on traditional hardware, is genuinely possible. The full context window stays in memory. You can experiment with very large models in a way that most on-premises hardware simply cannot accommodate.

But we found that the real value for production client deployments is not in running one enormous model. It is in running several smaller, specialized ones simultaneously. The 128GB pool lets you load a general chat model, a vision model, and a coding model at the same time, all on one device, while still leaving memory for Docling's OCR pipeline and Open WebUI's backend. Unified memory is somewhat slower than discrete VRAM at peak throughput, but the capacity lets you pack in a configuration that would be physically impossible to run otherwise.

Our current default configuration uses Llama 3.1 8B Instruct (Q4, approximately 4.6GB) for general chat and IBM Granite Vision 3.3-2B (Q8, approximately 1.3GB) for vision tasks. This is intentionally conservative, leaving substantial headroom for document processing workloads and concurrent requests. The Spark genuinely excels here: vision model for Docling, chat model for the team, coding model if needed, all alive at the same time with memory to spare. We are pushing the hardware to maximize the number of useful services running concurrently rather than chasing benchmark numbers on a single large model.

For multi-model routing, we integrated `llama-swap`, a lightweight OpenAI-compatible proxy that routes requests to the correct llama.cpp instance based on the `model` field. From Open WebUI's perspective, it connects to one endpoint. The user picks from a dropdown and the right backend handles it transparently.

```
User -> Nginx (HTTPS) -> Open WebUI -> llama-swap -> llamacpp-llama (text)
                                                   -> llamacpp-vision (images)
                      -> Docling -> llamacpp-vision (PDF/document processing)
```

---

## Challenge 4: HTTPS on a Closed Network

This is relatively standard practice for on-premises deployments, so we will keep it brief. Let's Encrypt does not work on a network that cannot reach the internet. The client in this deployment has an internal CA, and the DGX Spark is connected to it. Nginx handles SSL termination, certificates live in `nginx/ssl/`, and the deploy script generates a self-signed cert for operators who are standing up the stack for the first time before connecting it to an internal CA.

HTTP on port 80 redirects to HTTPS on port 443. All inter-service communication stays inside the Docker bridge network. The full SSL setup is documented in `nginx/ssl/README.md` in the repository.

---

## Challenge 5: Tracing Your Full Stack's Provenance

When you run AI on-premises, you still need to understand where your models and dependencies came from. The inference engine, the document processing library, the OCR backend, the vision model: each is a node in a supply chain. In some deployment contexts, every node has to meet the same standards as the primary model.

We ran into this concretely when evaluating OCR backends for Docling. RapidOCR, a popular lightweight option, is built on PaddleOCR from Baidu. Depending on your deployment context and compliance requirements, that may or may not be acceptable. We standardized on EasyOCR as the default, with Tesseract available as an alternative.

Air-gapped means your data does not leave the building. It does not automatically answer questions about model licensing, where the weights were trained, or what the dependency graph of your processing libraries looks like. Worth understanding before deployment.

---

## On Open Source and Why We Published This

We solved a lot of problems building this stack. The ARM64 + CUDA 13 gap. The Docling configuration that is not in the docs. The multi-model routing pattern. The unified memory tradeoffs for production workloads.

None of these were problems we invented. They are problems any team will hit when trying to deploy a serious AI stack on DGX Spark hardware for an air-gapped client. We benefited directly from open-source contributors like cslev, who published ARM64-compatible llama.cpp images before any official solution existed. The least we can do is pay that forward.

dgx-spark-ai-stack exists because we think this configuration is useful enough and non-obvious enough that publishing it saves other teams real time. If you are running into the ARM64 + CUDA wall, or trying to get Docling talking to Open WebUI in a way that actually works, or thinking through how to structure an air-gapped inference deployment, the repo is meant to be a working starting point rather than a blank page.

---

## What We Built

The full stack deploys with a single script:

```bash
git clone git@github.com:AlaiPartners/dgx-spark-ai-stack.git
cd dgx-spark-ai-stack
cp .env.example .env
./scripts/deploy.sh
```

The deploy script handles SSL certificate generation, default model downloads, and service startup. The result is Open WebUI accessible at `https://[server]`, Docling handling document processing, llama.cpp running GPU-accelerated inference across text and vision models, Nginx enforcing HTTPS, and llama-swap handling model routing. All containerized, all composable, no external dependencies at runtime.

The `add_model.py` tool in the repo guides operators through adding new models: selection, quantized GGUF download from HuggingFace, and automatic Docker Compose configuration. For fully offline setups, it supports pointing at local GGUF files already on the machine.

The repo is at [**github.com/AlaiPartners/dgx-spark-ai-stack**](https://github.com/AlaiPartners/dgx-spark-ai-stack). Issues and contributions are welcome, particularly from anyone running similar hardware or air-gapped deployments who has hit problems we have not documented yet.

---

*Daniel Lund is CTO and co-founder of [Alai Partners](https://alaipartners.com), an AI infrastructure consulting firm specializing in enterprise AI deployments, DGX infrastructure, and secure on-premises AI systems.*

---

*Tags: AI Infrastructure, On-Premises AI, NVIDIA DGX Spark, llama.cpp, Docker, ARM64, CUDA 13, Enterprise AI, Air-Gapped Deployment, Open Source, Docling*
