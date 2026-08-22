# Phase 2: Sentry Error Tracking Integration

## Overview

Phase 2 implements comprehensive error tracking and monitoring using Sentry, building on Phase 1's structured logging foundation. This phase adds:

1. **Advanced Sentry Configuration** - Performance monitoring and custom integrations
2. **Error Monitoring Endpoints** - REST APIs for error tracking and analysis
3. **Sensitive Data Filtering** - Automatic removal of credentials from error reports
4. **Cinema-Specific Metrics** - Custom error capture for business logic failures
5. **Performance Tracking** - Z3 solver operation monitoring

## Architecture

```
Cinema API (FastAPI)
    ↓
Middleware Layer
    ├── ErrorHandlingMiddleware
    ├── RequestTrackingMiddleware
    └── CORSMiddleware
    ↓
Application Routes
    ├── Verification API (/api/verify)
    ├── Billing API (/billing/*)
    ├── Metrics Router (/api/metrics/*)
    └── Error Monitoring Router (/api/errors/*)
    ↓
Sentry Integration
    ├── Error Capture & Filtering
    ├── Transaction Sampling
    ├── Performance Tracking
    └── Custom Context
    ↓
Error Log Files
    └── logs/
        ├── error.log (rotating, 10MB)
        └── combined.log (rotating, 50MB)
```

## Files Added/Modified

### New Files

#### `sentry_config.py` (171 lines)
Advanced Sentry configuration with performance monitoring.

**Key Functions:**
- `initialize_sentry_advanced()` - Initialize Sentry with FastAPI integration
- `filter_errors(event, hint)` - Filter non-critical errors and sanitize data
- `filter_transactions(event, hint)` - Reduce noise from health checks
- `sanitize_error_message(message)` - Remove API keys from error messages
- `capture_cinema_error()` - Capture Cinema-specific errors with context
- `capture_z3_performance()` - Track Z3 solver performance
- `capture_verification_flow()` - Capture verification metrics
- `SentryPerformanceTracker` - Context manager for operation timing

**Environment Variables:**
```bash
SENTRY_DSN=https://your-key@sentry.io/project-id
SENTRY_ENVIRONMENT=production|staging|development
SENTRY_RELEASE=1.0.0
SENTRY_SAMPLE_RATE=1.0           # Error sampling (0.0-1.0)
SENTRY_TRACES_SAMPLE_RATE=0.1    # Transaction sampling (0.0-1.0)
```

#### `error_monitoring.py` (240 lines)
REST endpoints for error tracking and analysis.

**Endpoints:**

1. **GET /api/errors**
   - Retrieve recent error events
   - Query Parameters:
     - `limit`: Number of errors (1-500, default 50)
     - `minutes`: Time window (1-1440, default 60)
   - Returns: List of ErrorEvent objects

2. **GET /api/errors/{error_id}**
   - Get detailed error information
   - Path Parameters:
     - `error_id`: Error ID from recent errors or Sentry
   - Returns: Complete error event object

3. **GET /api/errors/stats**
   - Error statistics for time period
   - Query Parameters:
     - `minutes`: Time window (1-1440, default 60)
   - Returns: ErrorStats with totals and top error types

4. **POST /api/errors/test**
   - Test error capture and Sentry integration
   - Body:
     ```json
     {
       "error_type": "test_error|value_error|runtime_error",
       "message": "Test error message",
       "should_raise": true
     }
     ```
   - Returns: Capture status and details

5. **GET /api/errors/sentry/health**
   - Check Sentry integration health
   - Returns: Status, configuration, and integration info

#### `tests/test_sentry_integration.py` (350 lines)
Comprehensive test suite for Sentry integration.

**Test Classes:**
- `TestSentryConfiguration` - Configuration and filtering tests
- `TestSentryCinemaIntegration` - Cinema-specific error capture tests
- `TestSentryPerformanceTracker` - Performance tracking tests
- `TestErrorMonitoringEndpoints` - Error monitoring endpoint tests
- `TestErrorSanitization` - Message sanitization pattern tests
- `TestSentryIntegrationEndToEnd` - Integration flow tests

