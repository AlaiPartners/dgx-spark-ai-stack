#!/bin/sh
# Preload gpt-oss:20b with keep_alive: -1 so it stays resident. Use /api/chat with a
# real message and stream: false so the model runs a full inference. Best-effort:
# exit 0 if the model is not pulled yet (fresh install).
set -e
json='{"model": "gpt-oss:20b", "messages": [{"role": "user", "content": "Reply with OK."}], "stream": false, "keep_alive": -1}'
printf '%s' "$json" | curl -s -H "Content-Type: application/json" -d @- http://ollama:11434/api/chat || true
