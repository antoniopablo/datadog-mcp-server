# Example session

A real conversation looks like this once the server is wired into Claude Desktop.

---

**You:** Use datadog-cost to tell me where my Datadog bill is concentrated this month.

**Claude:** *(calls `get_usage_summary`)*
This month so far:
- Custom metric series (avg): **47,812**
- Indexed log events: **9,443,207**
- APM indexed spans: **1,204,338**
- Infra hosts (top99p): 3

The custom-metric count is the thing to look at first — 47k series on 3 hosts is very high.

---

**You:** Which metrics are driving that?

**Claude:** *(calls `top_custom_metrics`)*
Two metrics carry high-cardinality tags:
1. `checkout.request.duration` — tagged by `pod_name`, `request_id` → **REVIEW**
2. `checkout.request.count` — tagged by `pod_name` → **REVIEW**

Those tags multiply series count without adding queryable value.

---

**You:** What would I save if I drop pod_name and request_id from the duration metric? It's about 31,000 series now and would collapse to ~180.

**Claude:** *(calls `estimate_metric_savings`, current_series=31000, projected_series=180)*
- Series removed: **30,820** (**99.4%** reduction)
- Estimated saving: **~€15.41/month** at list price for that one metric — and it scales:
  the same fix across your top offenders is where the 30–60% total reduction comes from.

Apply it as a tag configuration (Metrics without Limits) committed to your Terraform,
so it doesn't regress.

---

**You:** And my logs?

**Claude:** *(calls `log_index_config`)*
Your `main` index has **0 exclusion filters** and 30-day retention on everything —
you're indexing (and paying for) debug and health-check logs nobody reads. Drop
`status:debug`/`status:info` from high-volume services and route audit logs to an
archive tier.