### Modified Files

#### `cinema_main.py`
- Added import: `from error_monitoring import router as error_monitoring_router`
- Added router: `app.include_router(error_monitoring_router)`

#### `requirements.txt`
- Already includes: `sentry-sdk[fastapi]==1.39.2`
- Already includes: `psutil==5.9.6`

## Error Filtering Strategy

### Filtered Errors (Not Sent to Sentry)
- Connection/timeout errors in test contexts
- Health check health checks (to reduce noise)
- Metrics endpoint access

### Sanitized Error Messages
The following patterns are automatically removed from error messages:

```python
# Stripe live keys
sk_live_\w+             → sk_live_***
rk_live_\w+             → rk_live_***

# DSG API keys
dsg_\w+_[0-9a-f]+       → dsg_***

# Webhook secrets
whsec_[A-Za-z0-9]{16,}  → whsec_***
```

## Cinema-Specific Monitoring

### Error Capture
```python
from sentry_config import capture_cinema_error

capture_cinema_error(
    error_type="verification_failed",
    details={"reason": "Invalid input", "context": "user_id_123"},
    level="error"
)
```

### Z3 Performance Tracking
```python
from sentry_config import capture_z3_performance

capture_z3_performance(
    solver_name="sat_solver",
    duration_ms=750.5,
    result="SAT"
)
```

### Verification Flow Tracking
```python
from sentry_config import capture_verification_flow

capture_verification_flow(
    channel="stripe",
    execution_id="exec_abc123",
    decision="ALLOW",
    duration_ms=1234.5
)
```

### Performance Tracking
```python
from sentry_config import SentryPerformanceTracker

with SentryPerformanceTracker("verify_operation", critical_threshold_ms=500):
    # Your operation here
    result = perform_verification()
```

## Usage Examples

### Initialize Sentry in Application
Sentry is automatically initialized on import if `SENTRY_DSN` is set:

```python
from sentry_config import initialize_sentry_advanced

# Automatic initialization happens here:
initialize_sentry_advanced()
```

### Capture Custom Error
```python
import sentry_sdk
from sentry_config import capture_cinema_error

capture_cinema_error(
    error_type="stripe_webhook_error",
    details={
        "event_id": "evt_123",
        "status": "failed",
        "retry_count": 3
    },
    level="warning"
)
```

### Query Error History
```bash
# Get last 50 errors from last hour
curl http://localhost:8000/api/errors

# Get errors from last 4 hours (limit 100)
curl "http://localhost:8000/api/errors?limit=100&minutes=240"

# Get error details
curl http://localhost:8000/api/errors/error_id_123

# Get error statistics
curl http://localhost:8000/api/errors/stats?minutes=60

# Check Sentry health
curl http://localhost:8000/api/errors/sentry/health
```

### Test Error Capture
```bash
# Test with ValueError
curl -X POST http://localhost:8000/api/errors/test \
  -H "Content-Type: application/json" \
  -d '{
    "error_type": "value_error",
    "message": "Test validation error",
    "should_raise": true
  }'

# Test without raising (just capture)
curl -X POST http://localhost:8000/api/errors/test \
  -H "Content-Type: application/json" \
  -d '{
    "error_type": "test_error",
    "message": "Test message",
    "should_raise": false
  }'
```

## Testing

### Run Sentry Integration Tests
```bash
# Run all Sentry tests
python -m pytest tests/test_sentry_integration.py -v

# Run specific test class
python -m pytest tests/test_sentry_integration.py::TestSentryConfiguration -v

# Run tests with coverage
python -m pytest tests/test_sentry_integration.py --cov=sentry_config --cov=error_monitoring
```

### Manual Testing

