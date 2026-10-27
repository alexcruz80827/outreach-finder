#!/usr/bin/env python3
"""Local evidence review. Python standard library only."""
import json
import argparse
import csv
import io
import sys
import sqlite3
import re
import ipaddress
import outreach
from datetime import datetime
from urllib.parse import urlsplit
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
MAX_BODY = 65536
SECURITY_HEADERS = {'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'", 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store'}


def valid_origin(value):
    """Accept literal HTTP(S) origins, never URL paths or wildcard hosts."""
    if not isinstance(value, str) or not re.fullmatch(r'https?://(?:[a-z0-9.-]+|\[[0-9a-f:]+\])(?::[1-9][0-9]{0,4})?', value):
        raise ValueError('Expected an exact HTTP(S) origin without path, credentials, query or fragment')
    parsed = urlsplit(value)
    host = parsed.hostname
    if ':' in host:
        ipaddress.IPv6Address(host)
    elif len(host) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
        raise ValueError('Invalid origin hostname')
    parsed.port  # Reject out-of-range ports.
    return value


def origin_map(port, allowed_origins):
    origins = {f'127.0.0.1:{port}': f'http://127.0.0.1:{port}', f'localhost:{port}': f'http://localhost:{port}'}
    for value in allowed_origins:
        origin = valid_origin(value)
        host = urlsplit(origin).netloc
        if host in origins and origins[host] != origin:
            raise ValueError('Conflicting origins for Host: ' + host)
        origins[host] = origin
    return origins


def handle_request(db, method, path, headers, body, port, allowed_origins=()):
    headers = {k.lower(): v for k, v in headers.items()}
    def response(code, value, content_type='application/json; charset=utf-8'):
        data = json.dumps(value, ensure_ascii=False).encode() if content_type.startswith('application/json') else value
        return code, {**SECURITY_HEADERS, 'Content-Type': content_type}, data
    host = headers.get('host', '')
    origins = origin_map(port, allowed_origins)
    if host not in origins:
        return response(403, {'error': 'Allowed Host required'})
    if method == 'POST':
        if headers.get('origin') != origins[host]:
            return response(403, {'error': 'Exact same-origin required'})
        if headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return response(415, {'error': 'application/json required'})
        if len(body) > MAX_BODY:
            return response(413, {'error': 'Body too large'})
        try:
            result = outreach.route(db, method, path, json.loads(body))
            if result is not None:
                return response(200, result)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return response(400, {'error': 'Invalid workspace fields or conflicting request'})
        except KeyError:
            return response(404, {'error': 'Workspace record not found'})
        match = re.fullmatch(r'/api/prospects/([a-z0-9][a-z0-9_-]{0,99})', path)
        if not match:
            return response(404, {'error': 'Not found'})
        try:
            p = update_prospect(db, match[1], json.loads(body))
            return response(200, {'prospect': p})
        except (ValueError, UnicodeDecodeError, RecursionError):
            return response(400, {'error': 'Invalid JSON, fields, status or suppressed prospect'})
        except KeyError:
            return response(404, {'error': 'Prospect not found'})
    if method != 'GET':
        return response(405, {'error': 'Method not allowed'})
    if path == '/api/health':
        return response(200, {'ok': True, 'prospect_count': len(list_prospects(db)), 'mode': 'local review; no sending'})
    if path == '/api/prospects':
        return response(200, {'prospects': [{**p, 'fit_indicators': fit_indicators(p)} for p in list_prospects(db)]})
    try:
        result = outreach.route(db, method, path)
        if result is not None:
            return response(200, result)
    except ValueError:
        return response(400, {'error': 'Invalid workspace query'})
    except KeyError:
        return response(404, {'error': 'Workspace record not found'})
    assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
    if path in assets and (ROOT / 'static' / assets[path][0]).is_file():
        filename, mime = assets[path]
        return response(200, (ROOT / 'static' / filename).read_bytes(), mime)
    return response(404, {'error': 'Not found'})


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def do_OPTIONS(self):
        self.respond()

    def respond(self):
        try:
            if len(self.headers.get_all('Host', [])) != 1 or len(self.headers.get_all('Origin', [])) > 1 or len(self.headers.get_all('Content-Length', [])) > 1 or len(self.headers.get_all('Content-Type', [])) > 1 or self.headers.get('Transfer-Encoding'):
                result = (400, SECURITY_HEADERS, b'Invalid headers')
            else:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > MAX_BODY:
                    result = (413, SECURITY_HEADERS, b'Invalid body size')
                else:
                    body = self.rfile.read(length)
                    result = handle_request(self.server.db, self.command, self.path, self.headers, body, self.server.server_port, allowed_origins=getattr(self.server, 'allowed_origins', ()))
        except (ValueError, TimeoutError):
            result = (400, SECURITY_HEADERS, b'Invalid request')
        except sqlite3.Error:
            result = (500, SECURITY_HEADERS, b'Database unavailable')
        code, headers, body = result
        self.send_response(code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def setup(self):
        self.request.settimeout(5)
        super().setup()

    def log_message(self, format, *args):
        pass


STATUSES = ('new', 'shortlist', 'maybe', 'reject', 'do_not_contact')
ENUMS = {'status': STATUSES, 'youtube_status': ('active', 'occasional', 'none_found', 'unknown'), 'intent': ('explicit', 'inferred', 'unknown'), 'income_status': ('self_reported', 'independently_verified', 'commercial_signal_only', 'unknown')}
TEXT_FIELDS = ('id', 'name', 'company', 'website', 'niche', 'offer', 'expertise_summary', 'opportunity_hypothesis', 'income_summary', 'notes')


def text(value, label, nonempty=True):
    if not isinstance(value, str) or len(value) > 20000 or (nonempty and not value.strip()) or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError('Invalid ' + label)
    return value


def valid_url(value):
    text(value, 'URL')
    try:
        u = urlsplit(value)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
            raise ValueError('Invalid HTTP(S) URL')
        u.port
    except (ValueError, TypeError):
        raise ValueError('Invalid HTTP(S) URL') from None
    return value


def valid_date(value, source_date=False):
    text(value, 'date')
    try:
        if source_date:
            if re.fullmatch(r'[0-9]{4}-[0-9]{2}', value):
                year, month = map(int, value.split('-'))
                datetime(year, month, 1)  # Validate only; preserve the original precision.
                return
            if not re.match(r'[0-9]{4}-[0-9]{2}-[0-9]{2}(?:$|T)', value):
                raise ValueError
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not source_date and ('T' not in value or parsed.tzinfo is None):
            raise ValueError
    except ValueError:
        raise ValueError('Dates must be ISO 8601') from None


def validate_prospect(p):
    if not isinstance(p, dict) or set(p) - set(TEXT_FIELDS) - set(ENUMS) - {'evidence', 'caveats', 'youtube_url', 'x_url', 'x_handle', 'x_status'}:
        raise ValueError('Invalid prospect fields')
    for field in TEXT_FIELDS:
        text(p.get(field), field, field != 'notes')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', p['id']):
        raise ValueError('id must be a stable lowercase slug')
    for field, values in ENUMS.items():
        if p.get(field) not in values:
            raise ValueError('Invalid ' + field)
    valid_url(p['website'])
    if p.get('youtube_url') is not None:
        valid_url(p['youtube_url'])
    if not isinstance(p.get('caveats'), list):
        raise ValueError('caveats must be a list')
    for caveat in p['caveats']:
        text(caveat, 'caveat')
    if not isinstance(p.get('evidence'), list) or not p['evidence']:
        raise ValueError('At least one citation is required')
    for e in p['evidence']:
        if not isinstance(e, dict) or set(e) - {'category', 'url', 'title', 'excerpt', 'observed_at', 'source_date'} or e.get('category') not in ('offer', 'expertise', 'income', 'youtube', 'intent', 'x_profile'):
            raise ValueError('Invalid evidence')
        valid_url(e.get('url'))
        for key in ('title', 'excerpt'):
            text(e.get(key), key)
        valid_date(e.get('observed_at'))
        if e.get('source_date') is not None:
            valid_date(e['source_date'], source_date=True)
    categories = {e['category'] for e in p['evidence']}
    x_status = p.get('x_status', 'unknown')
    if x_status not in ('verified', 'unverified', 'not_found', 'unknown'):
        raise ValueError('Invalid x_status')
    x_url, x_handle = p.get('x_url'), p.get('x_handle')
    if x_status in ('verified', 'unverified'):
        match = re.fullmatch(r'https://(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})', x_url) if isinstance(x_url, str) else None
        if not match or not isinstance(x_handle, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,15}', x_handle) or match[1].lower() != x_handle.lower():
            raise ValueError('X requires a canonical profile URL and matching handle without @')
        if x_handle.lower() in ('home', 'search', 'intent', 'messages', 'settings', 'i', 'explore', 'compose', 'login', 'signup'):
            raise ValueError('Reserved X profile path')
        if x_status == 'verified' and 'x_profile' not in categories:
            raise ValueError('Verified X identity requires primary-source x_profile evidence')
    elif x_url is not None or x_handle is not None:
        raise ValueError('Unknown/not_found X status cannot include a profile')
    if p['income_status'] in ('self_reported', 'independently_verified') and 'income' not in categories:
        raise ValueError('Revenue claims require income citations')
    if p['intent'] == 'explicit' and 'intent' not in categories:
        raise ValueError('Explicit intent requires intent citation')
    if p['youtube_status'] in ('active', 'occasional') and ('youtube' not in categories or not p.get('youtube_url')):
        raise ValueError('YouTube activity requires a channel URL and citation')
    return p


def init_db(db):
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as con:
        con.execute('CREATE TABLE IF NOT EXISTS prospects (id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, data TEXT NOT NULL)')
        outreach.migrate(con)


def identity(p):
    u = urlsplit(p['website'])
    host = u.hostname.lower().removeprefix('www.')
    path = u.path.rstrip('/')
    name = ' '.join(p['name'].casefold().split())
    return json.dumps([name, host, path], ensure_ascii=False)


def import_prospects(db, payload):
    if not isinstance(payload, dict) or set(payload) != {'prospects'} or not isinstance(payload['prospects'], list):
        raise ValueError('Expected {prospects: [...]}')
    rows = [validate_prospect(p) for p in payload['prospects']]
    init_db(db)
    seen = set()
    with sqlite3.connect(db) as con:
        for original in rows:
            p = dict(original)
            key = identity(p)
            if p['id'] in seen:
                raise ValueError('Duplicate id in batch')
            seen.add(p['id'])
            old = con.execute('SELECT data FROM prospects WHERE id = ?', (p['id'],)).fetchone()
            if old and ' '.join(json.loads(old[0])['name'].casefold().split()) != ' '.join(p['name'].casefold().split()):
                raise ValueError('Stable id belongs to another person')
            same_person = con.execute('SELECT data FROM prospects WHERE identity = ?', (key,)).fetchone()
            if old and same_person and json.loads(old[0])['id'] != json.loads(same_person[0])['id']:
                raise ValueError('Conflicting identities')
            old = old or same_person
            if old:
                prior = json.loads(old[0])
                for field in ('id', 'status', 'notes'):
                    p[field] = prior[field]
                con.execute('UPDATE prospects SET identity = ?, data = ? WHERE id = ?', (key, json.dumps(p), p['id']))
            else:
                con.execute('INSERT INTO prospects VALUES (?, ?, ?)', (p['id'], key, json.dumps(p)))
    return len(rows)


def list_prospects(db):
    init_db(db)
    with sqlite3.connect(db) as con:
        return [json.loads(row[0]) for row in con.execute('SELECT data FROM prospects ORDER BY id')]


def update_prospect(db, prospect_id, changes):
    if not isinstance(changes, dict) or not changes or set(changes) - {'status', 'notes'}:
        raise ValueError('Only status and notes can be updated')
    if 'status' in changes and changes['status'] not in STATUSES:
        raise ValueError('Invalid status')
    if 'notes' in changes:
        text(changes['notes'], 'notes', False)
    with sqlite3.connect(db) as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT data FROM prospects WHERE id = ?', (prospect_id,)).fetchone()
        if not row:
            raise KeyError(prospect_id)
        p = json.loads(row[0])
        if p['status'] == 'do_not_contact' and changes.get('status', 'do_not_contact') != 'do_not_contact':
            raise ValueError('Suppression cannot be cleared through review')
        p.update(changes)
        con.execute('UPDATE prospects SET data = ? WHERE id = ?', (json.dumps(p), prospect_id))
    return p


def fit_indicators(p):
    return {
        'cited_categories': sorted({e['category'] for e in p['evidence']}),
        'income_label': {'self_reported': 'Self-reported revenue — unverified', 'independently_verified': 'Independent revenue citation — human verification required'}.get(p['income_status'], 'Revenue unverified'),
        'intent_label': {'explicit': 'Explicit intent citation — verify context', 'inferred': 'Inferred — hypothesis, not expressed intent', 'unknown': 'Intent unknown'}[p['intent']],
    }


def export_data(db, format):
    rows = list_prospects(db)
    if format == 'json':
        return json.dumps({'prospects': rows}, ensure_ascii=False, indent=2) + '\n'
    output = io.StringIO(newline='')
    fields = list(TEXT_FIELDS) + list(ENUMS) + ['youtube_url', 'x_url', 'x_handle', 'x_status', 'evidence', 'caveats']
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for p in rows:
        cells = {}
        for field in fields:
            value = p.get(field, '')
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            value = str(value)
            if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
                value = "'" + value
            cells[field] = value
        writer.writerow(cells)
    return output.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'outreach.sqlite3')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init', help='Initialize an empty local database')
    imp = sub.add_parser('import', help='Validate and transactionally import researched JSON')
    imp.add_argument('input', type=Path)
    exp = sub.add_parser('export', help='Export JSON or spreadsheet-safe CSV')
    exp.add_argument('output', type=Path)
    exp.add_argument('--format', choices=['json', 'csv'], default='json')
    serve = sub.add_parser('serve', help='Serve local review dashboard (no sending)')
    serve.add_argument('--port', type=int, default=3016, help='Loopback port (default: 3016)')
    serve.add_argument('--allow-origin', action='append', type=valid_origin, default=[], help='Exact private proxy HTTP(S) origin; repeat for additional hosts (no trailing slash)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            init_db(args.db)
            print('Initialized', args.db)
        elif args.command == 'import':
            count = import_prospects(args.db, json.loads(args.input.read_text(encoding='utf-8')))
            print(f'Imported {count} researched records; existing review decisions preserved')
        elif args.command == 'export':
            if args.output.resolve() == args.db.resolve():
                raise ValueError('Export cannot overwrite the database')
            args.output.write_text(export_data(args.db, args.format), encoding='utf-8')
            print('Exported', args.output)
        else:
            if not 1 <= args.port <= 65535:
                raise ValueError('Invalid port')
            origin_map(args.port, args.allow_origin)  # Validate conflicts before DB writes or binding.
            init_db(args.db)
            with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
                server.db = args.db
                server.allowed_origins = tuple(args.allow_origin)
                print(f'Local review: http://127.0.0.1:{args.port} — no automated sending', flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
    except (ValueError, OSError, sqlite3.Error) as exc:
        print('Error:', exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
