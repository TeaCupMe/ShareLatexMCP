# Contributing

Use Python 3.11+ and uv. From a checkout:

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv build
uv run --locked python scripts/check_release.py
```

The offline suite requires no account and must not contact a ShareLaTeX server.
On Windows, pyoverleaf's browser_cookie3 dependency imports WMI; a restricted
sandbox may prevent import. Do not work around this by embedding real cookies.

Keep stdout exclusively for MCP JSON-RPC; use stderr for logs. Never log cookies,
request headers or document contents. Keep client configurations and credentials
untracked. Changes to dependencies must update uv.lock (`uv lock`).

Add regression coverage for changes to protocol handling, parsing, write behavior
and packaging. Test an installed wheel outside the source checkout before release.
Avoid claiming a new deployment version works without a live verification.

Live verification is opt-in on a disposable project without concurrent editors:

```sh
uv run --locked python scripts/check_live.py --project Testing --allow-write
```

The script changes a source file and attempts to restore its contents. If a
connection fails, inspect that project before retrying. Never run on user projects
as part of automated CI.

See docs/releasing.md for the release process. This project uses the MIT license;
contributions are submitted under the same license.
