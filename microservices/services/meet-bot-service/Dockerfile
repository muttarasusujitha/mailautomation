FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
WORKDIR /app
COPY microservices/services/meet-bot-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY microservices/services/meet-bot-service/app ./app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010', timeout=3)" || exit 1
# The Playwright base image's xvfb-run waits indefinitely for a readiness
# signal that its bundled Xvfb does not emit. Start Xvfb directly, then exec
# the health server / bot process so the container can become healthy.
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp & exec python -m app.main"]
