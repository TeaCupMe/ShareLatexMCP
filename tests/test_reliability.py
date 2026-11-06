import hashlib
import os
import unittest
from unittest.mock import Mock, patch
from sharelatex_mcp import server as s


class ReliabilityTests(unittest.TestCase):
    def test_secret_never_reaches_logger(self):
        with patch.dict(os.environ, {'OVERLEAF_COOKIE': 'sid=private+value'}):
            with self.assertLogs('sharelatex', 'ERROR') as logs:
                with self.assertRaisesRegex(RuntimeError, 'redacted'):
                    s._call(lambda: (_ for _ in ()).throw(ValueError('private+value private%2Bvalue')))
        self.assertNotIn('private', '\n'.join(logs.output))

    def test_url_validation(self):
        for url in ['http://example.org', 'https://example.org/prefix', 'https://user:pass@example.org', 'https://example.org:8443']:
            with patch.dict(os.environ, {'OVERLEAF_URL': url}):
                with self.assertRaises(RuntimeError):
                    s._host()
        with patch.dict(os.environ, {'OVERLEAF_URL': 'https://example.org:443'}):
            self.assertEqual(s._host(), 'example.org')

    def test_nested_heading_and_comment(self):
        text = '% \\section{Hidden}\n\\section{A \\textbf{bold} title}\nbody'
        self.assertEqual([h.title for h in s.headings_in(text)], [r'A \textbf{bold} title'])

    def test_hash_conflict_prevents_write(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.join_doc.return_value = [None, ['new content'], 2]
        with patch.object(s, '_ProjectSocket', return_value=connection):
            with self.assertRaisesRegex(RuntimeError, 'Content changed'):
                s._apply_doc_ops(Mock(), 'project', 'doc', lambda text: s.append_ops(text, '!'), hashlib.sha256(b'old content').hexdigest())
        connection.call.assert_not_called()

    def test_disconnection_reports_uncertain_result_without_retry(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.join_doc.return_value = [None, ['text'], 2]
        connection.call.side_effect = ConnectionError('closed')
        with patch.object(s, '_ProjectSocket', return_value=connection):
            with self.assertRaisesRegex(RuntimeError, 'outcome is unknown'):
                s._apply_doc_ops(Mock(), 'project', 'doc', lambda text: s.append_ops(text, '!'))
        self.assertEqual(connection.call.call_count, 1)

    def test_failed_handshake_closes_socket(self):
        api = Mock()
        with patch.object(s._ProjectSocket, '_recv_until', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                with s._ProjectSocket(api, 'project'):
                    pass
        api._open_socket.return_value.close.assert_called_once()

    def test_rejected_update(self):
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            s._check_update_ack(['version conflict'])

    def test_log_reports_file_errors_and_truncation(self):
        result = s.compile_log_lines('main.tex:12: Undefined control sequence.\n! fatal\n', 1)
        self.assertIn('main.tex:12:', result[0])
        self.assertIn('truncated', result[-1])

    def test_recursive_outline_cycle(self):
        from pyoverleaf import ProjectFile, ProjectFolder
        files = ProjectFolder('root', '', [ProjectFile('a', 'main.tex', None, 'doc'), ProjectFile('b', 'child.tex', None, 'doc')])
        api = Mock()
        api.project_get_files.return_value = files
        bodies = {'a': '\\input{child}', 'b': '\\section{Child}\n\\input{main}'}
        with patch.object(s, '_api', return_value=api), patch.object(s, '_resolve', return_value=Mock(id='p')), patch.object(s, '_read_entity', side_effect=lambda api, pid, entity: bodies[entity.id]):
            outline = s.project_outline('project')
        self.assertIn('Child', outline)
        self.assertIn('cycle', outline)

class CompileAndSearchTests(unittest.TestCase):
    def api(self, status=200, payload=None):
        api = Mock()
        api._host = 'example.org'
        response = api._get_session.return_value.post.return_value
        response.status_code = status
        response.json.return_value = payload or {'status': 'success'}
        return api

    def test_busy_queue(self):
        self.assertIn('status: busy', s._compile_log(self.api(429), 'p', None))

    def test_compile_timeout(self):
        import requests
        api = self.api()
        api._get_session.return_value.post.side_effect = requests.Timeout()
        self.assertIn('status: timeout', s._compile_log(api, 'p', None))

    def test_missing_log_does_not_claim_no_warnings(self):
        result = s._compile_log(self.api(), 'p', None)
        self.assertIn('unavailable', result)
        self.assertNotIn('No errors', result)

    def test_search_filter_context_and_cap(self):
        from pyoverleaf import ProjectFile, ProjectFolder
        api = Mock()
        api.project_get_files.return_value = ProjectFolder('r', '', [ProjectFile('a', 'main.tex', None, 'doc'), ProjectFile('b', 'skip.bib', None, 'doc')])
        with patch.object(s, '_api', return_value=api), patch.object(s, '_resolve', return_value=Mock(id='p')), patch.object(s, '_read_entity', return_value='before\nneedle\nafter\nneedle') as read:
            result = s.search_project('project', 'needle', '*.tex', 1, 1)
        self.assertIn('main.tex:2:', result)
        self.assertIn('1: before', result)
        self.assertIn('truncated', result)
        self.assertEqual(read.call_count, 1)
