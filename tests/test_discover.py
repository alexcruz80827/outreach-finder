"""Synthetic fixtures below are unit-test data, never discovery evidence."""
import base64
import sys
import importlib.util
import pathlib
import io
from contextlib import redirect_stdout, redirect_stderr
import json
import tempfile
import subprocess
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('discover', ROOT / 'discover.py')


class DiscoveryTests(unittest.TestCase):
    def load(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        out = redirect_stdout(self.stdout)
        err = redirect_stderr(self.stderr)
        out.__enter__()
        err.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        self.addCleanup(err.__exit__, None, None, None)
        self.assertTrue((ROOT / 'discover.py').exists(), 'discovery collector is missing')
        module = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(module)
        return module

    def test_collect_preserves_exact_raw_evidence_and_argv(self):
        d = self.load()
        raw = 'Title: Synthetic founder\nURL: https://example.org/founder\nPublished: 2026-01-01\nHighlights: synthetic test only\n'
        with patch.object(d.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, raw.encode('utf-8'), b'')) as run:
            record = d.collect('AI founders revenue', 5)
        run.assert_called_once_with(['mcporter', 'call', 'exa.web_search_exa', 'query=AI founders revenue', 'numResults=5'], capture_output=True, timeout=90, shell=False)
        self.assertEqual(record['raw_response'], raw)
        self.assertEqual(record['status'], 'success')
        self.assertEqual(record['urls'], ['https://example.org/founder'])
        self.assertEqual(record['query'], 'AI founders revenue')
        self.assertTrue(record['time'])
        self.assertIsNone(record['error'])

    def test_real_subprocess_preserves_mixed_line_endings_and_raw_bytes(self):
        d = self.load()
        real_run = subprocess.run
        for suffix in (b'valid UTF-8: \xc3\xa9', b'invalid UTF-8: \xff\xfe'):
            raw = b'Title: fixture\r\nURL: https://example.org/test\r\nHighlights: first\nsecond\rthird\r\n' + suffix
            stderr = b'diagnostic\r\nnext\rlast\n' + suffix
            script = 'import os; os.write(1, {!r}); os.write(2, {!r})'.format(raw, stderr)

            def run_fixture(argv, **kwargs):
                return real_run([sys.executable, '-c', script], **kwargs)

            with self.subTest(suffix=suffix), patch.object(d.subprocess, 'run', side_effect=run_fixture):
                record = d.collect('synthetic fixture', 1)
                self.assertEqual(record['raw_response'], raw.decode('utf-8', errors='replace'))
                self.assertEqual(base64.b64decode(record['raw_response_base64']), raw)
                self.assertEqual(record['stderr'], stderr.decode('utf-8', errors='replace'))
                self.assertEqual(base64.b64decode(record['stderr_base64']), stderr)
                self.assertEqual(record['status'], 'success')
                self.assertEqual(record['urls'], ['https://example.org/test'])
                with tempfile.TemporaryDirectory() as tmp:
                    output = pathlib.Path(tmp) / 'discovery.json'
                    d.append_records(output, [record])
                    stored = json.loads(output.read_text())['runs'][0]
                    self.assertEqual(stored, record)

    def test_timeout_preserves_partial_raw_bytes(self):
        d = self.load()
        for raw, stderr in ((b'partial\r\nnext\rlast\n\xff', b'error\r\n\xfe'), (None, None)):
            with self.subTest(raw=raw), patch.object(
                    d.subprocess, 'run', side_effect=subprocess.TimeoutExpired(
                        ['mcporter'], 90, output=raw, stderr=stderr)):
                record = d.collect('synthetic fixture', 1)
            self.assertEqual(record['status'], 'error')
            self.assertEqual(record['error'], 'Timeout after 90 seconds')
            self.assertEqual(record['raw_response'], (raw or b'').decode('utf-8', errors='replace'))
            self.assertEqual(record['stderr'], (stderr or b'').decode('utf-8', errors='replace'))
            self.assertEqual(base64.b64decode(record['raw_response_base64']), raw or b'')
            self.assertEqual(base64.b64decode(record['stderr_base64']), stderr or b'')

    def test_failures_are_records_not_successful_empty_results(self):
        d = self.load()
        cases = [
            (FileNotFoundError('mcporter missing'), '', 'missing'),
            (subprocess.TimeoutExpired(['mcporter'], 90, output=b'partial'), 'partial', 'timeout'),
            (subprocess.CompletedProcess([], 1, b'partial', b'provider failed'), 'partial', 'provider failed'),
            (subprocess.CompletedProcess([], 0, b'', b''), '', 'invalid'),
            (subprocess.CompletedProcess([], 0, b'{"error":"bad API key"}', b''), '{"error":"bad API key"}', 'invalid'),
            (subprocess.CompletedProcess([], 0, b'nonsense https://example.org/not-a-hit', b''), 'nonsense https://example.org/not-a-hit', 'invalid'),
        ]
        for result, raw, error in cases:
            with self.subTest(error=error):
                kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
                with patch.object(d.subprocess, 'run', **kwargs):
                    record = d.collect('synthetic fixture', 1)
                self.assertEqual(record['status'], 'error')
                self.assertEqual(record['raw_response'], raw)
                self.assertIn(error, record['error'].lower())
                self.assertTrue(record['time'])

    def test_invalid_query_and_limits_never_call_provider(self):
        d = self.load()
        with patch.object(d.subprocess, 'run') as run:
            for query, limit in [('', 1), (' ', 1), ('x' * 501, 1), ('x\nother', 1), ('x', 0), ('x', 11), ('x', True), ('x', 1.5)]:
                with self.subTest(query=query, limit=limit), self.assertRaises(ValueError):
                    d.collect(query, limit)
            run.assert_not_called()

    def test_append_preserves_evidence_deduplicates_candidates_and_is_atomic(self):
        d = self.load()
        record = {'query': 'synthetic', 'time': 'fixture time', 'status': 'success', 'error': None,
                  'raw_response': 'URL: https://example.org/test\nHighlights: synthetic only',
                  'urls': ['https://example.org/test']}
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / 'nested' / 'discovery.json'
            first = d.append_records(output, [record])
            second = d.append_records(output, [record, dict(record, status='error', error='fixture failure')])
            self.assertEqual(len(first['runs']), 1)
            self.assertEqual(len(second['runs']), 3)
            self.assertEqual(len(second['candidates']), 1)
            candidate = second['candidates'][0]
            self.assertEqual(candidate['status'], 'unverified_search_hit')
            self.assertEqual(candidate['evidence_run_indexes'], [0, 1])
            self.assertEqual(second['purpose'], 'discovery_only_not_qualified_import')
            self.assertEqual(json.loads(output.read_text()), second)
            original = output.read_bytes()
            with patch.object(d.os, 'replace', side_effect=OSError('synthetic write failure')):
                with self.assertRaises(OSError):
                    d.append_records(output, [record])
            self.assertEqual(output.read_bytes(), original)
            output.write_text('{broken')
            with self.assertRaises(ValueError):
                d.append_records(output, [record])
            self.assertEqual(output.read_text(), '{broken')

    def test_cli_query_and_preset_save_each_call_and_report_errors(self):
        d = self.load()
        success = {'query': 'synthetic', 'time': 'fixture', 'status': 'success', 'error': None,
                   'raw_response': 'synthetic test only', 'urls': ['https://example.org/test']}
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / 'discovery.json'
            with patch.object(d, 'collect', return_value=success) as collect:
                self.assertEqual(d.main(['--query', 'literal $(not executed)', '--limit', '5', '--output', str(output)]), 0)
                collect.assert_called_once_with('literal $(not executed)', 5)
            with patch.object(d, 'collect', return_value=dict(success, status='error', error='synthetic failure')) as collect:
                self.assertEqual(d.main(['--preset', 'ai-founders', '--limit', '2', '--output', str(output)]), 1)
                self.assertEqual(collect.call_count, 3)
                self.assertTrue(all(call.args[1] == 2 for call in collect.call_args_list))
                self.assertIn('"AI" "founder" "YouTube" "hiring" "editor"', [call.args[0] for call in collect.call_args_list])
            self.assertEqual(len(json.loads(output.read_text())['runs']), 4)

    def test_cli_invalid_arguments_do_not_call_provider(self):
        d = self.load()
        with patch.object(d, 'collect') as collect:
            for args in [[], ['--query', ''], ['--query', 'x', '--limit', '11'], ['--query', 'x', '--preset', 'ai-founders']]:
                with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                    d.main(args)
                self.assertEqual(raised.exception.code, 2)
            collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
