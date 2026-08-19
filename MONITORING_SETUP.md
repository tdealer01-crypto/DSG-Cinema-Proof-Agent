# Monitoring & Logging Setup Guide

Complete monitoring and logging infrastructure for DSG Z3 Solver Service.

## Overview

This setup includes:
- ✅ **Structured JSON Logging** - Easy parsing and analysis
- ✅ **Prometheus Metrics** - Real-time performance monitoring
- ✅ **Azure Application Insights** - Cloud-native monitoring (optional)
- ✅ **Audit Trails** - Security and compliance logging
- ✅ **Health Checks** - Kubernetes readiness/liveness probes
- ✅ **Performance Tracking** - Function and API monitoring

---

## 1. Quick Start

### 1.1 Install Dependencies

```bash
# Install monitoring libraries
pip install -r requirements.txt

# Verify installation
python -c "from monitoring import setup_logging; print('✓ Monitoring module loaded')"
```

### 1.2 Run Service with Monitoring

```bash
# Default (INFO level logging to console + file)
python z3_main.py

# With debug logging
LOG_LEVEL=DEBUG python z3_main.py

# With Azure Insights
ENABLE_AZURE_INSIGHTS=true \
AZURE_INSTRUMENTATION_KEY=your-key \
python z3_main.py

# With custom log file
LOG_FILE=/var/log/z3-solver/service.log python z3_main.py
```

### 1.3 Check Service Health

```bash
# Health status
curl http://localhost:8080/health

# Liveness probe
curl http://localhost:8080/health/live

# Readiness probe
curl http://localhost:8080/health/ready

# View metrics
curl http://localhost:8080/metrics

# Service status
curl http://localhost:8080/status
```

---

## 2. Logging

### 2.1 Log Levels

| Level | Usage | Example |
|-------|-------|---------|
| DEBUG | Detailed diagnostic info | Function entry/exit, variable values |
| INFO | General informational | API requests, solve completion |
| WARNING | Warning conditions | Auth failures, Z3 timeouts |
| ERROR | Error events | Exceptions, solve failures |
| CRITICAL | Critical failures | Service shutdown |

### 2.2 Configuration

Set log level via environment variable:

```bash
# Production
LOG_LEVEL=INFO python z3_main.py

# Development
LOG_LEVEL=DEBUG python z3_main.py

# Minimal
LOG_LEVEL=WARNING python z3_main.py
```

### 2.3 Log Output

Logs are written to:
- **Console (stdout)**: Real-time monitoring
- **File (`/var/log/z3-solver/service.log`)**: Persistent storage

### 2.4 Log Format (JSON)

All logs are structured JSON for easy parsing:

```json
{
  "timestamp": "2026-08-19T11:52:30.123456Z",
  "level": "INFO",
  "name": "z3-solver-service",
  "message": "Solve request completed",
  "extra": {
    "timestamp": "2026-08-19T11:52:30.123456Z",
    "context": {
      "request_id": "req-12345",
      "problem_type": "qubo"
    },
    "duration_ms": 156
  }
}
```

### 2.5 Log Rotation

Logs are automatically rotated when they reach 100 MB:
- Max file size: 100 MB
- Backup copies: 10 (1 GB total)
- Old logs: Automatically archived with `.1`, `.2`, etc. suffixes

---

## 3. Prometheus Metrics

### 3.1 Available Metrics

#### Solver Metrics

```
solver_requests_total{problem_type="qubo",status="SAT"}
  - Total solve requests by type and status

solver_duration_seconds{problem_type="qubo",status="SAT"}
  - Time to solve (histogram with buckets)
  - Buckets: 0.1s, 0.5s, 1s, 2.5s, 5s, 10s, 30s

solver_queue_size
  - Number of pending requests

z3_timeout_errors_total{problem_type="qubo"}
  - Z3 timeout count

z3_sat_results_total{problem_type="qubo",result="SAT"}
  - SAT/UNSAT results
```

#### API Metrics

```
api_requests_total{method="POST",endpoint="/solve",status_code="200"}
  - Total API requests

api_request_duration_seconds{method="POST",endpoint="/solve"}
  - API response time (histogram)
  - Buckets: 0.01s, 0.05s, 0.1s, 0.25s, 0.5s, 1s, 2.5s, 5s

active_requests
  - Currently processing requests

api_errors_total{error_type="ValueError"}
  - Total errors by type
```

#### System Metrics

```
service_uptime_seconds
  - Service uptime in seconds

auth_failures_total{reason="Invalid token"}
  - Authentication failures

errors_total{error_type="TimeoutError"}
  - Total errors by category
```

### 3.2 Scrape Configuration (Prometheus)

Add to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'z3-solver'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: '/metrics'
    scrape_interval: 15s
    scrape_timeout: 10s
```

### 3.3 View Metrics

```bash
# Raw Prometheus format
curl http://localhost:8080/metrics

# Specific metric
curl http://localhost:8080/metrics | grep solver_requests_total

