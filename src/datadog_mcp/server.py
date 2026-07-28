"""Datadog Cost MCP Server.

Exposes read-only Datadog usage/cost tools to any MCP client (e.g. Claude).
Each tool returns structured data plus an `advice` field encoding the
heuristics an ex-Datadog SRE would apply in a real cost audit.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from datadog_mcp.datadog_client import DatadogClient, DatadogConfigError

mcp = FastMCP("datadog-cost")

# Heuristics tuned from real audits.
CARDINALITY_REVIEW_THRESHOLD = 5_000  # series above this need a reason to exist
NOISY_TAG_KEYS = {"pod_name", "container_id", "request_id", "user_id", "trace_id", "path", "host"}
DEFAULT_PRICE_PER_100_SERIES = 0.05  # USD/month list-ish; override with DD_PRICE_PER_100_SERIES


def _client() -> DatadogClient:
    return DatadogClient()


def _price_per_100_series() -> float:
    raw = os.environ.get("DD_PRICE_PER_100_SERIES")
    try:
        return float(raw) if raw else DEFAULT_PRICE_PER_100_SERIES
    except ValueError:
        return DEFAULT_PRICE_PER_100_SERIES


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@mcp.tool()
async def get_usage_summary(months: int = 1) -> dict[str, Any]:
    """Billable Datadog usage for the last N months.

    Returns hosts, custom metrics, indexed/ingested logs and APM spans so the
    model can see where the bill concentrates. `months=1` is the current month.
    """
    now = datetime.now(timezone.utc)
    start_year = now.year
    start_month = now.month - (months - 1)
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start = f"{start_year:04d}-{start_month:02d}"

    data = await _client().usage_summary(start_month=start, end_month=_current_month())
    usage = data.get("usage", [])

    def _sum(key: str) -> int:
        return sum(int(m.get(key) or 0) for m in usage)

    summary = {
        "window": {"start_month": start, "end_month": _current_month(), "months": len(usage)},
        "billable": {
            "infra_hosts_top99p": _sum("agent_host_top99p") + _sum("infra_host_top99p"),
            "custom_metrics_avg": _sum("num_custom_timeseries") // max(len(usage), 1),
            "indexed_logs_events": _sum("indexed_events_count"),
            "ingested_logs_bytes": _sum("ingested_events_bytes"),
            "apm_indexed_spans": _sum("indexed_spans_count") + _sum("apm_host_top99p"),
        },
    }
    cm = summary["billable"]["custom_metrics_avg"]
    logs = summary["billable"]["indexed_logs_events"]
    hints = []
    if cm > 100_000:
        hints.append(f"{cm:,} custom metric series — check top_custom_metrics for cardinality offenders.")
    if logs > 0:
        hints.append("Run log_index_config: most orgs read <5% of what they index.")
    summary["advice"] = " ".join(hints) or "Usage looks modest; still worth a cardinality and log-index pass."
    return summary


@mcp.tool()
async def top_custom_metrics(limit: int = 20, lookback_hours: int = 24) -> dict[str, Any]:
    """Highest-cardinality custom metrics — usually the #1 cost driver.

    Lists active custom metrics and, for the busiest ones, the tag keys that
    inflate series count. Metrics above the review threshold are flagged.
    """
    client = _client()
    from_epoch = int(time.time()) - lookback_hours * 3600
    active = await client.list_active_metrics(from_epoch)
    names = active.get("metrics", [])

    # Custom metrics are the ones that aren't in Datadog's integration namespaces.
    integration_prefixes = ("system.", "datadog.", "aws.", "azure.", "gcp.", "kubernetes.", "docker.")
    custom = [m for m in names if not m.startswith(integration_prefixes)]

    offenders: list[dict[str, Any]] = []
    for name in custom[: max(limit, 1)]:
        try:
            tags = await client.metric_all_tags(name)
        except Exception:
            continue
        tag_keys = sorted({t.split(":", 1)[0] for t in tags.get("data", {}).get("attributes", {}).get("tags", [])})
        noisy = sorted(set(tag_keys) & NOISY_TAG_KEYS)
        offenders.append(
            {
                "metric": name,
                "tag_keys": tag_keys,
                "noisy_tag_keys": noisy,
                "flag": "REVIEW" if noisy else "ok",
            }
        )

    offenders.sort(key=lambda o: (o["flag"] != "REVIEW", -len(o["noisy_tag_keys"])))
    flagged = [o["metric"] for o in offenders if o["flag"] == "REVIEW"]
    advice = (
        f"{len(flagged)} metric(s) carry high-cardinality tags {sorted(NOISY_TAG_KEYS)}. "
        "Drop those tags via Metrics without Limits™ — you keep the metric, stop paying "
        "for a dimension nobody queries. Use estimate_metric_savings to quantify."
        if flagged
        else "No obvious high-cardinality offenders in the sampled metrics."
    )
    return {"count_custom_metrics": len(custom), "sampled": len(offenders), "metrics": offenders, "advice": advice}


@mcp.tool()
async def estimate_metric_savings(
    current_series: int,
    projected_series: int,
    price_per_100_series: float | None = None,
) -> dict[str, Any]:
    """Estimate €/month saved by shrinking a metric's series count.

    e.g. dropping `pod_name` takes checkout.request.duration from 31,406 -> 180 series.
    Pass your negotiated price_per_100_series for accuracy; list-ish default otherwise.
    """
    price = price_per_100_series if price_per_100_series is not None else _price_per_100_series()
    current_series = max(current_series, 0)
    projected_series = max(min(projected_series, current_series), 0)
    saved_series = current_series - projected_series
    monthly_saving = round(saved_series / 100.0 * price, 2)
    pct = round(100 * saved_series / current_series, 1) if current_series else 0.0
    return {
        "current_series": current_series,
        "projected_series": projected_series,
        "series_removed": saved_series,
        "percent_reduction": pct,
        "price_per_100_series": price,
        "estimated_monthly_saving": monthly_saving,
        "advice": (
            f"~{pct}% fewer series (~{monthly_saving} /month at {price}/100 series). "
            "Apply with a tag configuration (Metrics without Limits), version-controlled in your IaC."
        ),
    }


@mcp.tool()
async def log_index_config() -> dict[str, Any]:
    """List log indexes with retention and whether any exclusion filters exist.

    Flags the classic leak: one index, everything indexed, no exclusion filters.
    """
    data = await _client().log_indexes()
    indexes = []
    leaks = 0
    for idx in data.get("indexes", []):
        filters = idx.get("exclusion_filters", []) or []
        active_filters = [f for f in filters if (f.get("filter") or {}).get("query")]
        has_exclusion = len(active_filters) > 0
        if not has_exclusion:
            leaks += 1
        indexes.append(
            {
                "name": idx.get("name"),
                "retention_days": idx.get("num_retention_days"),
                "daily_limit": idx.get("daily_limit"),
                "exclusion_filters": len(active_filters),
                "flag": "NO_EXCLUSION_FILTERS" if not has_exclusion else "ok",
            }
        )
    advice = (
        f"{leaks} index(es) have no exclusion filters — you're indexing (and paying for) "
        "everything. Drop status:debug/info from high-volume services, sample 2xx access "
        "logs, route audit logs to an archive tier."
        if leaks
        else "Indexes have exclusion filters in place — good. Still verify retention tiers match value."
    )
    return {"indexes": indexes, "advice": advice}


@mcp.tool()
async def find_idle_hosts(live_hostnames: list[str] | None = None, filter_str: str | None = None) -> dict[str, Any]:
    """Find hosts billing to Datadog that may be zombies.

    Cross-references reporting hosts against a `live_hostnames` inventory you pass
    (e.g. from your ASG/Terraform state). Hosts reporting but not in the inventory,
    or already muted, are candidates to stop paying for.
    """
    data = await _client().hosts(filter_str=filter_str)
    live = set(live_hostnames or [])
    reporting = data.get("host_list", [])
    suspects = []
    for h in reporting:
        name = h.get("name")
        muted = h.get("is_muted", False)
        up = h.get("up", True)
        unknown = bool(live) and name not in live
        if muted or not up or unknown:
            suspects.append(
                {
                    "host": name,
                    "muted": muted,
                    "up": up,
                    "in_live_inventory": (name in live) if live else None,
                    "reason": "muted" if muted else ("not_up" if not up else "not_in_inventory"),
                }
            )
    advice = (
        f"{len(suspects)} suspect host(s). Common causes: agents baked into CI AMIs, "
        "autoscaling churn (each short-lived instance bills as a host-hour), forgotten dev "
        "boxes. Remove the agent from ephemeral images and alert on hosts outside IaC."
        if suspects
        else "No obvious zombie hosts among reporting hosts."
    )
    return {"reporting_hosts": len(reporting), "suspects": suspects, "advice": advice}


if __name__ == "__main__":
    try:
        mcp.run()
    except DatadogConfigError as e:  # surfaced clearly at startup
        raise SystemExit(f"[datadog-mcp] configuration error: {e}")
