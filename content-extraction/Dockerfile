FROM python:3.11-slim

WORKDIR /app

# pymupdf has prebuilt ARM64 wheels; markitdown[docx] for Word → Markdown
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