# Filter by label
curl http://localhost:8080/metrics | grep 'solver_requests_total{problem_type="qubo"}'
```

---

## 4. Azure Application Insights

### 4.1 Setup

#### Step 1: Create Application Insights Resource

```bash
# Using Azure CLI
az monitor app-insights component create \
  --app dsg-z3-solver \
  --location westus3 \
  --resource-group dsg-resources \
  --application-type web

# Get instrumentation key
INSTRUMENTATION_KEY=$(az monitor app-insights component show \
  --app dsg-z3-solver \
  --resource-group dsg-resources \
  --query instrumentationKey -o tsv)

echo "INSTRUMENTATION_KEY=$INSTRUMENTATION_KEY"
```

#### Step 2: Enable in Service

```bash
# Enable monitoring
ENABLE_AZURE_INSIGHTS=true \
AZURE_INSTRUMENTATION_KEY=$INSTRUMENTATION_KEY \
python z3_main.py
```

### 4.2 Queries

#### Monitor Error Rate

```kusto
requests
| where name == "/solve"
| summarize
    requests=count(),
    errors=sum(toint(not(success))),
    error_rate=sum(toint(not(success))) * 100.0 / count()
by bin(timestamp, 1m)
```

#### Solver Performance

```kusto
customMetrics
| where name == "solver_duration_seconds"
| summarize
    avg_duration=avg(todouble(value)),
    max_duration=max(todouble(value)),
    p95_duration=percentile(todouble(value), 95)
by problem_type
```

#### Timeout Tracking

```kusto
customMetrics
| where name == "z3_timeout_errors_total"
| summarize
    timeouts=sum(todouble(value))
by bin(timestamp, 1h), problem_type
```

---

## 5. Audit Logging

### 5.1 Audit Events

Audit trail logs all:
- ✅ Authentication attempts (success/failure)
- ✅ Solve requests with results
- ✅ Z3 solver results
- ✅ Timeout events
- ✅ Errors and exceptions

### 5.2 Audit Log Format

```json
{
  "timestamp": "2026-08-19T11:52:30Z",
  "level": "INFO",
  "name": "audit",
  "message": "Authentication successful",
  "extra": {
    "context": {
      "request_id": "req-12345"
    },
    "status": "success"
  }
}
```

### 5.3 Audit Log Location

`/var/log/z3-solver/audit.log`

### 5.4 Retention Policy

- **Default**: 365 days
- **Configurable**: Edit `MONITORING_SETUP.md` retention section

---

## 6. Health Checks

### 6.1 Endpoints

#### `/health` - Full Status

Returns comprehensive health information:

```bash
curl http://localhost:8080/health
```

Response:
```json
{
  "status": "healthy",
  "uptime_seconds": 3600,
  "uptime_human": "1h 0m 0s",
  "total_requests": 1234,
  "error_count": 5,
  "last_successful_solve": "2026-08-19T11:52:30Z",
  "error_rate": 0.004,
  "z3_version": "4.13.0"
}
```

#### `/health/live` - Liveness Probe

For Kubernetes liveness probe:

```bash
curl http://localhost:8080/health/live
# Always returns 200 if service is running
```

#### `/health/ready` - Readiness Probe

For Kubernetes readiness probe:

```bash
curl http://localhost:8080/health/ready
# Returns 200 if ready, 503 if degraded
```

#### `/status` - Detailed Status

```bash
curl http://localhost:8080/status
```

### 6.2 Health Status Levels

| Status | Meaning | Error Rate |
|--------|---------|-----------|
| healthy | All systems operational | < 1% |
| degraded | High error rate | ≥ 1% and < 10% |
| unhealthy | Severe issues | ≥ 10% |

---

## 7. Docker Logging

### 7.1 Docker Compose with Logging

```yaml
version: '3.8'
services:
  z3-solver:
    build: .
    ports:
      - "8080:8080"
    environment:
      LOG_LEVEL: INFO
      ENABLE_AZURE_INSIGHTS: "false"
    volumes:
      - z3-logs:/var/log/z3-solver
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "10"
        labels: "service=z3-solver"

volumes:
  z3-logs:
    driver: local
```

### 7.2 View Docker Logs

```bash
# Real-time logs
docker logs -f z3-solver

# Last 100 lines
docker logs --tail 100 z3-solver

