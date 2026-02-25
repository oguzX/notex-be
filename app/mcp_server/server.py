from __future__ import annotations

from fastmcp import FastMCP

mcp = FastMCP("notex-mcp")

# Import tools to register them via decorators
from app.mcp_server.tools import weather  # noqa: F401
from app.mcp_server.tools import fx  # noqa: F401
from app.mcp_server.tools import pharmacy  # noqa: F401


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
