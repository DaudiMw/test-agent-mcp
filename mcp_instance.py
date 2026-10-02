import os
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

API_KEY = os.getenv("MCP_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "MCP_API_KEY environment variable is not set. "
        "Set it before starting the server."
    )

S3_BUCKET = os.getenv("S3_BUCKET")
if not S3_BUCKET:
    raise RuntimeError(
        "S3_BUCKET environment variable is not set. "
        "Set it to the name of your S3 bucket before starting the server."
    )

mcp = FastMCP(
    name="learning-plan-server",
    auth=StaticTokenVerifier(tokens={API_KEY: {"client_id": "mcp-client"}})
)
