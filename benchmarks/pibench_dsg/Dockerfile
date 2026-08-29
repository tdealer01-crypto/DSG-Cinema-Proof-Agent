FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY benchmarks/pibench_dsg/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r /app/requirements.txt

COPY benchmarks/pibench_dsg/gate.py /app/gate.py
COPY benchmarks/pibench_dsg/cinema_mcp.py /app/cinema_mcp.py
COPY benchmarks/pibench_dsg/cinema_decision.py /app/cinema_decision.py
COPY benchmarks/pibench_dsg/server.py /app/server.py

EXPOSE 9010
ENTRYPOINT ["python", "/app/server.py"]
CMD ["--host", "0.0.0.0", "--port", "9010"]
