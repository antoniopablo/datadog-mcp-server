"""Thin async wrapper over the Datadog REST API.

Only read endpoints are used. Credentials are read from the environment:
    DD_API_KEY, DD_APP_KEY, DD_SITE (default datadoghq.com)
"""
from __future__ import annotations

import os
from typing import Any

import httpx

_VALID_SITES = {
    "datadoghq.com",
    "us3.datadoghq.com",
    "us5.datadoghq.com",
    "datadoghq.eu",
    "ap1.datadoghq.com",
    "ddog-gov.com",
}


class DatadogConfigError(RuntimeError):
    """Raised when required credentials are missing or invalid."""


class DatadogClient:
    def __init__(
        self,
        api_key: str | None = None,
        app_key: str | None = None,
        site: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("DD_API_KEY", "")
        self.app_key = app_key or os.environ.get("DD_APP_KEY", "")
        self.site = (site or os.environ.get("DD_SITE") or "datadoghq.com").strip()

        if not self.api_key or not self.app_key:
            raise DatadogConfigError(
                "DD_API_KEY and DD_APP_KEY must be set (read-only keys are fine)."
            )
        if self.site not in _VALID_SITES:
            raise DatadogConfigError(
                f"DD_SITE '{self.site}' is not a known Datadog site. "
                f"Expected one of: {', '.join(sorted(_VALID_SITES))}"
            )
        self._base = f"https://api.{self.site}"
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key,
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, headers=self._headers, params=params or {})
        if resp.status_code == 403:
            raise DatadogConfigError(
                "Datadog returned 403 — the application key likely lacks the "
                "usage_read / metrics_read scope, or the site is wrong."
            )
        resp.raise_for_status()
        return resp.json()

    # ---- Usage -------------------------------------------------------------
    async def usage_summary(self, start_month: str, end_month: str | None = None) -> dict[str, Any]:
        """GET /api/v1/usage/summary  (months as YYYY-MM)."""
        params: dict[str, Any] = {"start_month": start_month}
        if end_month:
            params["end_month"] = end_month
        return await self._get("/api/v1/usage/summary", params)

    # ---- Metrics -----------------------------------------------------------
    async def list_active_metrics(self, from_epoch: int) -> dict[str, Any]:
        """GET /api/v1/metrics — metrics that have reported since `from_epoch`."""
        return await self._get("/api/v1/metrics", {"from": from_epoch})

    async def metric_all_tags(self, metric: str) -> dict[str, Any]:
        """GET /api/v2/metrics/{metric}/all-tags — indexed tag keys/values."""
        return await self._get(f"/api/v2/metrics/{metric}/all-tags")

    async def metric_tag_config(self, metric: str) -> dict[str, Any]:
        """GET /api/v2/metrics/{metric}/tags — active tag configuration (MwL)."""
        return await self._get(f"/api/v2/metrics/{metric}/tags")

    # ---- Logs --------------------------------------------------------------
    async def log_indexes(self) -> dict[str, Any]:
        """GET /api/v1/logs/config/indexes — indexes, retention, exclusion filters."""
        return await self._get("/api/v1/logs/config/indexes")

    # ---- Infrastructure ----------------------------------------------------
    async def hosts(self, filter_str: str | None = None, count: int = 1000) -> dict[str, Any]:
        """GET /api/v1/hosts — reporting hosts."""
        params: dict[str, Any] = {"count": count}
        if filter_str:
            params["filter"] = filter_str
        return await self._get("/api/v1/hosts", params)
