"""Tests for Sentry error tracking integration."""

import os
import re
from unittest.mock import MagicMock, patch

import pytest
import sentry_sdk

from error_monitoring import (
    calculate_error_stats,
    get_error_log_file,
    read_recent_errors,
)
from sentry_config import (
    filter_errors,
    filter_transactions,
    sanitize_error_message,
    capture_cinema_error,
    capture_z3_performance,
    SentryPerformanceTracker,
)


class TestSentryConfiguration:
    """Test Sentry configuration and initialization."""

    def test_filter_errors_ignores_test_connection_errors(self):
        """Test that connection errors in tests are filtered."""
        event = {"exception": {"values": [{"value": "Connection failed in test"}]}}
        hint = {
            "exc_info": (
                ConnectionError,
                ConnectionError("test connection"),
                None,
            )
        }

        result = filter_errors(event, hint)
        assert result is None, "Test connection errors should be filtered"

    def test_filter_errors_sanitizes_api_keys(self):
        """Test that API keys are sanitized in error messages."""
        event = {
            "exception": {
                "values": [
                    {"value": "Failed with API key sk_live_abc123def456"}
                ]
            }
        }
        hint = {"exc_info": None}

        result = filter_errors(event, hint)
        assert "sk_live_***" in result["exception"]["values"][0]["value"]
        assert "sk_live_abc123" not in result["exception"]["values"][0]["value"]

    def test_filter_transactions_skips_health_checks(self):
        """Test that health check transactions are filtered."""
        event = {"request": {"url": "http://localhost:8000/health"}}
        hint = {}

        result = filter_transactions(event, hint)
        assert result is None, "Health check transactions should be filtered"

    def test_filter_transactions_skips_metrics(self):
        """Test that metrics endpoint transactions are filtered."""
        event = {"request": {"url": "http://localhost:8000/metrics"}}
        hint = {}

        result = filter_transactions(event, hint)
        assert result is None, "Metrics transactions should be filtered"

    def test_filter_transactions_allows_verification(self):
        """Test that verification transactions are allowed through."""
        event = {"request": {"url": "http://localhost:8000/api/verify"}}
        hint = {}

        result = filter_transactions(event, hint)
        assert result == event, "Verification transactions should be allowed"

    def test_sanitize_stripe_keys(self):
        """Test that Stripe API keys are sanitized."""
        message = "Error with Stripe key sk_live_xyz789abc"
        result = sanitize_error_message(message)
        assert "sk_live_***" in result
        assert "sk_live_xyz789" not in result

    def test_sanitize_dsg_keys(self):
        """Test that DSG API keys are sanitized."""
        message = "DSG error with key dsg_test_abcdef123456_fedcba654321abcdef"
        result = sanitize_error_message(message)
        assert "dsg_***" in result
        assert "abcdef123456" not in result

    def test_sanitize_multiple_keys(self):
        """Test sanitization of multiple key types in one message."""
        message = (
            "Errors: sk_live_123 and rk_live_456 and dsg_live_abc_def"
        )
        result = sanitize_error_message(message)
        assert "sk_live_***" in result
        assert "rk_live_***" in result
        assert "dsg_***" in result
        assert "123" not in result
        assert "456" not in result


class TestSentryCinemaIntegration:
    """Test Cinema-specific error capture."""

    @patch("sentry_sdk.capture_message")
    def test_capture_cinema_error_sets_context(self, mock_capture):
        """Test that cinema error capture sets proper context."""
        capture_cinema_error(
            error_type="verification_failed",
            details={"reason": "Invalid input"},
            level="error",
        )

        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        assert "Cinema Error" in call_args[0][0]

    @patch("sentry_sdk.capture_message")
    def test_capture_z3_performance_marks_slow_operations(
        self, mock_capture
    ):
        """Test that slow Z3 operations are marked as slow."""
        capture_z3_performance("sat_solver", 750.0, "SAT")

        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        assert "Z3 Slow" in call_args[0][0]

    @patch("sentry_sdk.capture_message")
    def test_capture_z3_performance_skips_fast_operations(
        self, mock_capture
    ):
        """Test that fast Z3 operations don't trigger messages."""
        capture_z3_performance("sat_solver", 250.0, "SAT")

        mock_capture.assert_not_called()


class TestSentryPerformanceTracker:
    """Test the performance tracking context manager."""

    def test_performance_tracker_measures_duration(self):
        """Test that the tracker measures operation duration."""
        with SentryPerformanceTracker("test_operation") as tracker:
            pass

        assert tracker.start_time is not None
        assert tracker.transaction is not None

    @patch("sentry_sdk.capture_message")
    def test_performance_tracker_warns_on_slow_operations(
        self, mock_capture
    ):
        """Test that slow operations trigger warnings."""
        with patch("time.time") as mock_time:
            # Simulate a 600ms operation (exceeds default 500ms threshold)
            mock_time.side_effect = [0, 0.6]

            with SentryPerformanceTracker("slow_op", critical_threshold_ms=500):
                pass

            mock_capture.assert_called_once()
            call_args = mock_capture.call_args
            assert "Slow operation" in call_args[0][0]

    @patch("sentry_sdk.capture_message")
    def test_performance_tracker_skips_fast_operations(
        self, mock_capture
    ):
        """Test that fast operations don't trigger warnings."""
        with patch("time.time") as mock_time:
            # Simulate a 300ms operation (below default 500ms threshold)
            mock_time.side_effect = [0, 0.3]

            with SentryPerformanceTracker("fast_op", critical_threshold_ms=500):
                pass

            mock_capture.assert_not_called()


