from concurrent.futures import ThreadPoolExecutor
from functools import partial
import os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from porchlight import infrastructure as infra


class ProbeHandler(BaseHTTPRequestHandler):
    paths = []

    def do_GET(self):
        self.paths.append(self.path)
        code, body = {
            '/login': (200, b'<html>Sign in</html>'),
            '/ready': (200, b'READY'),
            '/auth': (401, b'Unauthorized'),
            '/broken': (503, b'Unavailable'),
            '/host-rejected': (400, b'Bad host'),
            '/websocket': (426, b'Upgrade required'),
            '/redirect': (302, b''),
        }.get(self.path, (404, b''))
        self.send_response(code)
        if code == 302:
            self.send_header('Location', '/ready')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), ProbeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def probe(self, path, **extra):
        return infra.service_probe({'id': 'svc', 'host': 'host', 'probe': {'url': self.base + path, **extra}}, 'test')

    def test_login_and_auth_are_reachable_but_not_healthy(self):
        for path in ('/login', '/auth'):
            with self.subTest(path=path):
                result = self.probe(path)
                self.assertEqual(result['reachability'], 'reachable')
                self.assertEqual(result['health'], 'unknown')

    def test_readiness_requires_success_and_marker(self):
        self.assertEqual(self.probe('/ready', kind='readiness', expected_text='READY')['health'], 'healthy')
        self.assertEqual(self.probe('/login', kind='readiness', expected_text='READY')['health'], 'degraded')
        self.assertEqual(self.probe('/auth', kind='readiness', expected_text='READY')['health'], 'unknown')
        self.assertEqual(self.probe('/broken')['health'], 'degraded')

    def test_protocol_and_host_rejections_do_not_fabricate_application_failure(self):
        for path in ('/host-rejected', '/websocket'):
            with self.subTest(path=path):
                result = self.probe(path)
                self.assertEqual(result['reachability'], 'reachable')
                self.assertEqual(result['health'], 'unknown')

    def test_redirect_is_not_followed(self):
        ProbeHandler.paths.clear()
        status, body = infra.request(self.base + '/redirect', headers={'Authorization': 'fixture-secret'})
        self.assertEqual(status, 302)
        self.assertEqual(ProbeHandler.paths, ['/redirect'])
        self.assertEqual(self.probe('/redirect', kind='readiness', expected_text='READY')['health'], 'unknown')

    def test_failed_probe_has_no_fabricated_observation(self):
        with patch.object(infra, 'request', side_effect=OSError('fixture secret must not leak')):
            result = self.probe('/ready')
        self.assertEqual(result['reachability'], 'unreachable')
        self.assertEqual(result['health'], 'unknown')
        self.assertIsNone(result['observed_at'])
        self.assertNotIn('secret', json.dumps(result))


