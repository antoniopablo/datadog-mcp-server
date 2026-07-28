"""Unit tests for the pure logic that doesn't need the Datadog API."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Credentials so importing the client module doesn't matter; we test server logic
# via the tool functions that don't hit the network.
os.environ.setdefault("DD_API_KEY", "test")
os.environ.setdefault("DD_APP_KEY", "test")
os.environ.setdefault("DD_SITE", "datadoghq.eu")

from datadog_mcp import server  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_savings_basic():
    r = _run(server.estimate_metric_savings(current_series=31000, projected_series=180, price_per_100_series=0.05))
    assert r["series_removed"] == 30820
    assert r["percent_reduction"] == 99.4
    assert r["estimated_monthly_saving"] == round(30820 / 100 * 0.05, 2)


def test_savings_clamps_projection_above_current():
    r = _run(server.estimate_metric_savings(current_series=100, projected_series=500))
    assert r["projected_series"] == 100
    assert r["series_removed"] == 0
    assert r["percent_reduction"] == 0.0


def test_savings_zero_current():
    r = _run(server.estimate_metric_savings(current_series=0, projected_series=0))
    assert r["percent_reduction"] == 0.0
    assert r["estimated_monthly_saving"] == 0.0


if __name__ == "__main__":
    test_savings_basic()
    test_savings_clamps_projection_above_current()
    test_savings_zero_current()
    print("all tests passed")
