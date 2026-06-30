FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf2.0-0 \
    libffi-dev shared-mime-info \
    && rm -rf /var/lib/apt/lists/*
COPY microservices/shared /app/shared
COPY microservices/services/document-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY microservices/services/document-service/app ./app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
EXPOSE 8006
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8006/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
