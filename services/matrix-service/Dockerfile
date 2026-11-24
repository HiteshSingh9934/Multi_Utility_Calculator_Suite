FROM python:3.12-slim

# No .pyc files in the image; print logs straight to "docker logs"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

WORKDIR /app

# An unprivileged user to run the app (numeric, so Kubernetes can verify runAsNonRoot)
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser

# Dependencies first: editing the code later reuses this cached layer
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py ./

USER 10001
EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=2)"]

# gunicorn is a production web server; scale by adding containers, not workers
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--access-logfile", "-", "--no-control-socket", "app:app"]
