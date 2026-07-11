FROM python:3.11-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates zstd \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://ollama.com/install.sh | sh
COPY microservices/shared /app/shared
COPY microservices/services/intelligence-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY microservices/services/intelligence-service/app ./app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
EXPOSE 8005
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8005/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
