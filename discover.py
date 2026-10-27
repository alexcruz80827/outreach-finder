#!/usr/bin/env python3
"""Collect Exa discovery evidence; search hits are NOT qualified prospects.

Usage: python3 discover.py --query 'AI founders revenue' --limit 5 --output data/discovery.json
Or: python3 discover.py --preset ai-founders --limit 5 --output data/discovery.json

Requires an already configured mcporter Exa connection. Source cost and rate limits
are unknown; each query makes one request, with a 90-second timeout and no retries.
The preset makes three requests. No X access is proven. No cookies, credential-file
reads, account creation, qualification, or model-generated claims occur here.

Output appends raw query records and provider bytes, with URL-only candidates
marked unverified_search_hit. Evidence references are zero-based indexes into runs;
raw_response and stderr are UTF-8 decoded with replacement and unchanged newlines;
raw_response_base64 and stderr_base64 preserve the exact original bytes, including
partial output on timeout. Snippets are never synthesized. This is
NOT the app's qualified-prospect import schema: research original sources, verify
claims, and prepare a reviewed import separately. Existing records survive repeats;
URLs are deduplicated by exact string, without speculative normalization. A local
.lock sidecar serializes writers, and atomic replacement prevents partial JSON.
Unrecognized/empty responses are errors requiring inspection, not successful
zero-result searches. Exit codes: 0 collected, 1 provider/storage failure, 2 usage.
"""
import argparse
import base64
import sys
import datetime
import fcntl
import json
import os
from pathlib import Path
import tempfile
import re
import subprocess
from urllib.parse import urlsplit


def validate(query, limit):
    if not isinstance(query, str) or not query.strip() or len(query) > 500 or any(ord(c) < 32 for c in query):
        raise ValueError('query must be nonblank, single-line, at most 500 characters')
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('limit must be an integer from 1 to 10')


def text(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else (value or '')


def collect(query, limit):
    validate(query, limit)
    record = {
        'query': query, 'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'limit': limit, 'status': 'error', 'error': None,
        'raw_response': '', 'raw_response_base64': '',
        'stderr': '', 'stderr_base64': '', 'urls': [],
    }
    try:
        result = subprocess.run(
            ['mcporter', 'call', 'exa.web_search_exa', 'query=' + query, 'numResults=' + str(limit)],
            capture_output=True, timeout=90, shell=False,
        )
        record['raw_response'] = text(result.stdout)
        record['raw_response_base64'] = base64.b64encode(result.stdout).decode('ascii')
        record['stderr'] = text(result.stderr)
        record['stderr_base64'] = base64.b64encode(result.stderr).decode('ascii')
        record['returncode'] = result.returncode
        for url in re.findall(r'^URL:[ \t]*(https?://\S+)', record['raw_response'], re.MULTILINE):
            try:
                valid = urlsplit(url).hostname is not None
            except ValueError:
                valid = False
            if valid and url not in record['urls']:
                record['urls'].append(url)
        if result.returncode:
            record['error'] = 'mcporter exited {}: {}'.format(record['returncode'], record['stderr'] or record['raw_response'])
        elif not record['urls']:
            record['error'] = 'Invalid or empty response: no recognizable URL result blocks; inspect raw_response'
        else:
            record['status'] = 'success'
    except subprocess.TimeoutExpired as exc:
        record.update(raw_response=text(exc.stdout), stderr=text(exc.stderr), error='Timeout after 90 seconds')
        record['raw_response_base64'] = base64.b64encode(exc.stdout or b'').decode('ascii')
        record['stderr_base64'] = base64.b64encode(exc.stderr or b'').decode('ascii')
    except OSError as exc:
        record['error'] = 'mcporter missing or could not execute: ' + str(exc)
    return record


def append_records(output, records):
    """Append evidence atomically under a local advisory writer lock."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(str(output) + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        document = {'schema_version': 1, 'purpose': 'discovery_only_not_qualified_import', 'runs': [], 'candidates': []}
        if output.exists():
            document = json.loads(output.read_text(encoding='utf-8'))
            if (not isinstance(document, dict) or document.get('schema_version') != 1
                    or document.get('purpose') != 'discovery_only_not_qualified_import'
                    or not isinstance(document.get('runs'), list)):
                raise ValueError('Existing output is not a discovery evidence document; refusing overwrite')
        document['runs'].extend(records)
        candidates = {}
        for index, record in enumerate(document['runs']):
            if record['status'] != 'success':
                continue
            for url in record['urls']:
                candidate = candidates.setdefault(url, {'url': url, 'status': 'unverified_search_hit', 'evidence_run_indexes': []})
                if index not in candidate['evidence_run_indexes']:
                    candidate['evidence_run_indexes'].append(index)
        document['candidates'] = list(candidates.values())
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as handle:
                temporary = handle.name
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return document


AI_FOUNDER_QUERIES = (
    'AI startup founder product monthly revenue YouTube interview',
    'AI automation agency founder monthly revenue YouTube founder',
    '"AI" "founder" "YouTube" "hiring" "editor"',
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--query', help='Single-line query, 1 to 500 characters')
    source.add_argument('--preset', choices=['ai-founders'], help='Three fixed discovery queries, not prospect qualification')
    parser.add_argument('--limit', type=int, default=5, help='Requested results per query, 1 to 10 (default: 5)')
    parser.add_argument('--output', type=Path, default=Path('data/discovery.json'))
    args = parser.parse_args(argv)
    queries = [args.query] if args.query is not None else AI_FOUNDER_QUERIES
    try:
        for query in queries:
            validate(query, args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    failures = 0
    try:
        # Validate existing storage before making requests; each completed query is
        # persisted immediately so later interruption cannot lose earlier evidence.
        append_records(args.output, [])
        for query in queries:
            record = collect(query, args.limit)
            document = append_records(args.output, [record])
            failures += record['status'] != 'success'
            if record['error']:
                print(record['error'], file=sys.stderr)
        print(json.dumps({'output': str(args.output), 'purpose': document['purpose'],
                          'new_runs': len(queries), 'errors': failures,
                          'total_runs': len(document['runs']),
                          'unverified_search_hits': len(document['candidates'])}))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Discovery storage error: ' + str(exc), file=sys.stderr)
        return 1
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
