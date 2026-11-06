"""ShareLaTeX MCP server.

Talks to a self-hosted ShareLaTeX / Overleaf instance through pyoverleaf.
The session cookie and instance URL come from the environment. Nothing in
this process may write to stdout except the MCP stdio transport.
"""

from __future__ import annotations

import fnmatch
import hashlib
import time
import json
import logging
import os
import posixpath
import re
import sys
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Callable
from urllib.parse import urlparse, quote, unquote

import requests
from mcp.server import MCPServer
from mcp_types import ToolAnnotations
from pyoverleaf import Api, Project, ProjectFile, ProjectFolder, ProjectIO

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("sharelatex")

mcp = MCPServer("sharelatex")

_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    open_world_hint=True,
)
_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)

_SECTION = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)"
    r"\*?(?:\[[^\]]*\])?\{([^{}]*)\}"
)
_INPUT = re.compile(r"\\(input|include)\{([^{}]+)\}")
_LEVELS = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
    "subparagraph": 6,
}
_SEARCH_LIMIT = 30
_INCLUDE_LIMIT = 30
_LOG_LIMIT = 40


def _redact(message: str) -> str:
    raw = os.environ.get("OVERLEAF_COOKIE", "")
    secret = raw.split("=", 1)[1] if "=" in raw else ""
    if secret:
        for variant in {secret, quote(secret, safe=""), unquote(secret)}:
            if variant:
                message = message.replace(variant, "[redacted]")
    return message


def _host() -> str:
    raw = os.environ.get("OVERLEAF_URL", "").strip()
    if not raw:
        raise RuntimeError("Set OVERLEAF_URL to the ShareLaTeX instance URL.")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise RuntimeError("OVERLEAF_URL must be an HTTPS origin without credentials or a path prefix.")
    try:
        if parsed.port not in (None, 443):
            raise RuntimeError("Custom ports are unsupported by pyoverleaf realtime authentication.")
    except ValueError:
        raise RuntimeError("OVERLEAF_URL has an invalid port.") from None
    return parsed.hostname



def _cookie() -> tuple[str, str]:
    raw = os.environ.get("OVERLEAF_COOKIE", "").strip()
    if "=" not in raw:
        raise RuntimeError(
            "Set OVERLEAF_COOKIE to name=value, for example overleaf.sid=<session>."
        )
    name, value = raw.split("=", 1)
    if not name or not value:
        raise RuntimeError("OVERLEAF_COOKIE must be a non-empty name=value pair.")
    return name, value


def _api() -> Api:
    host = _host()
    name, value = _cookie()
    api = Api(host=host, timeout=60)
    jar = CookieJar()
    # pyoverleaf attaches websocket cookies only when the domain ends with
    # ".{host}". A leading dot satisfies that filter and still matches HTTP.
    jar.set_cookie(requests.cookies.create_cookie(name, value, domain=f".{urlparse('https://' + host).hostname}"))
    api.login_from_cookies(jar)
    return api


def _call(action):
    try:
        return action()
    except Exception as exc:
        message = _redact(str(exc))
        log.error("ShareLaTeX request failed (%s): %s", type(exc).__name__, message)
        raise RuntimeError(message) from None


def _cell(value: object) -> str:
    return str(value).replace("\t", " ").replace("\n", " ").strip()


def _project_line(project: Project) -> str:
    return f"{_cell(project.name)}\t{_cell(project.id)}\t{_cell(project.last_updated)}"


def resolve_project(projects: list[Project], label: str) -> Project:
    """Pick a project by exact id, then exact name, then case-insensitive name."""
    by_id = [project for project in projects if project.id == label]
    if len(by_id) == 1:
        return by_id[0]
    exact = [project for project in projects if project.name == label]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        rows = "\n".join(_project_line(project) for project in exact)
        raise RuntimeError(f"Several projects match {label!r}:\n{rows}")
    folded = [project for project in projects if project.name.casefold() == label.casefold()]
    if len(folded) == 1:
        return folded[0]
    if len(folded) > 1:
        rows = "\n".join(_project_line(project) for project in folded)
        raise RuntimeError(f"Several projects match {label!r}:\n{rows}")
    raise RuntimeError(f"No project matches {label!r}.")


