# Security policy

## Supported versions

Security fixes target the latest 0.1.x release. This is a preview that relies on
internal ShareLaTeX APIs. Review client write permissions before connecting.

## Credentials

A session cookie grants the permissions of the logged-in account. Store it in a
private client environment or private configuration, never in source code, issue
reports or commits. .codex/, .cursor/ and .env files are ignored by this repository.
If exposed, invalidate the browser session, obtain a new cookie and remove the
secret from published artifacts and repository history as applicable.

MCP annotations do not enforce confirmation. Configure your host to prompt for
write_file, append_to_file and replace_in_file. The server is a local STDIO
process, with no HTTP listener or multi-user authentication layer.

## Reporting

Once the repository is hosted on GitHub, use its private vulnerability reporting
feature if enabled. Otherwise contact the maintainer at alesha@gilenko.net.
Do not open a public issue containing credentials, private documents or a working
exploit against a third-party service. Include the package version, OS, deployment
version when known, and sanitized reproduction steps.