class TestErrorMonitoringEndpoints:
    """Test error monitoring endpoint functions."""

    def test_get_error_log_file_returns_none_if_missing(self):
        """Test that missing error log returns None."""
        with patch("os.path.exists", return_value=False):
            result = get_error_log_file()
            assert result is None

    def test_get_error_log_file_returns_path_if_exists(self):
        """Test that existing error log returns path."""
        with patch("os.path.exists", return_value=True):
            with patch("os.getenv", return_value="logs"):
                result = get_error_log_file()
                assert result is not None
                assert "error.log" in result

    def test_get_recent_errors_respects_limit(self):
        """Test that recent errors respects the limit parameter."""
        errors = read_recent_errors(limit=10)
        assert isinstance(errors, list)
        assert len(errors) <= 10

    def test_get_recent_errors_respects_time_window(self):
        """Test that recent errors respects the time window."""
        errors = read_recent_errors(minutes=5)
        # This is a basic test that it doesn't crash
        assert isinstance(errors, list)

    def test_calculate_error_stats_returns_dict(self):
        """Test that error stats calculation returns proper dict."""
        stats = calculate_error_stats(minutes=60)

        assert isinstance(stats, dict)
        assert "total_errors" in stats
        assert "critical_errors" in stats
        assert "warnings" in stats
        assert "time_period_minutes" in stats
        assert "top_error_types" in stats


class TestErrorSanitization:
    """Test error message sanitization patterns."""

    def test_stripe_live_key_pattern(self):
        """Test Stripe live key sanitization pattern."""
        message = "Payment failed with sk_live_abc123XYZ789"
        result = sanitize_error_message(message)
        assert re.search(r"sk_live_\w+", message) is not None
        assert re.search(r"sk_live_\w+", result) is None
        assert "sk_live_***" in result

    def test_stripe_restricted_key_pattern(self):
        """Test Stripe restricted key sanitization pattern."""
        message = "Auth failed with rk_live_xyz789abc123"
        result = sanitize_error_message(message)
        assert re.search(r"rk_live_\w+", message) is not None
        assert re.search(r"rk_live_\w+", result) is None
        assert "rk_live_***" in result

    def test_dsg_key_pattern(self):
        """Test DSG API key sanitization pattern."""
        message = "Failed with dsg_test_abcdef123456_fedcba654321abcdef123456"
        result = sanitize_error_message(message)
        # Check that the pattern is properly sanitized
        assert "dsg_***" in result

    def test_no_false_positives_in_sanitization(self):
        """Test that sanitization doesn't affect legitimate content."""
        message = "User requested data with key_name sk_test_valid"
        result = sanitize_error_message(message)
        # sk_test_ (test keys) should not be sanitized
        assert "key_name" in result
        assert "test" in result


class TestSentryIntegrationEndToEnd:
    """End-to-end tests for Sentry integration."""

    def test_error_capture_flow(self):
        """Test complete error capture flow."""
        with patch("sentry_sdk.push_scope"):
            capture_cinema_error(
                error_type="test_error",
                details={"test": "data"},
            )
            # If this doesn't raise, the flow works

    def test_performance_tracking_flow(self):
        """Test complete performance tracking flow."""
        with SentryPerformanceTracker("test_op"):
            pass
        # If this doesn't raise, the flow works

    def test_transaction_filtering_preserves_important_transactions(self):
        """Test that important transactions are not filtered."""
        important_paths = [
            "/api/billing",
            "/api/activation",
            "/api/remediation",
        ]

        for path in important_paths:
            event = {"request": {"url": f"http://localhost:8000{path}"}}
            result = filter_transactions(event, {})
            assert result == event, f"Path {path} should not be filtered"

    def test_transaction_filtering_samples_verify_endpoints(self):
        """Test that verify endpoints are sampled (50% kept, 50% filtered)."""
        with patch("sentry_config.random.random") as mock_random:
            event = {"request": {"url": "http://localhost:8000/api/verify"}}

            # Test when random <= 0.5 (transaction kept, because condition is > 0.5)
            mock_random.return_value = 0.4
            result = filter_transactions(event, {})
            assert result == event

            # Test when random > 0.5 (transaction filtered)
            mock_random.return_value = 0.6
            result = filter_transactions(event, {})
            assert result is None