def _resolve(api: Api, label: str) -> Project:
    return resolve_project(api.get_projects(), label)


def _norm_path(path: str) -> str:
    path = posixpath.normpath(path.replace("\\", "/").strip())
    if path == ".." or path.startswith("../"):
        raise RuntimeError("Path escapes the project root.")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _walk(folder: ProjectFolder, prefix: str = "") -> list[str]:
    lines: list[str] = []
    for child in folder.children:
        path = f"{prefix}{child.name}"
        if isinstance(child, ProjectFolder):
            lines.append(f"{path}/ [folder]")
            lines.extend(_walk(child, path + "/"))
        elif isinstance(child, ProjectFile):
            lines.append(f"{path} [{child.type}]")
    return lines


def _index(folder: ProjectFolder, prefix: str = "") -> dict[str, ProjectFile | ProjectFolder]:
    found: dict[str, ProjectFile | ProjectFolder] = {}
    for child in folder.children:
        path = f"{prefix}{child.name}"
        found[path] = child
        if isinstance(child, ProjectFolder):
            found.update(_index(child, path + "/"))
    return found


def _lookup(indexed: dict[str, ProjectFile | ProjectFolder], file_path: str):
    path = _norm_path(file_path)
    if path not in indexed:
        raise RuntimeError(f"No such file or directory: {file_path}")
    entity = indexed[path]
    if isinstance(entity, ProjectFolder):
        raise RuntimeError(f"{file_path} is a folder.")
    return path, entity


@dataclass(frozen=True)
class Heading:
    line: int
    command: str
    title: str
    start: int
    level: int


