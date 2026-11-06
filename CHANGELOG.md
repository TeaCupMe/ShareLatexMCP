# Changelog

## 0.1.0

First packaged preview release.

- Eleven MCP tools for projects, file trees, full and partial reads, sections,
  recursive outlines, search, document editing and compilation diagnostics.
- STDIO transport and environment-based session authentication.
- Versioned realtime edits with optional SHA-256 content guards; no automatic
  retry when an update outcome is uncertain.
- Secret redaction, bounded realtime waits and client-controlled write approvals.
- Installed command and Python module entry points, MIT license and client examples.
- Offline protocol tests, package checks and Windows/Linux/macOS CI.

Compatibility: HTTPS on port 443, without a URL path prefix; pyoverleaf 0.1.8's
legacy realtime protocol. Compatibility with other deployments is not guaranteed.
