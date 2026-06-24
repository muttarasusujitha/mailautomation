FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    fonts-dejavu-core \
    libcairo2 \
    libffi8 \
    libgdk-pixbuf-2.0-0 \
    libharfbuzz-subset0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    shared-mime-info \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
  && addgroup --system app \
  && adduser --system --ingroup app app

COPY --chown=root:root --chmod=555 agents ./agents
COPY --chown=root:root --chmod=555 config ./config
COPY --chown=root:root --chmod=555 models ./models
COPY --chown=root:root --chmod=555 routes ./routes
COPY --chown=root:root --chmod=555 scripts ./scripts
COPY --chown=root:root --chmod=555 templates ./templates
COPY --chown=root:root --chmod=555 utils ./utils
COPY --chown=root:root --chmod=444 celery_app.py config.py database.py generate_token.py main.py ./
RUN mkdir -p uploads assets && chown -R app:app uploads config assets

EXPOSE 8000

USER app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
