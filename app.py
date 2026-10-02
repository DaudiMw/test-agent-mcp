from mcp_instance import mcp
import tools.create_learning_plan   # noqa: E402, F401 — registers @mcp.tool() decorators
import tools.estimate_course_length  # noqa: E402, F401 — registers @mcp.tool() decorators

if __name__ == "__main__":
    # Bind to localhost only; use a reverse proxy (ALB / nginx) to expose publicly on AWS
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
