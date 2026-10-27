import copy
import importlib.util
import json
import tempfile
import subprocess
import sys
import csv
import io
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

try:
    import app
except ImportError:
    app = None


def prospect(**changes):
    p = dict(id='test-owner', name='Test Owner', company='Example', website='https://example.test/', niche='AI operations', offer='Consulting', youtube_status='unknown', expertise_summary='Public case study', opportunity_hypothesis='Educational video may help', intent='inferred', income_status='commercial_signal_only', income_summary='Offer exists; revenue unknown', evidence=[dict(category='offer', url='https://example.test/offer', title='Offer', excerpt='Consulting services', observed_at='2026-10-26T12:00:00Z')], caveats=['Revenue not verified'], status='new', notes='')
    p.update(changes)
    return p


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'test.sqlite3'


class StoreTests(DatabaseCase):
    def test_import_persists_evidence_backed_prospect(self):
        self.assertIsNotNone(app, 'app module must exist')
        app.init_db(self.db)
        self.assertEqual(app.import_prospects(self.db, {'prospects': [prospect()]}), 1)
        rows = app.list_prospects(self.db)
        self.assertEqual(rows[0]['name'], 'Test Owner')
        self.assertEqual(rows[0]['evidence'][0]['url'], 'https://example.test/offer')
        self.assertEqual(len(rows), 1)

    def test_verified_x_roundtrips_primary_source_evidence_and_exports(self):
        p = prospect(x_url='https://x.com/Test_Owner', x_handle='test_owner', x_status='verified')
        p['evidence'].append(dict(category='x_profile', url='https://example.test/about', title='Owner biography', excerpt='Find Test Owner on X: https://x.com/Test_Owner', observed_at='2026-10-26T12:00:00Z'))
        app.import_prospects(self.db, {'prospects': [p]})
        self.assertEqual(app.list_prospects(self.db)[0], p)
        self.assertEqual(json.loads(app.export_data(self.db, 'json'))['prospects'][0], p)
        row = next(csv.DictReader(io.StringIO(app.export_data(self.db, 'csv'))))
        for key in ('x_url', 'x_handle', 'x_status'):
            self.assertEqual(row[key], p[key])

    def test_x_fields_are_strict_and_cross_consistent(self):
        valid = dict(x_url='https://x.com/Test_Owner', x_handle='test_owner', x_status='unverified')
        for domain in ('x.com', 'twitter.com'):
            app.validate_prospect(prospect(**{**valid, 'x_url': 'https://' + domain + '/Test_Owner'}))
        for status in ('unknown', 'not_found'):
            app.validate_prospect(prospect(x_status=status, x_url=None, x_handle=None))
        app.validate_prospect(prospect())
        invalid_urls = ['http://x.com/Test_Owner', 'https://www.x.com/Test_Owner', 'https://x.com.evil.test/Test_Owner', 'https://user@x.com/Test_Owner', 'https://x.com:443/Test_Owner', 'https://x.com/Test_Owner/', 'https://x.com/Test_Owner/status/1', 'https://x.com/Test_Owner?', 'https://x.com/Test_Owner#', 'https://x.com/%54est_Owner', 'https://x.com/é', 'https://x.com/' + 'a'*16, 'https://x.com/Test_Owner\n']
        bad = [{**valid, 'x_url': url} for url in invalid_urls]
        bad += [{**valid, 'x_url': 'https://x.com/' + name, 'x_handle': name} for name in ('home', 'SEARCH', 'intent', 'messages', 'settings', 'i', 'explore', 'compose', 'login', 'signup')]
        bad += [{**valid, field: value} for field in ('x_url', 'x_handle', 'x_status') for value in (True, False, 12, [], {}, '')]
        bad += [{**valid, 'x_handle': '@test_owner'}, {**valid, 'x_handle': 'different'}, {**valid, 'x_status': 'verified'}, {**valid, 'x_status': 'unknown'}, {**valid, 'x_status': 'not_found'}, {'x_url': valid['x_url']}, {'x_handle': valid['x_handle']}, {'x_status': 'verified'}, {'x_status': None}]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                app.validate_prospect(prospect(**changes))

    def test_x_reimport_preserves_suppression_notes_and_legacy_csv(self):
        app.import_prospects(self.db, {'prospects': [prospect(status='do_not_contact', notes='Opted out')]})
        row = next(csv.DictReader(io.StringIO(app.export_data(self.db, 'csv'))))
        self.assertEqual([row[k] for k in ('x_url', 'x_handle', 'x_status')], ['', '', ''])
        app.import_prospects(self.db, {'prospects': [prospect(x_status='unverified', x_url='https://twitter.com/Test_Owner', x_handle='Test_Owner')]})
        p = app.list_prospects(self.db)[0]
        self.assertEqual((p['status'], p['notes'], p['x_handle']), ('do_not_contact', 'Opted out', 'Test_Owner'))

    def test_source_dates_preserve_calendar_precision(self):
        for source_date in ('2026-10', '2026-10-04', '2026-10-04T12:30:00Z'):
            with self.subTest(source_date=source_date):
                p = prospect()
                p['evidence'][0]['source_date'] = source_date
                app.import_prospects(self.db, {'prospects': [p]})
                self.assertEqual(app.list_prospects(self.db)[0]['evidence'][0]['source_date'], source_date)
        for source_date in ('2026-13', '2026-02-30', '2026-13-01', '2026-2', '20261004'):
            with self.subTest(source_date=source_date):
                p = prospect()
                p['evidence'][0]['source_date'] = source_date
                with self.assertRaises(ValueError):
                    app.import_prospects(self.db, {'prospects': [p]})

    def test_observed_at_requires_timezone_aware_datetime(self):
        for observed_at in ('2026-10', '2026-10-26', '2026-10-26T12:30:00', '2026-02-30T12:30:00Z'):
            with self.subTest(observed_at=observed_at):
                p = prospect()
                p['evidence'][0]['observed_at'] = observed_at
                with self.assertRaises(ValueError):
                    app.import_prospects(self.db, {'prospects': [p]})
        for observed_at in ('2026-10-26T12:30:00Z', '2026-10-26T12:30:00-04:00'):
            with self.subTest(observed_at=observed_at):
                p = prospect()
                p['evidence'][0]['observed_at'] = observed_at
                app.import_prospects(self.db, {'prospects': [p]})
                self.assertEqual(app.list_prospects(self.db)[0]['evidence'][0]['observed_at'], observed_at)

    def test_invalid_batch_is_atomic(self):
        app.init_db(self.db)
        bad_cases = [dict(evidence=[]), dict(status='sent'), dict(website='javascript:alert(1)'), dict(income_status='rich'), dict(youtube_status='popular'), dict(intent='certain'), dict(caveats='none'), dict(id='../escape'), dict(evidence=[dict(category='bad', url='https://example.test', title='x', excerpt='x', observed_at='2026-10-26T12:00:00Z')])]
        for changes in bad_cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    app.import_prospects(self.db, {'prospects': [prospect(id='valid', name='Different Person'), prospect(**changes)]})
                self.assertEqual(app.list_prospects(self.db), [])

    def test_reimport_deduplicates_person_not_cofounders_and_preserves_review(self):
        app.import_prospects(self.db, {'prospects': [prospect(status='do_not_contact', notes='Human decision')]})
        app.import_prospects(self.db, {'prospects': [prospect(id='alternate', name='  TEST  Owner ', website='http://www.example.test/?utm_source=x', offer='Updated')]})
        rows = app.list_prospects(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], 'test-owner')
        self.assertEqual(rows[0]['status'], 'do_not_contact')
        self.assertEqual(rows[0]['notes'], 'Human decision')
        self.assertEqual(rows[0]['offer'], 'Updated')
        app.import_prospects(self.db, {'prospects': [prospect(id='cofounder', name='Other Founder')]})
        self.assertEqual(len(app.list_prospects(self.db)), 2)

    def test_stable_id_cannot_reassign_identity_or_partial_commit(self):
        app.import_prospects(self.db, {'prospects': [prospect()]})
        with self.assertRaises(ValueError):
            app.import_prospects(self.db, {'prospects': [prospect(id='another', name='Another'), prospect(name='Different Person')]})
        self.assertEqual(len(app.list_prospects(self.db)), 1)

    def test_review_updates_allow_only_status_notes_and_suppression_is_sticky(self):
        app.import_prospects(self.db, {'prospects': [prospect()]})
        self.assertTrue(hasattr(app, 'update_prospect'), 'review update required')
        app.update_prospect(self.db, 'test-owner', {'status': 'shortlist', 'notes': 'Reviewed'})
        self.assertEqual(app.list_prospects(self.db)[0]['notes'], 'Reviewed')
        for bad in ({'offer': 'hack'}, {'status': 'sent'}, {'notes': 3}, {}):
            with self.assertRaises(ValueError):
                app.update_prospect(self.db, 'test-owner', bad)
        app.update_prospect(self.db, 'test-owner', {'status': 'do_not_contact'})
        with self.assertRaises(ValueError):
            app.update_prospect(self.db, 'test-owner', {'status': 'shortlist'})
        app.import_prospects(self.db, {'prospects': [prospect()]})
        self.assertEqual(app.list_prospects(self.db)[0]['status'], 'do_not_contact')
        with self.assertRaises(KeyError):
            app.update_prospect(self.db, 'missing', {'notes': 'no'})

    def test_fit_indicators_are_evidence_categories_not_income_scores(self):
        self.assertTrue(hasattr(app, 'fit_indicators'), 'transparent indicators required')
        result = app.fit_indicators(prospect())
        self.assertEqual(result['cited_categories'], ['offer'])
        self.assertEqual(result['income_label'], 'Revenue unverified')
        self.assertEqual(result['intent_label'], 'Inferred — hypothesis, not expressed intent')
        self.assertNotIn('score', result)

    def test_stronger_claims_need_matching_citations(self):
        for changes in ({'income_status': 'self_reported'}, {'income_status': 'independently_verified'}, {'intent': 'explicit'}, {'youtube_status': 'active'}, {'youtube_status': 'occasional', 'youtube_url': 'https://youtube.com/@test'}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    app.import_prospects(self.db, {'prospects': [prospect(**changes)]})
        evidence = [dict(category=c, url='https://example.test/'+c, title=c, excerpt='Human-verifiable source', observed_at='2026-10-26T12:00:00Z', source_date='2026-01-01') for c in ('income', 'youtube', 'intent')]
        app.import_prospects(self.db, {'prospects': [prospect(income_status='self_reported', intent='explicit', youtube_status='occasional', youtube_url='https://youtube.com/@test', evidence=evidence)]})
        self.assertEqual(len(app.list_prospects(self.db)), 1)


class ApiTests(DatabaseCase):
    def request(self, method='GET', path='/api/prospects', headers=None, body=b''):
        return app.handle_request(self.db, method, path, headers or {'Host': '127.0.0.1:3016'}, body, 3016)

    def test_read_api_security_and_health(self):
        self.assertTrue(hasattr(app, 'handle_request'), 'HTTP boundary required')
        app.import_prospects(self.db, {'prospects': [prospect()]})
        code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(body)['prospects']), 1)
        self.assertIn('Content-Security-Policy', headers)
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(self.request(path='/api/health')[0], 200)
        self.assertEqual(self.request(headers={'Host': 'evil.example:3016'})[0], 403)
        self.assertEqual(self.request(path='/../../app.py')[0], 404)

    def test_invalid_unicode_notes_are_rejected_before_commit(self):
        app.import_prospects(self.db, {'prospects': [prospect(notes='Original')]})
        headers = {'Host': '127.0.0.1:3016', 'Origin': 'http://127.0.0.1:3016', 'Content-Type': 'application/json'}
        for invalid in ('\ud800', '\udfff', 'prefix\ud800suffix'):
            with self.subTest(value=repr(invalid)):
                code, _, _ = self.request('POST', '/api/prospects/test-owner', headers, json.dumps({'notes': invalid}).encode())
                self.assertEqual(code, 400)
                self.assertEqual(app.list_prospects(self.db)[0]['notes'], 'Original')
                self.assertEqual(self.request()[0], 200)
                with self.assertRaises(ValueError):
                    app.validate_prospect(prospect(name=invalid))
        valid = 'Café 😀'
        self.assertEqual(self.request('POST', '/api/prospects/test-owner', headers, json.dumps({'notes': valid}).encode())[0], 200)
        self.assertEqual(json.loads(self.request()[2])['prospects'][0]['notes'], valid)

    def test_deep_json_is_rejected_without_mutating_workspace(self):
        app.import_prospects(self.db, {'prospects': [prospect(notes='Original')]})
        headers = {'Host': '127.0.0.1:3016', 'Origin': 'http://127.0.0.1:3016', 'Content-Type': 'application/json'}
        body = b'[' * 1500 + b']' * 1500
        self.assertLess(len(body), app.MAX_BODY)
        for path in ('/api/settings', '/api/prospects/test-owner'):
            with self.subTest(path=path):
                code, _, raw = self.request('POST', path, headers, body)
                self.assertEqual(code, 400)
                self.assertIn('error', json.loads(raw))
                self.assertEqual(self.request(path='/api/settings')[0], 200)
                self.assertEqual(json.loads(self.request(path='/api/settings')[2])['daily_target'], 30)
                self.assertEqual(json.loads(self.request()[2])['prospects'][0]['notes'], 'Original')

    def test_write_requires_exact_local_origin_json_and_allowlisted_fields(self):
        self.assertTrue(hasattr(app, 'handle_request'), 'HTTP boundary required')
        app.import_prospects(self.db, {'prospects': [prospect()]})
        good = {'Host': '127.0.0.1:3016', 'Origin': 'http://127.0.0.1:3016', 'Content-Type': 'application/json'}
        path = '/api/prospects/test-owner'
        body = b'{"status":"shortlist","notes":"Reviewed"}'
        for bad in ({**good, 'Origin': 'https://evil.test'}, {**good, 'Origin': 'null'}, {**good, 'Host': 'evil.test:3016'}, {k:v for k,v in good.items() if k != 'Origin'}):
            self.assertEqual(self.request('POST', path, bad, body)[0], 403)
        self.assertEqual(self.request('POST', path, {**good, 'Content-Type': 'text/plain'}, body)[0], 415)
        self.assertEqual(self.request('POST', path, good, b'{')[0], 400)
        self.assertEqual(self.request('POST', path, good, b'{"offer":"bad"}')[0], 400)
        self.assertEqual(self.request('POST', path, good, body)[0], 200)
        self.assertEqual(app.list_prospects(self.db)[0]['notes'], 'Reviewed')
        self.assertEqual(self.request('POST', '/api/prospects/missing', good, body)[0], 404)
        self.assertEqual(self.request('POST', path, good, b'x'*65537)[0], 413)

    def test_explicit_proxy_origin_allows_reads_and_note_updates(self):
        app.import_prospects(self.db, {'prospects': [prospect()]})
        origin = 'http://100.72.26.84:3016'
        headers = {'Host': '100.72.26.84:3016', 'Origin': origin, 'Content-Type': 'application/json'}
        def request(method, path, body=b''):
            return app.handle_request(self.db, method, path, headers, body, 3016, allowed_origins=(origin,))
        self.assertEqual(request('GET', '/')[0], 200)
        self.assertEqual(request('GET', '/api/prospects')[0], 200)
        code, response_headers, body = request('POST', '/api/prospects/test-owner', b'{"notes":"Tailnet review"}')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['prospect']['notes'], 'Tailnet review')
        self.assertEqual(app.list_prospects(self.db)[0]['notes'], 'Tailnet review')
        self.assertNotIn('Access-Control-Allow-Origin', response_headers)

    def test_proxy_allowlist_rejects_foreign_hosts_and_origins_without_trusting_forwarding(self):
        app.import_prospects(self.db, {'prospects': [prospect()]})
        origin = 'http://100.72.26.84:3016'
        good = {'Host': '100.72.26.84:3016', 'Origin': origin, 'Content-Type': 'application/json'}
        for changes in ({'Origin': 'https://100.72.26.84:3016'}, {'Origin': 'http://100.72.26.84:3017'}, {'Origin': 'http://evil.test:3016'}, {'Origin': 'null'}, {'Origin': ''}, {'Origin': origin + '/'}, {'Host': '100.72.26.84:3017'}, {'Host': 'evil.test:3016', 'X-Forwarded-Host': good['Host'], 'Forwarded': 'host=100.72.26.84:3016;proto=http'}, {'Host': '127.0.0.1:3016', 'X-Forwarded-Host': good['Host']}):
            with self.subTest(changes=changes):
                result = app.handle_request(self.db, 'POST', '/api/prospects/test-owner', {**good, **changes}, b'{"notes":"bad"}', 3016, allowed_origins=(origin,))
                self.assertEqual(result[0], 403)
        for host in ('evil.test:3016', '100.72.26.84:3017'):
            self.assertEqual(app.handle_request(self.db, 'GET', '/', {'Host': host, 'X-Forwarded-Host': good['Host']}, b'', 3016, allowed_origins=(origin,))[0], 403)
        self.assertEqual(app.list_prospects(self.db)[0]['notes'], '')
        self.assertEqual(self.request(headers=good)[0], 403, 'proxy access must be opt-in')

    def test_invalid_proxy_origin_configuration_is_rejected(self):
        invalid = ('*', 'http://*:3016', 'ftp://100.72.26.84:3016', 'http://user@100.72.26.84:3016', 'http://100.72.26.84:3016/', 'http://100.72.26.84:3016/path', 'http://100.72.26.84:3016?', 'http://100.72.26.84:3016#', 'http://100.72.26.84:0', 'http://100.72.26.84:65536', 'http://100.72.26.84:', 'http://evil.test\\@100.72.26.84:3016', 'http://evil.test\n:3016', 'http://evil.test%2f:3016', 'http://', 'null')
        for origin in invalid:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                app.handle_request(self.db, 'GET', '/', {'Host': '127.0.0.1:3016'}, b'', 3016, allowed_origins=(origin,))
        for origins in (('https://localhost:3016',), ('http://proxy.test:3016', 'https://proxy.test:3016')):
            with self.subTest(origins=origins), self.assertRaises(ValueError):
                app.handle_request(self.db, 'GET', '/', {'Host': '127.0.0.1:3016'}, b'', 3016, allowed_origins=origins)

    def test_dashboard_assets_are_allowlisted_and_external_script_only(self):
        self.assertEqual(self.request(path='/')[0], 200, 'dashboard must be served')
        html = self.request(path='/')[2].decode()
        self.assertIn('id="search"', html)
        self.assertIn('id="income"', html)
        self.assertIn('id="revenue-evidence"', html)
        for route in ('/app.js', '/style.css'):
            self.assertEqual(self.request(path=route)[0], 200)
        js = self.request(path='/app.js')[2].decode()
        self.assertNotIn('innerHTML', js)
        self.assertIn('textContent', js)

    def test_http_parser_rejects_duplicate_content_length_without_listening(self):
        app.init_db(self.db)
        class Request:
            def __init__(self, raw):
                self.input = io.BytesIO(raw)
                self.output = bytearray()
            def makefile(self, *args):
                return self.input
            def sendall(self, data):
                self.output.extend(data)
            def settimeout(self, timeout):
                pass
        raw = b'GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:3016\r\nContent-Length: 0\r\nContent-Length: 200\r\n\r\n'
        request = Request(raw)
        app.Handler(request, ('127.0.0.1', 12345), SimpleNamespace(db=self.db, server_port=3016))
        self.assertIn(b' 400 ', bytes(request.output).split(b'\r\n')[0])
        read = Request(b'GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:3016\r\n\r\n')
        app.Handler(read, ('127.0.0.1', 12345), SimpleNamespace(db=self.db, server_port=3016))
        self.assertIn(b' 200 ', bytes(read.output).split(b'\r\n')[0])
        self.assertTrue(json.loads(bytes(read.output).split(b'\r\n\r\n')[1])['ok'])
        proxy = Request(b'GET /api/health HTTP/1.0\r\nHost: 100.72.26.84:3016\r\n\r\n')
        app.Handler(proxy, ('127.0.0.1', 12345), SimpleNamespace(db=self.db, server_port=3016, allowed_origins=('http://100.72.26.84:3016',)))
        self.assertIn(b' 200 ', bytes(proxy.output).split(b'\r\n')[0])