class RegistryTest(unittest.TestCase):
    def test_registry_rejects_bad_shapes_and_references(self):
        valid = {'hosts': [{'id': 'host'}], 'services': [{'id': 'svc', 'host': 'host'}]}
        bad = [
            {'hosts': [None]}, {'hosts': [{'id': 1}]},
            {'hosts': [{'id': 'x'}, {'id': 'x'}]},
            {**valid, 'services': [{'id': 'svc', 'host': 'missing'}]},
            {**valid, 'services': [{'id': 'svc', 'host': 'host', 'probe': []}]},
            {**valid, 'services': [{'id': 'svc', 'host': 'host', 'probe': {'kind': 'readiness'}}]},
            {'hosts': [{'id': 'host', 'links': [{'url': 'javascript:alert(1)'}]}]},
            {'hosts': [{'id': 'host', 'links': [None]}]},
            {**valid, 'interval_seconds': 1},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'registry.json'
            for value in bad:
                with self.subTest(value=value):
                    path.write_text(json.dumps(value))
                    with self.assertRaises(ValueError):
                        infra.load_registry(path)
            path.write_text(json.dumps(valid))
            self.assertEqual(len(infra.load_registry(path)['services']), 1)

    def test_public_and_credential_urls_are_rejected_for_probes(self):
        for url in ('http://user:secret@127.0.0.1', 'http://127.0.0.1?token=secret', 'file:///etc/passwd', 'http://127.0.0.1\n'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                infra.safe_url(url)
        with self.assertRaises(ValueError):
            infra.safe_url('http://8.8.8.8', network=True)
        with self.assertRaises(ValueError):
            infra.safe_url('http://169.254.169.254', network=True)
        self.assertEqual(infra.safe_url('http://100.99.9.110:9120', network=True), 'http://100.99.9.110:9120')

    def test_ambiguous_provider_names_never_select_a_host(self):
        self.assertIsNone(infra.unique_match([{'id': 'a', 'name': 'same'}, {'id': 'b', 'name': 'same'}], 'same'))
        self.assertEqual(infra.unique_match([{'id': 'a', 'name': 'same'}], 'a')['id'], 'a')


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name)
        self.now = datetime.now(timezone.utc).isoformat()
        self.registry = {'hosts': [{'id': 'host', 'name': 'Test host', 'beszel_id': 'sys1', 'komodo_id': 'server1'}],
                         'services': [{'id': 'svc', 'host': 'host', 'komodo_stack_id': 'stack1'}]}
        (self.config / 'infrastructure.json').write_text(json.dumps(self.registry))
        (self.config / 'infrastructure.env').write_text('BESZEL_URL=http://127.0.0.1:8090\nBESZEL_TOKEN=beszel-fixture-secret\nKOMODO_URL=http://127.0.0.1:9120\nKOMODO_API_KEY=fixture-key\nKOMODO_API_SECRET=komodo-fixture-secret\n')
        self.calls = []
        self.provider_failed = False
        self.server_state = 'Ok'
        self.monitor = infra.InfrastructureMonitor(self.config, fetch_json=self.fetch)

    def fetch(self, url, **options):
        self.calls.append((url, options))
        if self.provider_failed:
            raise OSError('backend private credential text')
        if url.endswith('/systems/records'):
            return {'items': [{'id': 'sys1', 'name': 'Test host', 'status': 'up', 'updated': self.now}], 'totalPages': 1}
        if url.endswith('/system_stats/records'):
            return {'items': [{'created': self.now, 'type': '1m', 'stats': {'cpu': 0, 'mp': 36.5, 'dp': None}}]}
        kind = url.rsplit('/', 1)[-1]
        if kind == 'ListServers':
            return [{'id': 'server1', 'name': 'Test host', 'info': {'state': self.server_state}}]
        if kind == 'ListStacks':
            return [{'id': 'stack1', 'info': {'state': 'Running'}}]
        if kind == 'ListAlerts':
            return {'alerts': [{'resolved': False, 'target': {'type': 'Server', 'id': 'server1'}}], 'next_page': None}
        self.fail('unexpected API request')

    def test_summary_uses_sample_time_and_hides_credentials(self):
        self.monitor.collect()
        result = self.monitor.snapshot()
        host = result['hosts'][0]
        self.assertEqual(host['status'], 'up')
        self.assertEqual(host['telemetry']['metrics'], {'cpu_pct': 0, 'memory_pct': 36.5, 'disk_pct': None})
        self.assertEqual(host['telemetry']['observed_at'], self.now)
        self.assertEqual(host['management']['active_alerts'], 1)
        self.assertEqual(result['services'][0]['deployment']['state'], 'Running')
        self.assertEqual(result['services'][0]['health'], 'unknown')
        self.assertNotIn('fixture-secret', json.dumps(result))
        self.assertNotIn('fixture-key', json.dumps(result))
        request = next(options for url, options in self.calls if url.endswith('/read/ListServers'))
        self.assertEqual(request['headers']['x-api-secret'], 'komodo-fixture-secret')

    def test_provider_failure_preserves_timestamps_then_expires(self):
        self.monitor.collect()
        before = self.monitor.snapshot()['hosts'][0]['management']['observed_at']
        self.provider_failed = True
        self.monitor.collect()
        current = self.monitor.snapshot()
        self.assertEqual(current['providers']['komodo']['status'], 'error')
        self.assertEqual(current['hosts'][0]['management']['observed_at'], before)
        with patch.object(infra.time, 'time', return_value=infra.time.time() + 200):
            expired = self.monitor.snapshot()
        self.assertEqual(expired['hosts'][0]['status'], 'unknown')
        self.assertTrue(expired['hosts'][0]['telemetry_stale'])
        self.assertTrue(expired['services'][0]['deployment_stale'])
        self.assertNotIn('private credential', json.dumps(current))

    def test_successful_missing_mapping_discards_cached_health(self):
        self.monitor.collect()
        with patch.object(self.monitor, '_beszel', return_value=({}, {"status": "ok"})), \
             patch.object(self.monitor, '_komodo', return_value=({}, {}, {"status": "ok"})):
            self.monitor.collect()
        snapshot = self.monitor.snapshot()
        self.assertEqual(snapshot['hosts'][0]['status'], 'unknown')
        self.assertEqual(snapshot['hosts'][0]['telemetry'], {})
        self.assertEqual(snapshot['hosts'][0]['management'], {})
        self.assertFalse(snapshot['services'][0]['deployment'])

    def test_registry_remap_does_not_inherit_previous_host_or_stack(self):
        self.monitor.collect()
        self.registry['hosts'][0].update(beszel_id='another-system', komodo_id='another-server')
        self.registry['services'][0]['komodo_stack_id'] = 'another-stack'
        (self.config / 'infrastructure.json').write_text(json.dumps(self.registry))
        self.provider_failed = True
        self.monitor.collect()
        snapshot = self.monitor.snapshot()
        self.assertEqual(snapshot['hosts'][0]['status'], 'unknown')
        self.assertEqual(snapshot['hosts'][0]['telemetry'], {})
        self.assertEqual(snapshot['hosts'][0]['management'], {})
        self.assertFalse(snapshot['services'][0]['deployment'])

    def test_provider_endpoint_change_invalidates_old_samples(self):
        self.monitor.collect()
        path = self.config / 'infrastructure.env'
        path.write_text(path.read_text().replace('127.0.0.1', '127.0.0.2'))
        self.provider_failed = True
        self.monitor.collect()
        snapshot = self.monitor.snapshot()
        self.assertEqual(snapshot['hosts'][0]['status'], 'unknown')
        self.assertFalse(snapshot['services'][0]['deployment'])

    def test_changed_probe_does_not_inherit_last_response(self):
        self.registry['services'][0]['probe'] = {'url': 'http://127.0.0.1:9001'}
        (self.config / 'infrastructure.json').write_text(json.dumps(self.registry))
        with patch.object(infra, 'request', return_value=(200, b'login')):
            self.monitor.collect()
        self.assertIsNotNone(self.monitor.snapshot()['services'][0]['last_success_at'])
        self.registry['services'][0]['probe']['url'] = 'http://127.0.0.1:9002'
        (self.config / 'infrastructure.json').write_text(json.dumps(self.registry))
        with patch.object(infra, 'request', side_effect=OSError('unreachable')):
            self.monitor.collect()
        self.assertIsNone(self.monitor.snapshot()['services'][0]['last_success_at'])

    def test_disabled_server_is_maintenance(self):
        self.server_state = 'Disabled'
        self.monitor.collect()
        self.assertEqual(self.monitor.snapshot()['hosts'][0]['status'], 'maintenance')

    def test_invalid_registry_marks_previous_data_unavailable(self):
        self.monitor.collect()
        (self.config / 'infrastructure.json').write_text('{"hosts":[null]}')
        self.monitor.collect()
        snapshot = self.monitor.snapshot()
        self.assertTrue(snapshot['collector_stale'])
        self.assertEqual(snapshot['hosts'][0]['status'], 'unknown')

    def test_missing_configuration_makes_no_network_requests(self):
        (self.config / 'infrastructure.json').unlink()
        (self.config / 'infrastructure.env').unlink()
        self.monitor.collect()
        self.assertFalse(self.monitor.snapshot()['configured'])
        self.assertEqual(self.calls, [])

    def test_future_timestamp_and_invalid_metrics_are_unknown(self):
        self.assertIsNone(infra.age_seconds((datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()))
        for value in (True, -1, 101, float('nan'), '25'):
            self.assertIsNone(infra.pct(value))


class InfrastructureApiTest(unittest.TestCase):
    def test_parallel_summary_requests_do_not_expose_credentials(self):
        from porchlight.config import load_config
        from porchlight.web import PorchlightHTTPServer, PorchlightHTTPRequestHandler
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"MUSTER_MOCK_ROOT": tmp}, clear=False):
                config = load_config()
            config.config_dir.mkdir(parents=True, exist_ok=True)
            (config.config_dir / "infrastructure.env").write_text("BESZEL_TOKEN=api-private-fixture-secret\n")
            class QuietHandler(PorchlightHTTPRequestHandler):
                def log_message(self, *args):
                    pass
            server = PorchlightHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=tmp), config, False)
            server.infrastructure.collect()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def fetch(_):
                    with urlopen(f'http://127.0.0.1:{server.server_port}/api/infrastructure', timeout=5) as response:
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                        return json.load(response)
                with ThreadPoolExecutor(max_workers=24) as executor:
                    results = list(executor.map(fetch, range(48)))
                self.assertEqual(len(results), 48)
                self.assertTrue(all(not result['configured'] for result in results))
                self.assertNotIn('api-private-fixture-secret', json.dumps(results))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class InfrastructureRenderingTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for frontend behavior checks')
    def test_cached_health_expires_and_links_are_escaped(self):
        script = r'''
const vm = require('vm');
const fs = require('fs');
const context = vm.createContext({URL, Date, console,
  fetch: () => new Promise(() => {}),
  window: {location: {hash: "#/infrastructure"}, localStorage: {getItem: () => null}, matchMedia: () => ({matches:false, addEventListener(){}}), addEventListener(){}},
  document: {documentElement:{dataset:{}}, querySelectorAll:()=>[], addEventListener(){}}});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const result = vm.runInContext(`
state.infrastructure = ${process.argv[2]};
renderInfrastructure()`, context);
process.stdout.write(result);
'''
        now = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        snapshot = {'generated_at': now, 'stale_seconds': 120, 'hosts': [{'id': 'h', 'name': '<Host>', 'status': 'up',
            'management': {'status': 'up', 'observed_at': old}, 'telemetry': {'observed_at': old, 'status_observed_at': old,
            'status': 'up', 'metrics': {'cpu_pct': 12}}, 'links': [{'url': 'javascript:alert(1)', 'label': 'bad'}]}],
            'services': [{'host': 'h', 'name': '<Service>', 'health': 'healthy', 'reachability': 'reachable', 'checked_at': old}]}
        result = subprocess.run(['node', '-e', script, str(ROOT / 'src/porchlight/webroot/app.js'), json.dumps(snapshot)],
                                check=True, text=True, capture_output=True).stdout
        self.assertIn('&lt;Host&gt;', result)
        self.assertIn('&lt;Service&gt;', result)
        self.assertNotIn('infra-badge good', result)
        self.assertNotIn('javascript:', result)
        self.assertNotIn('12.0%', result)


if __name__ == '__main__':
    unittest.main()
