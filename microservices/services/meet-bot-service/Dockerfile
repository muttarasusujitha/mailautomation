FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
WORKDIR /app
COPY microservices/services/meet-bot-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Used only for the one-time, localhost-only Google login screen.  The normal
# service never exposes VNC or noVNC.
RUN apt-get update && apt-get install -y --no-install-recommends x11vnc novnc websockify espeak-ng \
    && rm -rf /var/lib/apt/lists/*
COPY microservices/services/meet-bot-service/app ./app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010', timeout=3)" || exit 1
# The Playwright base image's xvfb-run waits indefinitely for a readiness
# signal that its bundled Xvfb does not emit. Start Xvfb directly, then exec
# the health server / bot process so the container can become healthy.
# Docker can retain a stale X lock after an unclean stop.  This container owns
# display :99, so clear only that display's lock/socket before starting Xvfb.
CMD ["sh", "-c", "rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 && Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp & exec python -m app.main"]
