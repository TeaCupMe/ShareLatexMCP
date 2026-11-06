# ShareLaTeX MCP

A local MCP server for reading and editing self-hosted ShareLaTeX / Overleaf
projects from an MCP client. Python 3.11+, STDIO transport, MIT license.
**0.1.0 is a preview**: deployment compatibility depends on internal web and
realtime APIs. No Git integration or paid Overleaf account is required.

## Quick start

From a downloaded or cloned checkout, install [uv](https://docs.astral.sh/uv/)
and run:

```sh
uv sync --locked
uv run --locked sharelatex-mcp --help
```

Set two environment variables in the process that starts your MCP client:

- `OVERLEAF_URL`: an HTTPS origin, for example `https://latex.example.org`.
- `OVERLEAF_COOKIE`: one browser session cookie, as `name=value`.

Log into your instance, then open browser developer tools > Application (or
Storage) > Cookies and locate its session cookie. Common names are `overleaf.sid`
and `overleaf_session2`; use the actual name from your deployment.

PowerShell example (substitute values locally):

```powershell
$env:OVERLEAF_URL = 'https://latex.example.org'
$env:OVERLEAF_COOKIE = 'overleaf.sid=REPLACE_WITH_YOUR_SESSION'
uv run --locked sharelatex-mcp
```

Bash/zsh example:

```sh
export OVERLEAF_URL='https://latex.example.org'
export OVERLEAF_COOKIE='overleaf.sid=REPLACE_WITH_YOUR_SESSION'
uv run --locked sharelatex-mcp
```

The server waits for JSON-RPC on stdin. Normally the MCP client launches it for
you; an idle terminal is not a connection test. Environment variables set in a
terminal are inherited only by programs launched from that terminal. GUI clients
may instead need a private `env` section in their server configuration.
`.env.example` documents variable names; the server does not load .env files.

## Install without a checkout

A wheel works without uv at runtime:

```sh
python -m pip install /path/to/sharelatex_mcp-0.1.0-py3-none-any.whl
sharelatex-mcp --version
```

Or run the wheel in a uv-managed environment:

```sh
uvx --from /path/to/sharelatex_mcp-0.1.0-py3-none-any.whl sharelatex-mcp
```

Install the current main branch directly from GitHub:

```sh
uvx --from 'git+https://github.com/TeaCupMe/ShareLatexMCP.git@main' sharelatex-mcp
```

The distribution name is not yet assumed to be available on PyPI. Installation
by package name alone is documented only after a PyPI release exists.

## Connect a client

Any MCP client capable of launching a local STDIO process can use the installed
`sharelatex-mcp` command (or `python -m sharelatex_mcp`). Use an absolute executable
path if your client's PATH differs from the terminal's.

For a checkout, a Cursor-style configuration is:

```json
{
  "mcpServers": {
    "sharelatex": {
      "command": "uv",
      "args": ["run", "--locked", "--directory", "/absolute/path/SharelatexMCP", "sharelatex-mcp"]
    }
  }
}
```

For Windows, use a path such as `C:/projects/SharelatexMCP`. For installed wheels,
see [examples/cursor.mcp.json](examples/cursor.mcp.json) and
[examples/codex.config.toml](examples/codex.config.toml). They contain placeholders,
not working credentials. Copy the needed example into your client's private
configuration; never commit its real cookie. The current checkout's `.codex/`,
`.cursor/` and `.env` files are ignored and excluded from release archives.

Keep confirmation enabled for `write_file`, `append_to_file` and `replace_in_file`
in your MCP client. Tool annotations describe side effects; confirmation is
controlled by the host. Restart/reconnect the server after updating credentials
or installing a new version. The old `python server.py` launch remains supported
from a synced source checkout.

Cloud clients without local process execution cannot use this STDIO release.
An HTTP service and multi-user authentication are outside version 0.1.0.

## Tools

All `project` arguments accept a name or ID. Ambiguous names return matching IDs.

- `list_projects()`: names, IDs and last-update timestamps.
- `list_files(project)`: the complete file tree.
- `read_file(project, file_path, start_line=None, end_line=None)`: full UTF-8 text
  or inclusive line range starting at 1.
- `get_sections(project, file_path)`: heading titles, commands and line numbers.
- `read_section(project, file_path, title)`: one section and its deeper headings.
- `project_outline(project, root_file=None)`: tree and recursively included
  headings, with cycle detection and a limit of 30 included files.
- `search_project(project, query, file_pattern="*", max_results=30, context_lines=0)`:
  literal case-insensitive search in editable documents, with glob path filtering,
  up to 200 results and up to 10 context lines.
- `write_file(project, file_path, content, expected_sha256=None)`: create or replace
  text; existing documents are edited in place, other files use uploads.
- `append_to_file(project, file_path, content, expected_sha256=None)`: append text.
- `replace_in_file(project, file_path, old_text, new_text, expected_sha256=None)`:
  replace exactly one occurrence in an editable document.
- `compile_project(project, root_file=None)`: compile status and capped error /
  warning diagnostics. Does not return the PDF or change source content.

For editable documents, writes read the latest realtime snapshot and submit a
versioned operation. `expected_sha256` optionally checks the full UTF-8 content
against a SHA-256 hex digest before editing. It detects stale snapshots, while
concurrent changes remain subject to ShareLaTeX's operational transformation.
This guard is not supported for uploaded files. When a write outcome is unknown,
read the document before deciding to retry; the server never retries automatically.

## Compatibility and limits

The CI matrix targets Windows, Linux and macOS on Python 3.11, 3.12 and 3.13.
Passing local checks does not prove remote deployment compatibility on all hosts.
Dependencies use MCP SDK 2.3.0 and pyoverleaf 0.1.8. uv.lock pins the development
resolution; installed distributions constrain direct dependencies.

- Only HTTPS on standard port 443 is supported. HTTP, custom ports and path
  prefixes are rejected explicitly due to pyoverleaf transport limitations.
- Self-hosted deployments must support the legacy Socket.IO realtime protocol
  used by pyoverleaf. This is not a promise of current overleaf.com compatibility.
- Root selection prefers main.tex, then a .tex containing documentclass. Set
  root_file explicitly when that differs from your project's configured root.
- The LaTeX parser handles comments, nested heading braces and common literal
  blocks. It does not expand macros or execute TeX.
- Uploaded images and PDFs are not read as text. Rename/delete, project creation,
  sharing permissions, PDF download and automatic cookie renewal are not included.

## Troubleshooting

Authentication errors: sign into the browser again, replace the session cookie
in your client's private configuration and restart the MCP process. A renewed
browser session does not update an already-running process's environment.

Server not found: check executable PATH and absolute paths; try `--help` and
`--version` in a terminal. Protocol logs go to stderr, never stdout.

Windows import errors: browser_cookie3, pulled in by pyoverleaf, imports WMI even
when authentication comes from the environment. Some sandboxes block that import;
run in an environment with WMI access. No browser profile access is needed for
this server's login path.

Compilation reports busy, timeout and unavailable logs separately. Realtime
failures may indicate an incompatible deployment. Report sanitized errors without
cookies or private document text; see [SECURITY.md](SECURITY.md).

## Development and releases

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md) and
[release instructions](docs/releasing.md). The offline suite, archive checks and
installed-wheel smoke test require no ShareLaTeX credentials. The optional live
script modifies only the explicitly chosen disposable test project and attempts
to restore the source afterward.

This project is independent of Overleaf. See [LICENSE](LICENSE) for MIT terms.
