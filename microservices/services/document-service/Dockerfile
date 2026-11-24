FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
  curl libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-xlib-2.0-0 \
  libffi-dev shared-mime-info tesseract-ocr tesseract-ocr-eng \
  && rm -rf /var/lib/apt/lists/*
COPY microservices/shared /app/shared
COPY microservices/services/document-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-calc \
  fontconfig fonts-crosextra-carlito \
  && rm -rf /var/lib/apt/lists/*
# Poppins headings and Carlito (Calibri-compatible) body text for the ToC course-outline PDF.
COPY microservices/services/document-service/fonts/poppins /usr/share/fonts/truetype/poppins
RUN fc-cache -f
COPY microservices/services/document-service/app ./app
RUN python -m app.pdf_font_check
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
EXPOSE 8006
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8006/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
