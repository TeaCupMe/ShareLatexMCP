"""Explicit live test on a disposable project, with content-based restoration guard."""
import argparse
import hashlib
import uuid

from sharelatex_mcp.server import append_to_file, read_file, replace_in_file, compile_project


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='Disposable project name or ID')
    parser.add_argument('--file', default='main.tex')
    parser.add_argument('--allow-write', action='store_true', required=True)
    args = parser.parse_args()
    original = read_file(args.project, args.file)
    marker = '\n% MCP integration ' + uuid.uuid4().hex + '\n'
    try:
        append_to_file(args.project, args.file, marker, expected_sha256=digest(original))
        updated = read_file(args.project, args.file)
        if updated != original + marker:
            raise RuntimeError('Unexpected post-edit contents; inspect the test project.')
    finally:
        current = read_file(args.project, args.file)
        if marker in current:
            replace_in_file(args.project, args.file, marker, '', expected_sha256=digest(current))
    if read_file(args.project, args.file) != original:
        raise RuntimeError('Content differs from the initial snapshot; inspect concurrent edits.')
    print('Edit and restoration verified.')
    print(compile_project(args.project, root_file=args.file))


if __name__ == '__main__':
    main()
