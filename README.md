# Datadog Cost MCP Server

**An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP client) inspect a Datadog org's usage and answer cost questions in plain English — written by an ex-Datadog SRE.**

Instead of clicking through the Plan & Usage pages, you ask:

> *"Which custom metrics are costing me the most this month, and what would I save by dropping the noisy tags?"*

…and Claude calls this server, pulls the numbers from the Datadog API, and gives you a ranked answer with a concrete fix.

This is the AI-assistant companion to my [Datadog Cost Audit Playbook](https://github.com/antoniopablo/datadog-cost-audit-playbook): the playbook is the manual audit, this puts the same audit one question away inside Claude.

---

## What it does

The server exposes these tools to the model:

| Tool | What it answers |
|------|-----------------|
| `get_usage_summary` | Billable usage for the last N months: hosts, custom metrics, indexed/ingested logs, APM spans. |
| `top_custom_metrics` | The highest-cardinality custom metrics (the usual #1 cost driver) with their active tag configuration. |
| `estimate_metric_savings` | Rough €/month you'd save by dropping given tags from a metric (Metrics without Limits™). |
| `log_index_config` | Each log index, its retention, and whether it has any exclusion filters — flags "indexing everything". |
| `find_idle_hosts` | Hosts reporting to Datadog that look muted/zombie, cross-referenced against a live inventory you pass in. |

Every tool returns structured data **plus** a short `advice` string, so the model can explain the finding and the remediation in one step.

## Why an ex-Datadog SRE built this

Cost tooling that just dumps numbers isn't useful — you need to know *which* number is the anomaly and *what to do about it*. Each tool here encodes the heuristics I use in real audits (cardinality thresholds, "read <5% of indexed logs" rule of thumb, zombie-host detection), so the model gives an SRE's answer, not a spreadsheet.

## Quick start

```bash
pip install -r requirements.txt

# Datadog credentials (read-only keys are enough)
export DD_API_KEY=...          # API key
export DD_APP_KEY=...          # Application key
export DD_SITE=datadoghq.eu    # or datadoghq.com, etc.

# Run over stdio (how MCP clients launch it)
python -m datadog_mcp
```

### Use it with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "datadog-cost": {
      "command": "python",
      "args": ["-m", "datadog_mcp"],
      "env": {
        "DD_API_KEY": "your-api-key",
        "DD_APP_KEY": "your-app-key",
        "DD_SITE": "datadoghq.eu"
      }
    }
  }
}
```

Restart Claude Desktop and ask: *"Use datadog-cost to show my top custom metrics and estimate what I'd save."*

## Example session

```
You:    Which custom metrics are costing me the most, and what should I do?

Claude: [calls top_custom_metrics]
        Your two biggest cost drivers are:
          1. checkout.request.duration — 31,406 series
          2. checkout.request.count    — 14,882 series
        Both explode because they're tagged by `pod_name` and `request_id`.

        [calls estimate_metric_savings on checkout.request.duration, drop=["pod_name","request_id"]]
        Dropping those two tags via Metrics without Limits collapses it to
        ~180 series — roughly a 99% cut on that metric, ~€480/month at your
        current per-100-series rate. You keep the metric, you just stop paying
        to index a dimension nobody queries.
```

## Design notes / safety

- **Read-only by design.** The server only calls Datadog *read* endpoints. It never edits tag configs, indexes, or retention — it tells you what to change; you apply it in your IaC (that's the [playbook](https://github.com/antoniopablo/datadog-cost-audit-playbook)'s job).
- Credentials come from env vars only; nothing is logged.
- `estimate_metric_savings` is an estimate (per-100-series list price by default; pass your negotiated rate for accuracy).

## Author

Antonio García — ex-Datadog SRE, cloud/observability cost audits across Europe.
Contact: antoniopablo.garlopez@hotmail.com · [Malt](https://en.malt.es/profile/antoniogarcia1)

## License

[MIT](LICENSE)
