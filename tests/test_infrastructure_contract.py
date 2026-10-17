"""Wire contracts from pinned upstream sources in INFRASTRUCTURE_ACCEPTANCE.md.

These local HTTP fixtures exercise the production urllib client. They are not
receipts of authenticated acceptance against an installed provider.
"""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from porchlight import infrastructure as infra


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.mode = 'ok'
        self.now = datetime.now(timezone.utc).isoformat()
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def handle_request(self):
                parsed = urlsplit(self.path)
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                payload = json.loads(body) if body else None
                query = parse_qs(parsed.query)
                test.calls.append((self.command, parsed.path, query, dict(self.headers), payload))
                komodo = parsed.path.startswith('/read/')
                authenticated = (self.headers.get('x-api-key') == 'fixture-key'
                    and self.headers.get('x-api-secret') == 'fixture-secret') if komodo else (
                    self.headers.get('Authorization') == 'fixture-token')
                code, response = 200, {}
                if test.mode == 'denied' or not authenticated:
                    code, response = 401, {'message': 'fixture-private-error'}
                elif test.mode == 'redirect':
                    code = 302
                elif test.mode == 'malformed':
                    response = {'unexpected': True}
                elif parsed.path == '/read/ListServers' and self.command == 'POST' and payload == {}:
                    response = [{'id': 'server1', 'name': 'Host', 'info': {'state': 'Ok'}}]
                elif parsed.path == '/read/ListStacks' and self.command == 'POST' and payload == {}:
                    response = [{'id': 'stack1', 'name': 'Stack', 'info': {'state': 'Running', 'server_id': 'server1'}}]
                elif parsed.path == '/read/ListAlerts' and self.command == 'POST' and payload == {'query': {'resolved': False}, 'page': 0}:
                    response = {'alerts': [{'resolved': False, 'target': {'type': 'Server', 'id': 'server1'}}], 'next_page': 1}
                elif parsed.path == '/read/ListAlerts' and self.command == 'POST' and payload == {'query': {'resolved': False}, 'page': 1}:
                    response = {'alerts': [
                        {'resolved': False, 'target': {'type': 'Server', 'id': 'server1'}},
                        {'resolved': True, 'target': {'type': 'Server', 'id': 'server1'}},
                        {'resolved': False, 'target': {'type': 'Stack', 'id': 'server1'}},
                    ], 'next_page': None}
                elif parsed.path == '/api/collections/systems/records' and self.command == 'GET':
                    page = query.get('page', [''])[0]
                    response = {'items': [] if page == '1' else [{'id': 'sys1', 'name': 'Host', 'status': 'up', 'updated': test.now}], 'totalPages': 2}
                elif parsed.path == '/api/collections/system_stats/records' and self.command == 'GET':
                    response = {'items': [{'created': test.now, 'type': '1m', 'stats': {'cpu': 0, 'mp': 36.5, 'dp': 50}}], 'totalPages': 1}
                else:
                    code = 400
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                if code == 302:
                    self.send_header('Location', '/credential-sink')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config = Path(self.tmp.name)
        base = f'http://127.0.0.1:{self.server.server_port}'
        self.env = config / 'infrastructure.env'
        self.env.write_text(f'BESZEL_URL={base}\nBESZEL_TOKEN=fixture-token\nKOMODO_URL={base}\nKOMODO_API_KEY=fixture-key\nKOMODO_API_SECRET=fixture-secret\n')
        (config / 'infrastructure.json').write_text(json.dumps({
            'hosts': [{'id': 'host', 'beszel_id': 'sys1', 'komodo_id': 'server1'}],
            'services': [{'id': 'svc', 'host': 'host', 'komodo_stack_id': 'stack1'}],
        }))
        self.monitor = infra.InfrastructureMonitor(config)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_komodo_paths_parameter_bodies_headers_and_alert_pagination(self):
        self.monitor.collect()
        calls = [call for call in self.calls if call[1].startswith('/read')]
        self.assertEqual([(method, path, payload) for method, path, _, _, payload in calls], [
            ('POST', '/read/ListServers', {}), ('POST', '/read/ListStacks', {}),
            ('POST', '/read/ListAlerts', {'query': {'resolved': False}, 'page': 0}),
            ('POST', '/read/ListAlerts', {'query': {'resolved': False}, 'page': 1}),
        ])
        for _, _, query, headers, _ in calls:
            self.assertEqual(query, {})
            self.assertEqual(headers['X-Api-Key'], 'fixture-key')
            self.assertEqual(headers['X-Api-Secret'], 'fixture-secret')
            self.assertEqual(headers['Content-Type'], 'application/json')
            self.assertNotIn('Authorization', headers)
        result = self.monitor.snapshot()
        self.assertEqual(result['providers']['komodo']['status'], 'ok')
        self.assertEqual(result['hosts'][0]['management']['active_alerts'], 2)
        self.assertEqual(result['services'][0]['deployment']['state'], 'Running')

    def test_beszel_token_queries_pagination_sample_timestamp_and_metrics(self):
        self.monitor.collect()
        calls = [call for call in self.calls if call[1].startswith('/api/collections')]
        self.assertEqual(len(calls), 3)
        for method, _, _, headers, payload in calls:
            self.assertEqual(method, 'GET')
            self.assertIsNone(payload)
            self.assertEqual(headers['Authorization'], 'fixture-token')
            self.assertNotIn('X-Api-Secret', headers)
        self.assertEqual(calls[0][2], {'page': ['1'], 'perPage': ['100'], 'fields': ['id,name,status,updated']})
        self.assertEqual(calls[1][2]['page'], ['2'])
        self.assertEqual(calls[2][2], {'perPage': ['1'], 'sort': ['-created'],
            'filter': ['system="sys1" && type="1m"'], 'fields': ['created,stats,type']})
        telemetry = self.monitor.snapshot()['hosts'][0]['telemetry']
        self.assertEqual(telemetry['observed_at'], self.now)
        self.assertEqual(telemetry['metrics'], {'cpu_pct': 0, 'memory_pct': 36.5, 'disk_pct': 50})

    def test_authentication_failure_is_redacted_and_cached_samples_expire(self):
        self.monitor.collect()
        before = self.monitor.snapshot()['hosts'][0]
        self.mode = 'denied'
        self.monitor.collect()
        result = self.monitor.snapshot()
        self.assertTrue(all(p['status'] == 'error' for p in result['providers'].values()))
        self.assertEqual(result['hosts'][0]['telemetry'], before['telemetry'])
        self.assertEqual(result['hosts'][0]['management'], before['management'])
        for secret in ('fixture-key', 'fixture-secret', 'fixture-token', 'fixture-private-error'):
            self.assertNotIn(secret, json.dumps(result))
        with patch.object(infra.time, 'time', return_value=infra.time.time() + 200):
            expired = self.monitor.snapshot()
        self.assertEqual(expired['hosts'][0]['status'], 'unknown')
        self.assertTrue(expired['hosts'][0]['telemetry_stale'])
        self.assertTrue(expired['hosts'][0]['management_stale'])
        self.assertTrue(expired['services'][0]['deployment_stale'])

    def test_invalid_responses_do_not_create_healthy_observations(self):
        for mode in ('denied', 'malformed'):
            with self.subTest(mode=mode):
                self.mode = mode
                self.monitor.collect()
                result = self.monitor.snapshot()
                self.assertTrue(all(p['status'] == 'error' for p in result['providers'].values()))
                self.assertEqual(result['hosts'][0]['status'], 'unknown')
                self.assertFalse(result['services'][0]['deployment'])

    def test_provider_redirects_never_forward_credentials(self):
        self.mode = 'redirect'
        self.monitor.collect()
        self.assertEqual([call[1] for call in self.calls], [
            '/api/collections/systems/records', '/read/ListServers'])
        self.assertTrue(all(p['status'] == 'error' for p in self.monitor.snapshot()['providers'].values()))

    def test_missing_credentials_do_not_send_requests(self):
        self.env.write_text('')
        self.monitor.collect()
        self.assertEqual(self.calls, [])
        self.assertTrue(all(p['status'] == 'unconfigured' for p in self.monitor.snapshot()['providers'].values()))


if __name__ == '__main__':
    unittest.main()
