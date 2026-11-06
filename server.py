"""Compatibility shim for existing source-checkout MCP configurations."""
import sys
from sharelatex_mcp import main

if __name__ == "__main__":
    main()
else:
    from sharelatex_mcp import server as _implementation
    sys.modules[__name__] = _implementation
