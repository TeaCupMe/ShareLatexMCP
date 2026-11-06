"""Check public source candidates and release archives without printing secrets."""
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'.codex', '.cursor', '.git', '.venv', '.venv-check', '__pycache__'}
SECRET = re.compile(rb's:[A-Za-z0-9_-]{20,}\.[A-Za-z0-9%+/=_-]{20,}')
HOME_PATH = re.compile(rb'(?:[A-Za-z]:[\\/]+Users[\\/]+|/Users/|/home/)[A-Za-z0-9_.-]+[\\/]')


def check(name, data):
    parts = PurePosixPath(name.replace('\\', '/')).parts
    if any(part in FORBIDDEN or part.startswith('.venv') for part in parts):
        raise RuntimeError(f'Private or generated path in publication: {name}')
    if any(part == '.env' or (part.startswith('.env.') and part != '.env.example') for part in parts):
        raise RuntimeError(f'Environment secrets file in publication: {name}')
    if SECRET.search(data) or HOME_PATH.search(data):
        raise RuntimeError(f'Potential session secret or personal absolute path in: {name}; inspect privately')


def main():
    candidates = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT
    ).split(b'\0')
    count = 0
    for raw in candidates:
        if raw:
            path = Path(raw.decode('utf-8'))
            check(path.as_posix(), (ROOT / path).read_bytes())
            count += 1
    print(f'Checked {count} public Git file candidates.')
    import tomllib
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    version = project['version']
    stem = 'sharelatex_mcp-' + version
    wheel = ROOT / 'dist' / (stem + '-py3-none-any.whl')
    source = ROOT / 'dist' / (stem + '.tar.gz')
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert 'sharelatex_mcp/server.py' in names, 'Server missing from wheel'
        metadata = archive.read(stem + '.dist-info/METADATA').decode()
        assert 'License-Expression: MIT' in metadata
        assert ('Version: ' + version) in metadata
        assert any(name.endswith('/licenses/LICENSE') for name in names)
        assert 'sharelatex-mcp' in archive.read(stem + '.dist-info/entry_points.txt').decode()
        for name in names:
            check(name, archive.read(name))
    with tarfile.open(source) as archive:
        names = archive.getnames()
        assert any(name.endswith('/tests/test_stdio.py') for name in names)
        assert any(name.endswith('/docs/releasing.md') for name in names)
        for member in archive.getmembers():
            if member.isfile():
                check(member.name, archive.extractfile(member).read())
    print(f'Checked wheel and source distribution for version {version}.')


if __name__ == '__main__':
    main()