1. **Verify Sentry Configuration**
   ```bash
   curl http://localhost:8000/api/errors/sentry/health
   ```
   Expected: Configuration details showing Sentry enabled

2. **Test Error Capture**
   ```bash
   curl -X POST http://localhost:8000/api/errors/test \
     -H "Content-Type: application/json" \
     -d '{"error_type": "test_error", "message": "Test", "should_raise": false}'
   ```
   Expected: `{"status": "captured", "error_type": "test_error", ...}`

3. **Verify Error Logging**
   ```bash
   curl http://localhost:8000/api/errors?limit=10&minutes=60
   ```
   Expected: Recent error events (may be empty if no recent errors)

4. **Check Error Statistics**
   ```bash
   curl http://localhost:8000/api/errors/stats
   ```
   Expected: Statistics object with error counts and types

## Environment Setup

### Development
```bash
# .env.local or .env.development
SENTRY_DSN=
SENTRY_ENVIRONMENT=development
SENTRY_RELEASE=dev
SENTRY_SAMPLE_RATE=1.0
SENTRY_TRACES_SAMPLE_RATE=0.5
LOG_DIR=logs
LOG_LEVEL=DEBUG
```

### Staging
```bash
# .env.staging
SENTRY_DSN=https://your-key@sentry.io/staging-project
SENTRY_ENVIRONMENT=staging
SENTRY_RELEASE=1.0.0-rc1
SENTRY_SAMPLE_RATE=1.0
SENTRY_TRACES_SAMPLE_RATE=0.2
LOG_DIR=logs
LOG_LEVEL=INFO
```

### Production
```bash
# .env.production (via Key Vault)
SENTRY_DSN=https://your-key@sentry.io/production-project
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=1.0.0
SENTRY_SAMPLE_RATE=0.1        # Sample 10% of errors
SENTRY_TRACES_SAMPLE_RATE=0.01 # Sample 1% of transactions
LOG_DIR=/var/log/cinema
LOG_LEVEL=WARNING
```

## Sentry Dashboard Configuration

### Recommended Alert Rules

1. **Critical Errors**
   - Trigger: Error level ≥ CRITICAL
   - Frequency: First occurrence
   - Action: Send to on-call

2. **High Error Rate**
   - Trigger: >10 errors per 5 minutes
   - Frequency: Per 5 minutes
   - Action: Alert team

3. **Slow Z3 Operations**
   - Trigger: Tag `performance_category:slow`
   - Frequency: Per occurrence
   - Action: Log to monitoring

4. **Failed Verifications**
   - Trigger: Message contains "verification_failed"
   - Frequency: Threshold (5 per hour)
   - Action: Escalate to billing team

### Recommended Dashboards

1. **Error Overview**
   - Total errors (trend)
   - Error types distribution
   - Top error messages
   - Error rate by endpoint

2. **Verification Metrics**
   - Verification success rate
   - Average verification time
   - Z3 solver performance
   - Decision distribution (ALLOW/REVIEW/BLOCK)

3. **Performance Monitor**
   - Slow operations count
   - Operation latency distribution
   - Z3 solver timing
   - Request throughput

## Troubleshooting

### Sentry Not Capturing Errors

1. **Check DSN Configuration**
   ```bash
   curl http://localhost:8000/api/errors/sentry/health
   ```
   If status is "disabled", verify `SENTRY_DSN` is set

2. **Verify Integration**
   ```bash
   python -c "from sentry_config import initialize_sentry_advanced; initialize_sentry_advanced()"
   ```

3. **Test Error Capture**
   ```bash
   curl -X POST http://localhost:8000/api/errors/test \
     -H "Content-Type: application/json" \
     -d '{"error_type": "test_error", "should_raise": false}'
   ```

### High Error Volume

1. **Adjust Sampling Rates**
   - Reduce `SENTRY_SAMPLE_RATE` to 0.1-0.5
   - Reduce `SENTRY_TRACES_SAMPLE_RATE` to 0.01-0.05

