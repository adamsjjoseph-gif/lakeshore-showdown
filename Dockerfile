# Lakeshore Showdown — tiny image, Python standard library only (no pip installs).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
# The SQLite database lives on a persistent volume mounted at /data
ENV PORT=8080 DB_PATH=/data/spiff.db PYTHONUNBUFFERED=1
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/healthz'%os.environ.get('PORT','8080'))" || exit 1
CMD ["python", "server.py"]
