"""Entry point: `python -m datadog_mcp` runs the MCP server over stdio."""
from datadog_mcp.server import mcp


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