class CliTests(unittest.TestCase):
    def test_serve_accepts_repeatable_origins_keeps_loopback_and_rejects_invalid_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'db.sqlite3'
            origins = ['http://100.72.26.84:3016', 'https://review.example.test']
            with patch.object(app, 'ThreadingHTTPServer') as factory:
                server = factory.return_value.__enter__.return_value
                self.assertEqual(app.main(['--db', str(db), 'serve', '--allow-origin', origins[0], '--allow-origin', origins[1]]), 0)
                factory.assert_called_once_with(('127.0.0.1', 3016), app.Handler)
                self.assertEqual(tuple(server.allowed_origins), tuple(origins))
                server.serve_forever.assert_called_once_with()
            for invalid in ('http://*:3016', 'http://100.72.26.84:3016/path'):
                result = subprocess.run([sys.executable, str(Path(__file__).with_name('app.py')), '--db', str(db), 'serve', '--allow-origin', invalid], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('Local review:', result.stdout)

    def test_cli_init_import_export_and_no_server_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'db.sqlite3'
            source = Path(tmp) / 'input.json'
            output = Path(tmp) / 'output.json'
            source.write_text(json.dumps({'prospects': [prospect(name='=HYPERLINK("bad")')]}))
            def run(*args):
                return subprocess.run([sys.executable, str(Path(__file__).with_name('app.py')), '--db', str(db), *args], capture_output=True, text=True)
            self.assertEqual(run('init').returncode, 0)
            self.assertTrue(db.exists(), 'init must create database')
            self.assertEqual(run('import', str(source)).returncode, 0)
            self.assertEqual(run('export', str(output)).returncode, 0)
            self.assertEqual(len(json.loads(output.read_text())['prospects']), 1)
            csvpath = Path(tmp) / 'output.csv'
            self.assertEqual(run('export', str(csvpath), '--format', 'csv').returncode, 0)
            rows = list(csv.DictReader(io.StringIO(csvpath.read_text())))
            self.assertTrue(rows[0]['name'].startswith("'="))
            self.assertIn('3016', run('serve', '--help').stdout)
            self.assertNotEqual(run('import', str(Path(tmp)/'missing')).returncode, 0)


if __name__ == '__main__':
    unittest.main()
