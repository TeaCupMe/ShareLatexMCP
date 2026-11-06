"""ShareLaTeX MCP package and command-line entry point."""

from importlib.metadata import version


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="sharelatex-mcp",
        description="Read and edit self-hosted ShareLaTeX projects over MCP STDIO.",
        epilog="Set OVERLEAF_URL and OVERLEAF_COOKIE=name=value in the environment."
    )
    parser.add_argument("--version", action="version", version=version("sharelatex-mcp"))
    parser.parse_args()
    from .server import main as run
    run()
