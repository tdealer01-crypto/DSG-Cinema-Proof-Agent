FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AUDIT_DB_PATH=/data/dsg_audit.sqlite3
WORKDIR /srv/dsg
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 dsg && mkdir -p /data && chown -R dsg:dsg /data /srv/dsg
USER dsg
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
