FROM python:3.12-slim

WORKDIR /app

# Install aegis-dq from PyPI
RUN pip install --no-cache-dir aegis-dq

# MCP stdio transport — Glama sends JSON-RPC over stdin/stdout
ENTRYPOINT ["aegis", "mcp"]
