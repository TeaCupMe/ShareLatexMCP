"""Run with the Python of a non-editable wheel installation, preferably with -I."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from importlib.metadata import version
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def probe(command, args, cwd):
    params = StdioServerParameters(command=str(command), args=args, cwd=cwd)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.list_tools()
            tools = {tool.name: tool for tool in result.tools}
            assert len(tools) == 11
            assert tools['write_file'].annotations.destructive_hint
            assert 'expected_sha256' in tools['write_file'].input_schema['properties']


def main():
    executable = Path(sys.executable).parent / ('sharelatex-mcp.exe' if os.name == 'nt' else 'sharelatex-mcp')
    with tempfile.TemporaryDirectory() as cwd:
        for command, args in [(executable, []), (sys.executable, ['-I', '-m', 'sharelatex_mcp'])]:
            for flag in ['--help', '--version']:
                result = subprocess.run([str(command), *args, flag], cwd=cwd, capture_output=True, text=True, check=True, timeout=20)
                assert result.stdout.strip()
                if flag == '--version':
                    assert result.stdout.strip() == version('sharelatex-mcp')
            asyncio.run(asyncio.wait_for(probe(command, args, cwd), timeout=30))
    print('Installed command and module verified outside the checkout.')


if __name__ == '__main__':
    main()