# Follow specific time
docker logs --since 2026-08-19T10:00:00Z z3-solver
```

---

## 8. Kubernetes Setup

### 8.1 Deployment with Health Checks

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: z3-solver
spec:
  replicas: 3
  selector:
    matchLabels:
      app: z3-solver
  template:
    metadata:
      labels:
        app: z3-solver
    spec:
      containers:
      - name: z3-solver
        image: tdealer01acr.azurecr.io/z3-solver:latest
        ports:
        - containerPort: 8080
        env:
        - name: LOG_LEVEL
          value: INFO
        - name: ENABLE_AZURE_INSIGHTS
          value: "true"
        - name: AZURE_INSTRUMENTATION_KEY
          valueFrom:
            secretKeyRef:
              name: z3-secrets
              key: instrumentation-key

        # Liveness probe
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10

        # Readiness probe
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5

        # Logs volume
        volumeMounts:
        - name: logs
          mountPath: /var/log/z3-solver

      volumes:
      - name: logs
        emptyDir: {}

---
apiVersion: v1
kind: Service
metadata:
  name: z3-solver
spec:
  selector:
    app: z3-solver
  ports:
  - protocol: TCP
    port: 8080
    targetPort: 8080
  type: LoadBalancer
```

### 8.2 Prometheus ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: z3-solver
spec:
  selector:
    matchLabels:
      app: z3-solver
  endpoints:
  - port: web
    path: /metrics
    interval: 30s
```

---

## 9. Alerting Examples

### 9.1 Prometheus Rules

```yaml
groups:
- name: z3-solver
  interval: 1m
  rules:
  # High error rate
  - alert: Z3HighErrorRate
    expr: |
      rate(errors_total[5m]) > 0.1
    for: 5m
    annotations:
      summary: "Z3 Solver high error rate"
      description: "Error rate > 10% for 5 minutes"

  # Long solve times
  - alert: Z3SlowSolving
    expr: |
      histogram_quantile(0.95, solver_duration_seconds) > 10
    for: 5m
    annotations:
      summary: "Z3 Solver slow (95th percentile > 10s)"

  # Z3 timeouts
  - alert: Z3Timeouts
    expr: |
      rate(z3_timeout_errors_total[5m]) > 0.05
    for: 5m
    annotations:
      summary: "Z3 Solver timeout rate high"

  # Service unavailable
  - alert: Z3ServiceDown
    expr: |
      up{job="z3-solver"} == 0
    for: 2m
    annotations:
      summary: "Z3 Solver service is down"
```

### 9.2 Azure Alerts

```bash
# High error rate alert
az monitor metrics alert create \
  --name z3-high-error-rate \
  --resource-group dsg-resources \
  --description "Alert when error rate exceeds 10%" \
  --condition "avg Failed > 0.1" \
  --evaluation-frequency 5m \
  --window-size 5m \
  --severity 2
```

---

## 10. Performance Tuning

### 10.1 Reduce Logging Overhead

```bash
# Production: Use WARNING level
LOG_LEVEL=WARNING python z3_main.py

# Disable metrics collection (if needed)
# - Modify monitoring.py to disable specific metrics
```

### 10.2 Log Rotation Settings

Edit `monitoring.py`:

```python
# Reduce backup count for less disk usage
backupCount=5  # Default: 10

# Adjust max bytes for rotation
maxBytes=50_000_000  # 50 MB (default: 100 MB)
```

### 10.3 Prometheus Scrape Interval

Adjust in Prometheus config:

```yaml
scrape_interval: 30s  # Default: 15s (less frequent scraping)
```

---

## 11. Troubleshooting

### 11.1 No Logs Appearing

```bash
# Check log file location
ls -la /var/log/z3-solver/

# Check permissions
chmod 755 /var/log/z3-solver/

# Verify logging is enabled
LOG_LEVEL=DEBUG python z3_main.py
```

### 11.2 High Disk Usage

```bash
# Check log sizes
du -sh /var/log/z3-solver/

# Enable log rotation sooner
# Edit monitoring.py: maxBytes=10_000_000 (10 MB)

# Compress old logs
gzip /var/log/z3-solver/service.log.*
```

### 11.3 Metrics Not Showing

```bash
# Check metrics endpoint
curl -v http://localhost:8080/metrics

# Verify Prometheus can reach service
prometheus_tool rule test -d rulefiles.yml

# Check service connectivity
netstat -tuln | grep 8080
```

### 11.4 Azure Insights Not Working

```bash
# Verify instrumentation key
echo $AZURE_INSTRUMENTATION_KEY

# Check SDK initialization
grep "Application Insights enabled" logs

# Test connectivity
curl -X POST https://dc.applicationinsights.azure.com/v2/track \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=Microsoft.ApplicationInsights.$INSTRUMENTATION_KEY.Event"
```

---

## 12. References

- [Python Logging Docs](https://docs.python.org/3/library/logging.html)
- [Prometheus Metrics](https://prometheus.io/docs/concepts/data_model/)
- [OpenTelemetry SDK](https://opentelemetry.io/docs/instrumentation/python/)
- [Azure Application Insights](https://docs.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview)
- [FastAPI Monitoring](https://fastapi.tiangolo.com/)
- [Kubernetes Health Checks](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-probes/)

---

## 13. Next Steps

1. ✅ Deploy monitoring stack
2. ✅ Configure Azure Insights
3. ✅ Setup Prometheus/Grafana dashboards
4. ✅ Configure alerting rules
5. ✅ Establish on-call procedures