def _latex_visible(text: str) -> str:
    # Keep offsets and line numbers stable while hiding comments and literal blocks.
    result = re.sub(r"\\begin\{(verbatim\*?|lstlisting|minted)\}.*?\\end\{\1\}",
                    lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)
    chars = list(result)
    for match in re.finditer("%", result):
        pos = match.start()
        backslashes = 0
        cursor = pos - 1
        while cursor >= 0 and result[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            continue
        end = result.find("\n", pos)
        end = len(result) if end < 0 else end
        chars[pos:end] = " " * (end - pos)
    return "".join(chars)


def headings_in(text: str) -> list[Heading]:
    visible = _latex_visible(text)
    pattern = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*(?:\[[^\]]*\]\s*)?\{")
    found = []
    for match in pattern.finditer(visible):
        if match.start() and visible[match.start() - 1] == "\\":
            continue
        depth = 1
        cursor = match.end()
        while cursor < len(visible) and depth:
            ch = visible[cursor]
            if ch == "\\":
                cursor += 2
                continue
            depth += (ch == "{") - (ch == "}")
            cursor += 1
        if depth:
            continue
        command = match.group(1)
        found.append(Heading(text.count("\n", 0, match.start()) + 1, command,
                             text[match.end():cursor - 1].strip(), match.start(), _LEVELS[command]))
    return found


def heading_lines(text: str) -> list[str]:
    return [f"{item.line}\t{item.command}\t{item.title}" for item in headings_in(text)]


def section_text(text: str, title: str) -> str:
    found = headings_in(text)
    chosen = [item for item in found if item.title == title]
    if not chosen:
        chosen = [item for item in found if item.title.casefold() == title.casefold()]
    if not chosen:
        raise RuntimeError(f"No heading titled {title!r}.")
    if len(chosen) > 1:
        lines = ", ".join(str(item.line) for item in chosen)
        raise RuntimeError(f"Heading {title!r} appears on lines {lines}.")
    current = chosen[0]
    end = len(text)
    for item in found:
        if item.start > current.start and item.level <= current.level:
            end = item.start
            break
    return text[current.start:end].rstrip()


def slice_lines(text: str, start_line: int | None, end_line: int | None) -> str:
    if start_line is None and end_line is None:
        return text
    lines = text.splitlines()
    start = 1 if start_line is None else start_line
    end = len(lines) if end_line is None else end_line
    if not lines:
        if start == 1 and end <= 1:
            return ""
        raise RuntimeError("The file is empty.")
    if start < 1 or start > len(lines) or end < start:
        raise RuntimeError(f"Line range {start}-{end} is outside the file (1-{len(lines)}).")
    end = min(end, len(lines))
    return "\n".join(lines[start - 1 : end])


def _commented(text: str, start: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start].replace("\\%", "")
    return "%" in prefix


def included_files(
    text: str,
    source_path: str,
    indexed: dict[str, ProjectFile | ProjectFolder],
) -> list[tuple[str, str, str | None]]:
    """Return (command, requested path, resolved project path or None)."""
    found: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for match in _INPUT.finditer(_latex_visible(text)):
        if _commented(text, match.start()):
            continue
        kind, raw = match.group(1), match.group(2).strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        found.append((kind, raw, resolve_include(source_path, raw, indexed)))
    return found


def resolve_include(
    source_path: str,
    raw: str,
    indexed: dict[str, ProjectFile | ProjectFolder],
) -> str | None:
    raw = raw.replace("\\", "/").strip().lstrip("/")
    while raw.startswith("./"):
        raw = raw[2:]
    names = [raw] if raw.endswith(".tex") else [raw, f"{raw}.tex"]
    parent = posixpath.dirname(_norm_path(source_path))
    candidates: list[str] = []
    for name in names:
        candidates.append(name)
        if parent:
            candidates.append(f"{parent}/{name}")
    for candidate in candidates:
        candidate = posixpath.normpath(candidate)
        entity = indexed.get(candidate)
        if isinstance(entity, ProjectFile):
            return candidate
    return None


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def replacement_ops(text: str, old_text: str, new_text: str) -> list[dict[str, object]]:
    """Build a ShareJS text op. old_text must occur once. Positions are UTF-16."""
    if old_text == "":
        raise RuntimeError("old_text must not be empty.")
    count = text.count(old_text)
    if count == 0:
        raise RuntimeError("old_text was not found.")
    if count > 1:
        raise RuntimeError(f"old_text appears {count} times. Refusing to edit.")
    if old_text == new_text:
        return []
    pos = _utf16_len(text[: text.find(old_text)])
    ops: list[dict[str, object]] = []
    if old_text:
        ops.append({"p": pos, "d": old_text})
    if new_text:
        ops.append({"p": pos, "i": new_text})
    return ops


def full_replace_ops(text: str, new_text: str) -> list[dict[str, object]]:
    if text == new_text:
        return []
    ops: list[dict[str, object]] = []
    if text:
        ops.append({"p": 0, "d": text})
    if new_text:
        ops.append({"p": 0, "i": new_text})
    return ops


def append_ops(text: str, content: str) -> list[dict[str, object]]:
    if content == "":
        return []
    return [{"p": _utf16_len(text), "i": content}]


def search_hits(path: str, text: str, query: str, limit: int) -> list[str]:
    needle = query.casefold()
    hits: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if needle not in line.casefold():
            continue
        hits.append(f"{path}:{number}: {_snippet(line, query)}")
        if len(hits) >= limit:
            break
    return hits


def _snippet(line: str, query: str, width: int = 160) -> str:
    stripped = line.strip()
    if len(stripped) <= width:
        return stripped
    idx = stripped.casefold().find(query.casefold())
    if idx < 0:
        return stripped[:width]
    start = max(0, idx - 40)
    end = min(len(stripped), start + width)
    prefix = "..." if start else ""
    suffix = "..." if end < len(stripped) else ""
    return prefix + stripped[start:end] + suffix


def compile_log_lines(log_text: str, limit: int = _LOG_LIMIT) -> list[str]:
    raw = log_text.splitlines()
    hits: list[str] = []
    for index, line in enumerate(raw):
        interesting = (
            line.startswith("!")
            or "Warning" in line
            or "Error" in line
            or "Emergency stop" in line
            or re.search(r"^.+\.(?:tex|sty|cls):\d+:", line) is not None
        )
        if not interesting:
            continue
        hits.append(line)
        if line.startswith("!") and index + 1 < len(raw) and raw[index + 1].startswith("l."):
            hits.append(raw[index + 1])
    if len(hits) > limit:
        return hits[:limit] + ["... log output truncated."]
    return hits


def _parse_join(ack: object) -> tuple[str, int]:
    if not isinstance(ack, list) or len(ack) < 3 or ack[0] is not None:
        raise RuntimeError("Unexpected joinDoc response from ShareLaTeX.")
    lines, version = ack[1], ack[2]
    if not isinstance(lines, list) or not isinstance(version, int):
        raise RuntimeError("Unexpected joinDoc response from ShareLaTeX.")
    if not all(isinstance(line, str) for line in lines):
        raise RuntimeError("Unexpected joinDoc response from ShareLaTeX.")
    return "\n".join(lines), version


def _parse_ack(line: str, msg_id: int) -> object:
    """Parse a socket.io ack. An empty ack is `6:::ID` and a payload ack is `6:::ID+JSON`."""
    rest = line[len(f"6:::{msg_id}") :]
    if rest in ("", "+"):
        return None
    return json.loads(rest[1:])


def _check_update_ack(ack: object) -> None:
    if ack is None or isinstance(ack, int):
        return
    if isinstance(ack, list) and (not ack or ack[0] is None):
        return
    if isinstance(ack, dict) and not ack.get("error"):
        return
    message = ack if isinstance(ack, str) else json.dumps(ack)[:300]
    raise RuntimeError(f"Document update was rejected: {message}")


class _ProjectSocket:
    """One realtime connection. Message ids follow pyoverleaf's socket.io framing."""

    def __init__(self, api: Api, project_id: str):
        self._api = api
        self._project_id = project_id
        self._socket = None
        self._next_id = 1

    def __enter__(self) -> _ProjectSocket:
        self._deadline = time.monotonic() + 60
        self._socket = self._api._open_socket(self._project_id)
        try:
            self._recv_until("5:")
        except Exception:
            self._socket.close()
            self._socket = None
            raise
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        socket = self._socket
        self._socket = None
        if socket is not None:
            socket.close()

    def join_doc(self, doc_id: str) -> object:
        self._socket.send(b'5:1+::{"name":"clientTracking.getConnectedUsers"}')
        self._next_id = 2
        return self.call("joinDoc", [doc_id, {"encodeRanges": True}])

    def call(self, name: str, args: list) -> object:
        msg_id = self._next_id
        self._next_id += 1
        payload = json.dumps({"name": name, "args": args})
        self._socket.send(f"5:{msg_id}+::{payload}".encode())
        line = self._recv_until_ack(msg_id)
        return _parse_ack(line, msg_id)

    def _recv_until_ack(self, msg_id: int) -> str:
        prefix = f"6:::{msg_id}"
        for _ in range(50):
            line = self._recv()
            if not line.startswith(prefix):
                continue
            rest = line[len(prefix) :]
            if rest == "" or rest.startswith("+"):
                return line
        raise RuntimeError("ShareLaTeX realtime session did not answer.")

    def _recv(self) -> str:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Realtime operation exceeded 60 seconds.")
        self._socket.settimeout(min(remaining, 15))
        line = self._socket.recv()
        if not line:
            raise ConnectionError("Realtime connection closed.")
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        if line.startswith("7:"):
            raise RuntimeError("ShareLaTeX rejected the realtime session.")
        return line

    def _recv_until(self, prefix: str) -> str:
        for _ in range(50):
            line = self._recv()
            if line.startswith(prefix):
                return line
        raise RuntimeError("ShareLaTeX realtime session did not answer.")


def _read_doc(api: Api, project_id: str, doc_id: str) -> str:
    with _ProjectSocket(api, project_id) as sock:
        text, _version = _parse_join(sock.join_doc(doc_id))
        return text


def _read_entity(api: Api, project_id: str, entity: ProjectFile) -> str:
    if entity.type == "doc":
        return _read_doc(api, project_id, entity.id)
    data = api.project_download_file(project_id, entity)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("The file is not UTF-8 text.") from exc


def _check_hash(text: str, expected_sha256: str | None) -> None:
    if expected_sha256 is not None and hashlib.sha256(text.encode("utf-8")).hexdigest() != expected_sha256.lower():
        raise RuntimeError("Content changed: expected_sha256 does not match. Read the file again.")


def _apply_doc_ops(
    api: Api,
    project_id: str,
    doc_id: str,
    build_ops: Callable[[str], list[dict[str, object]]],
    expected_sha256: str | None = None,
) -> None:
    with _ProjectSocket(api, project_id) as sock:
        text, version = _parse_join(sock.join_doc(doc_id))
        _check_hash(text, expected_sha256)
        ops = build_ops(text)
        if not ops:
            return
        try:
            ack = sock.call("applyOtUpdate", [doc_id, {"doc": doc_id, "op": ops, "v": version}])
        except Exception as exc:
            raise RuntimeError("Update outcome is unknown; read the document before retrying. " + _redact(str(exc))) from None
        _check_update_ack(ack)
        try:
            sock.call("leaveDoc", [doc_id])
        except Exception:
            log.info("leaveDoc failed after the document update")


def _choose_root(
    api: Api,
    project_id: str,
    indexed: dict[str, ProjectFile | ProjectFolder],
) -> str | None:
    files = [path for path, entity in indexed.items() if isinstance(entity, ProjectFile)]
    mains = [path for path in files if posixpath.basename(path) == "main.tex"]
    if mains:
        return sorted(mains, key=lambda path: (path.count("/"), path))[0]
    docs = [
        path
        for path, entity in indexed.items()
        if isinstance(entity, ProjectFile) and entity.type == "doc" and path.endswith(".tex")
    ]
    docs.sort(key=lambda path: (path.count("/"), path))
    for path in docs:
        if "\\documentclass" in _read_entity(api, project_id, indexed[path]):
            return path
    return docs[0] if docs else None


def _compile_log(api: Api, project_id: str, root_doc_id: str | None) -> str:
    token = api._get_csrf_token(project_id)
    session = api._get_session()
    host = api._host
    body: dict[str, object] = {
        "draft": False,
        "check": "silent",
        "incrementalCompilesEnabled": True,
        "stopOnFirstError": False,
    }
    if root_doc_id:
        body["rootDoc_id"] = root_doc_id
    try:
        response = session.post(
            f"https://{host}/project/{project_id}/compile",
            json=body,
            headers={
                "x-csrf-token": token,
                "Accept": "application/json",
                "Referer": f"https://{host}/project/{project_id}",
            },
            timeout=120,
        )
    except requests.Timeout:
        return "status: timeout\nCompile request timed out; check the project before retrying."
    if response.status_code in (409, 423, 429):
        return "status: busy\nCompilation is already running or the queue is busy."
    response.raise_for_status()
    payload = response.json()
    status = str(payload.get("status", "unknown"))
    lines = [f"status: {status}"]
    log_file = next(
        (
            item
            for item in payload.get("outputFiles") or []
            if isinstance(item, dict) and item.get("path") == "output.log"
        ),
        None,
    )
    if log_file is None:
        lines.append("Compile log unavailable; diagnostics could not be checked.")
        return "\n".join(lines)
    url = str(log_file.get("url") or "")
    if url and "://" not in url:
        url = f"https://{host}{url if url.startswith('/') else '/' + url}"
    if not url:
        return "\n".join(lines + ["Compile log unavailable: no URL returned."])
    parsed_log = urlparse(url)
    if parsed_log.scheme != "https" or parsed_log.netloc != host:
        raise RuntimeError("Compile log URL must use the configured HTTPS origin.")
    try:
        log_response = session.get(
            url,
            headers={"Referer": f"https://{host}/project/{project_id}"},
            timeout=60,
            allow_redirects=False,
        )
    except requests.Timeout:
        return "\n".join(lines + ["Compile log retrieval timed out."])
    if log_response.status_code != 200:
        return "\n".join(lines + [f"Compile log unavailable (HTTP {log_response.status_code})."])
    log_response.raise_for_status()
    messages = compile_log_lines(log_response.text)
    if messages:
        lines.extend(messages)
    else:
        lines.append("No errors or warnings.")
    return "\n".join(lines)


@mcp.tool(annotations=_READ_ONLY)
def list_projects() -> str:
    """List every ShareLaTeX project the logged-in user can see.

    Read-only. Returns one line per project: name, id, then last_updated,
    separated by tabs. Archived and trashed projects are omitted. Other
    tools accept either the name or the id.
    """

    def action() -> str:
        projects = _api().get_projects()
        if not projects:
            return "No projects."
        return "\n".join(_project_line(project) for project in projects)

    return _call(action)


@mcp.tool(annotations=_READ_ONLY)
def list_files(project: str) -> str:
    """List the full file tree of one ShareLaTeX project.

    Read-only. project is a project name or id. Each line is a path inside
    the project. Folders end with a slash. The bracketed type is folder,
    doc (an editable text document), or file (an uploaded binary).
    """

    def action() -> str:
        api = _api()
        project_id = _resolve(api, project).id
        lines = _walk(api.project_get_files(project_id))
        return "\n".join(lines) if lines else "(empty project)"

    return _call(action)


@mcp.tool(annotations=_READ_ONLY)
def read_file(
    project: str,
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read text from one file in a ShareLaTeX project.

    Read-only. project is a project name or id. file_path is the path
    inside the project, such as main.tex or chapters/intro.tex. Omit
    start_line and end_line to read the whole file. Line numbers are
    1-based and inclusive. end_line past the end of the file is clamped.
    """

    def action() -> str:
        api = _api()
        project_id = _resolve(api, project).id
        _path, entity = _lookup(_index(api.project_get_files(project_id)), file_path)
        return slice_lines(_read_entity(api, project_id, entity), start_line, end_line)

    return _call(action)


@mcp.tool(annotations=_READ_ONLY)
def get_sections(project: str, file_path: str) -> str:
    """Extract LaTeX section headings from a .tex file.

    Read-only. project is a project name or id. Returns one heading per
    line: line number, heading command (chapter, section, subsection, and
    so on), then the heading title. Starred commands such as \\section*
    are included.
    """

    def action() -> str:
        api = _api()
        project_id = _resolve(api, project).id
        _path, entity = _lookup(_index(api.project_get_files(project_id)), file_path)
        found = heading_lines(_read_entity(api, project_id, entity))
        return "\n".join(found) if found else "No section headings found."

    return _call(action)


@mcp.tool(annotations=_READ_ONLY)
def project_outline(project: str, root_file: str | None = None) -> str:
    """Summarize a ShareLaTeX project without reading every file.

    Read-only. project is a project name or id. Returns the file tree,
    the headings of the root .tex file, and the headings of files pulled
    in by \\input or \\include. The root file is main.tex when it exists,
    otherwise the first .tex document that contains \\documentclass.
    Includes are followed recursively with cycle detection. At most 30 files
    are opened. root_file overrides automatic root selection.
    """

    def action() -> str:
        api = _api()
        project_id = _resolve(api, project).id
        indexed = _index(api.project_get_files(project_id))
        tree = _walk_indexed(indexed)
        lines = ["FILES", *(tree or ["(empty project)"])]
        root_path = _lookup(indexed, root_file)[0] if root_file else _choose_root(api, project_id, indexed)
        lines.append("")
        if root_path is None:
            lines.append("ROOT none")
            return "\n".join(lines)
        root_entity = indexed[root_path]
        assert isinstance(root_entity, ProjectFile)
        root_text = _read_entity(api, project_id, root_entity)
        lines.append(f"ROOT {root_path}")
        lines.extend(heading_lines(root_text) or ["No section headings found."])
        queue = [(root_path, item) for item in included_files(root_text, root_path, indexed)]
        seen = {root_path}
        opened = 0
        while queue and opened < _INCLUDE_LIMIT:
            source, (kind, raw, resolved) = queue.pop(0)
            lines.append("")
            if resolved is None:
                lines.append(f"{kind.upper()} {raw} missing (from {source})")
                continue
            if resolved in seen:
                lines.append(f"{kind.upper()} {resolved} already visited (cycle or shared include)")
                continue
            seen.add(resolved)
            opened += 1
            lines.append(f"{kind.upper()} {resolved}")
            entity = indexed[resolved]
            assert isinstance(entity, ProjectFile)
            body = _read_entity(api, project_id, entity)
            lines.extend(heading_lines(body) or ["No section headings found."])
            queue.extend((resolved, item) for item in included_files(body, resolved, indexed))
        if queue:
            lines.append(f"Further includes omitted: file limit {_INCLUDE_LIMIT} reached.")
        return "\n".join(lines)

    return _call(action)


def _walk_indexed(indexed: dict[str, ProjectFile | ProjectFolder]) -> list[str]:
    lines: list[str] = []
    for path in sorted(indexed, key=lambda item: item.count("/")):
        entity = indexed[path]
        if isinstance(entity, ProjectFolder):
            lines.append(f"{path}/ [folder]")
        elif isinstance(entity, ProjectFile):
            lines.append(f"{path} [{entity.type}]")
    return lines


@mcp.tool(annotations=_READ_ONLY)
def read_section(project: str, file_path: str, title: str) -> str:
    """Read one LaTeX section, including its heading.

    Read-only. project is a project name or id. title is the heading text
    inside the braces, such as Introduction. The result runs from that
    heading through the line before the next heading of the same or higher
    level. Deeper headings are included. If the title appears more than
    once, the tool reports the line numbers and does not guess.
    """

    def action() -> str:
        api = _api()
        project_id = _resolve(api, project).id
        _path, entity = _lookup(_index(api.project_get_files(project_id)), file_path)
        return section_text(_read_entity(api, project_id, entity), title)

    return _call(action)


@mcp.tool(annotations=_READ_ONLY)
def search_project(project: str, query: str, file_pattern: str = "*", max_results: int = 30, context_lines: int = 0) -> str:
    """Search editable documents in one ShareLaTeX project.

    Read-only. project is a project name or id. The match is
    case-insensitive. Each hit is path, line number, and a short snippet.
    file_pattern filters project paths using glob syntax. max_results is
    1..200 (default 30); context_lines is 0..10. Uploaded files are skipped.
    """

    def action() -> str:
        if not 1 <= max_results <= 200 or not 0 <= context_lines <= 10:
            raise RuntimeError("max_results must be 1..200 and context_lines 0..10.")
        if not query:
            raise RuntimeError("query must not be empty.")
        api = _api()
        project_id = _resolve(api, project).id
        indexed = _index(api.project_get_files(project_id))
        hits: list[str] = []
        docs = [
            (path, entity)
            for path, entity in sorted(indexed.items())
            if isinstance(entity, ProjectFile) and entity.type == "doc" and fnmatch.fnmatchcase(path, file_pattern)
        ]
        for path, entity in docs:
            remaining = max_results + 1 - len(hits)
            if remaining <= 0:
                break
            body = _read_entity(api, project_id, entity)
            matches = search_hits(path, body, query, remaining)
            if context_lines:
                source_lines = body.splitlines()
                for index, hit in enumerate(matches):
                    number = int(hit[len(path) + 1:].split(":", 1)[0])
                    context = [f"  {n + 1}: {_snippet(source_lines[n], query)}" for n in range(max(0, number - 1 - context_lines), min(len(source_lines), number + context_lines))]
                    matches[index] = hit + "\n" + "\n".join(context)
            hits.extend(matches)
        if not hits:
            return "No matches."
        if len(hits) > max_results:
            hits = hits[:max_results] + [f"... results truncated at {max_results} matches."]
        return "\n".join(hits)

    return _call(action)


@mcp.tool(annotations=_WRITE)
def write_file(project: str, file_path: str, content: str, expected_sha256: str | None = None) -> str:
    """Create or overwrite a file in a ShareLaTeX project.

    This changes the remote project. The MCP client controls user confirmation.
    expected_sha256 optionally guards against stale content (UTF-8 SHA-256). project is a project name or id. An existing text
    document is updated in place. An existing uploaded file is re-uploaded.
    A missing file is created by upload. content is the full new text.
    """

    def action() -> str:
        api = _api()
        project_id = _resolve(api, project).id
        indexed = _index(api.project_get_files(project_id))
        path = _norm_path(file_path)
        entity = indexed.get(path)
        if isinstance(entity, ProjectFolder):
            raise RuntimeError(f"{file_path} is a folder.")
        if isinstance(entity, ProjectFile) and entity.type == "doc":
            _apply_doc_ops(api, project_id, entity.id, lambda text: full_replace_ops(text, content), expected_sha256)
            return f"Wrote {path}"
        if expected_sha256 is not None:
            raise RuntimeError("expected_sha256 is supported only for existing editable documents.")
        io = ProjectIO(api, project_id)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return f"Wrote {path}"

    return _call(action)


@mcp.tool(annotations=_WRITE)
def append_to_file(project: str, file_path: str, content: str, expected_sha256: str | None = None) -> str:
    """Append text to the end of an existing file in a ShareLaTeX project.

    This changes the remote project. The MCP client controls user confirmation.
    expected_sha256 optionally guards against stale content (UTF-8 SHA-256). project is a project name or id. file_path must
    already exist. A text document is updated in place. An uploaded file
    is downloaded, extended, and re-uploaded.
    """

    def action() -> str:
        api = _api()
        project_id = _resolve(api, project).id
        path, entity = _lookup(_index(api.project_get_files(project_id)), file_path)
        if entity.type == "doc":
            _apply_doc_ops(api, project_id, entity.id, lambda text: append_ops(text, content), expected_sha256)
            return f"Appended to {path}"
        if expected_sha256 is not None:
            raise RuntimeError("expected_sha256 is supported only for existing editable documents.")
        io = ProjectIO(api, project_id)
        with io.open(path, "a", encoding="utf-8") as handle:
            handle.write(content)
        return f"Appended to {path}"

    return _call(action)


@mcp.tool(annotations=_WRITE)
def replace_in_file(project: str, file_path: str, old_text: str, new_text: str, expected_sha256: str | None = None) -> str:
    """Replace one exact occurrence of text in a ShareLaTeX document.

    This changes the remote project. The MCP client controls user confirmation.
    expected_sha256 optionally guards against stale content (UTF-8 SHA-256). project is a project name or id. The file must be
    an editable text document, not an uploaded binary. old_text must occur
    exactly once. new_text may be empty to delete that occurrence.
    """

    def action() -> str:
        api = _api()
        project_id = _resolve(api, project).id
        path, entity = _lookup(_index(api.project_get_files(project_id)), file_path)
        if entity.type != "doc":
            raise RuntimeError(f"{path} is an uploaded file. Use write_file to replace it.")
        _apply_doc_ops(
            api,
            project_id,
            entity.id,
            lambda text: replacement_ops(text, old_text, new_text),
            expected_sha256,
        )
        return f"Updated {path}"

    return _call(action)


@mcp.tool(annotations=_READ_ONLY)
def compile_project(project: str, root_file: str | None = None) -> str:
    """Compile a ShareLaTeX project and return errors and warnings.

    Read-only with respect to project source. project is a project name or
    id. The result starts with the compile status and then lists error and
    warning lines from output.log. root_file overrides automatic root
    selection. Busy, timeout and unavailable logs are reported explicitly.
    """

    def action() -> str:
        api = _api()
        chosen = _resolve(api, project)
        indexed = _index(api.project_get_files(chosen.id))
        root_path = _lookup(indexed, root_file)[0] if root_file else _choose_root(api, chosen.id, indexed)
        root_id = None
        if root_path is not None:
            root = indexed[root_path]
            if isinstance(root, ProjectFile) and root.type == "doc":
                root_id = root.id
        return _compile_log(api, chosen.id, root_id)

    return _call(action)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
