# Releasing

The first preview is 0.1.0. The GitHub repository is
https://github.com/TeaCupMe/ShareLatexMCP. PyPI publication is separate.

1. Update pyproject.toml and CHANGELOG.md for the release version. Update versioned
   wheel examples and run `uv lock`. Use a clean branch and review the diff.
2. Run `uv sync --locked`, the unittest suite, `uv build`, and
   `uv run --locked python scripts/check_release.py`. Inspect the resulting archives.
3. Install the wheel in a fresh environment and run its Python with
   `-I scripts/check_install.py`. CI runs these checks on Windows, Linux and macOS.
   Wait for the full matrix to pass; local Windows success alone is insufficient.
4. Review `git status --short` before the first commit. Private client config,
   cookies and environment files must stay ignored. The automated publication
   check is a heuristic, not a substitute for reviewing public files.
5. Push the repository to the chosen GitHub destination. Enable private vulnerability
   reporting in repository settings. No hosting or publication is performed by
   local verification commands.
6. Create and push a version tag (for example v0.1.0). The release workflow checks
   the tag against package metadata, builds and tests, then prepares a DRAFT
   GitHub release with a wheel and source archive. Review before publishing it.
7. PyPI publication is separate and manual: choose an available distribution name,
   configure the account, and use `uv publish` only when ready. No PyPI credentials
   or publishing permissions are stored in this repository.

To verify a wheel locally (PowerShell):

```powershell
uv venv .release-check --python 3.11
uv pip install --python .release-check/Scripts/python.exe dist/sharelatex_mcp-0.1.0-py3-none-any.whl
.release-check/Scripts/python.exe -I scripts/check_install.py
```

On POSIX systems use `.release-check/bin/python` instead.
The wheel can be attached to the release and installed without PyPI.