2. **Adjust Filtering**
   - Review `filter_errors()` in sentry_config.py
   - Add more error types to filtered list

3. **Review Alert Rules**
   - Check Sentry dashboard alert configuration
   - Disable or adjust rules generating false positives

### Missing API Keys in Sanitization

If you see API keys in error reports:

1. **Add Pattern to `sanitize_error_message()`**
   ```python
   # In sentry_config.py, sanitize_error_message()
   message = re.sub(r"your_pattern_\w+", "your_pattern_***", message)
   ```

2. **Update `filter_errors()`**
   - Add the key format to the exception filtering logic

3. **Test Sanitization**
   ```bash
   python -m pytest tests/test_sentry_integration.py::TestErrorSanitization -v
   ```

## Performance Considerations

### Error Sampling
- Production: Sample 10% of errors (SENTRY_SAMPLE_RATE=0.1)
- Staging: 100% sampling (SENTRY_SAMPLE_RATE=1.0)
- Development: 100% sampling

### Transaction Sampling
- Health checks/metrics: Filtered (not sampled)
- Regular operations: 1-5% sampling
- Verification flows: 10-50% sampling

### Breadcrumb Limits
- Maximum 50 breadcrumbs per event
- Breadcrumbs include request tracking and logging

## Security Considerations

### Sensitive Data Handling

1. **Automatic Sanitization**
   - All error messages are sanitized before sending to Sentry
   - API keys, tokens, and secrets are replaced with `***`

2. **Error Filtering**
   - Non-critical errors are filtered out
   - Test-context errors are not sent

3. **PII Handling**
   - `send_default_pii=False` in Sentry config
   - User data in error context requires explicit handling

4. **Environment Separation**
   - Each environment has separate Sentry project
   - Production uses different DSN than staging/dev

## Monitoring and Metrics

### Key Metrics to Monitor

1. **Error Rate**
   - Errors per minute by endpoint
   - Error types distribution
   - Top error messages

2. **Performance**
   - Z3 solver latency (p50, p95, p99)
   - Verification operation latency
   - Overall request latency

3. **Business Metrics**
   - Verification success rate
   - Decision distribution (ALLOW/REVIEW/BLOCK)
   - Billing authorization success

4. **System Health**
   - CPU and memory usage
   - Log file sizes and rotation
   - Request tracking coverage

## Success Criteria

Phase 2 is complete when:

- [ ] ✓ Sentry configuration deployed and working
- [ ] ✓ Error monitoring endpoints responding
- [ ] ✓ Sensitive data sanitization active
- [ ] ✓ Cinema-specific errors capturing correctly
- [ ] ✓ Performance tracking working
- [ ] ✓ Test suite passing (100% of test_sentry_integration.py)
- [ ] ✓ Alert rules configured in Sentry
- [ ] ✓ Documentation complete and accurate
- [ ] ✓ GitHub Actions CI/CD passing
- [ ] ✓ Manual testing confirmed working

## Next Steps

After Phase 2 completion:

1. **Phase 3: Advanced Monitoring** (Optional)
   - Real-time dashboards
   - Custom metrics
   - Distributed tracing

2. **Phase 4: Alerts & Escalation** (Optional)
   - On-call integration
   - Automated remediation
   - Incident management

3. **Ongoing Maintenance**
   - Monitor error trends
   - Review alert effectiveness
   - Optimize sampling rates
   - Update sanitization patterns

## References

- [Sentry Documentation](https://docs.sentry.io/)
- [Sentry Python SDK](https://docs.sentry.io/platforms/python/)
- [FastAPI Integration](https://docs.sentry.io/platforms/python/integrations/fastapi/)
- [Performance Monitoring](https://docs.sentry.io/product/performance/)
- [Error Filtering](https://docs.sentry.io/platforms/python/configuration/filtering/)
