"""Offline STDIO smoke test: no credentials or remote writes required."""
import asyncio
import sys
from pathlib import Path
import unittest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class StdioTests(unittest.TestCase):
    def test_handshake_and_tools(self):
        async def check(command, args):
            params = StdioServerParameters(command=command, args=args)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    tools = {tool.name: tool for tool in result.tools}
                    self.assertEqual(len(tools), 11)
                    self.assertTrue(tools['write_file'].annotations.destructive_hint)
                    self.assertIn('expected_sha256', tools['write_file'].input_schema['properties'])
                    self.assertIn('root_file', tools['compile_project'].input_schema['properties'])
        executable = Path(sys.executable).parent / ('sharelatex-mcp.exe' if sys.platform == 'win32' else 'sharelatex-mcp')
        for command, args in [(sys.executable, ['-m', 'sharelatex_mcp']), (str(executable), []), (sys.executable, ['server.py'])]:
            with self.subTest(command=command, args=args):
                asyncio.run(asyncio.wait_for(check(command, args), 30))
