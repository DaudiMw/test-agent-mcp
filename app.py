import os
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

# Require the API key to be set in the environment — no hardcoded fallback
API_KEY = os.getenv("MCP_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "MCP_API_KEY environment variable is not set. "
        "Set it before starting the server."
    )

mcp = FastMCP(
    name="learning-plan-server",
    auth=StaticTokenVerifier(tokens={API_KEY: {"client_id": "mcp-client"}})
)

# Import tools so their @mcp.tool() decorators register against the mcp instance
import tools.create_learning_plan  # noqa: E402, F401

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8000)