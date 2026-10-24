import errno
import tempfile
import unittest
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import Mock, patch

from discord_archive.listener import bind_server, read_listener, save_listener, sync_private_proxy


class ListenerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_collision_retries_only_address_in_use(self):
        server = Mock()
        factory = Mock(side_effect=[OSError(errno.EADDRINUSE, 'busy'), server])
        self.assertIs(bind_server(factory, self.root, '127.0.0.1', 8765, None), server)
        self.assertEqual([call.args[0] for call in factory.call_args_list],
                         [('127.0.0.1', 8765), ('127.0.0.1', 8766)])
        factory = Mock(side_effect=PermissionError(errno.EACCES, 'denied'))
        with self.assertRaises(PermissionError):
            bind_server(factory, self.root, '127.0.0.1', 8765, None)
        self.assertEqual(factory.call_count, 1)

    def test_saved_port_is_sticky_and_root_scoped(self):
        save_listener(self.root, '127.0.0.1', 8765, 8768)
        factory = Mock()
        bind_server(factory, self.root, '127.0.0.1', 8765, None)
        self.assertEqual(factory.call_args.args[0], ('127.0.0.1', 8768))
        self.assertEqual((self.root/'data/listener.json').stat().st_mode & 0o777, 0o600)
        target = self.root/'other/data/listener.json'
        target.parent.mkdir(parents=True)
        target.write_bytes((self.root/'data/listener.json').read_bytes())
        self.assertEqual(read_listener(self.root/'other'), {})

    def test_port_exhaustion_and_invalid_port(self):
        factory = Mock(side_effect=OSError(errno.EADDRINUSE, 'busy'))
        with self.assertRaisesRegex(RuntimeError, '100'):
            bind_server(factory, self.root, '127.0.0.1', 8765, None)
        self.assertEqual(factory.call_count, 100)
        with self.assertRaises(ValueError):
            bind_server(factory, self.root, '127.0.0.1', 65536, None)

    def test_real_occupied_listener_remains_alive_and_fallback_binds(self):
        occupied = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
        self.addCleanup(occupied.server_close)
        preferred = occupied.server_address[1]
        server = bind_server(ThreadingHTTPServer, self.root, '127.0.0.1', preferred, BaseHTTPRequestHandler)
        self.addCleanup(server.server_close)
        self.assertNotEqual(server.server_address[1], preferred)
        self.assertGreaterEqual(occupied.fileno(), 0)

    def test_proxy_sync_only_changes_matching_managed_route(self):
        import json
        origin = 'https://archive.example.ts.net'
        state = {'Web': {'archive.example.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8765'}}}}}
        with patch('subprocess.run', side_effect=[Mock(returncode=0, stdout=json.dumps(state)), Mock(returncode=0)]) as run:
            self.assertIsNone(sync_private_proxy(origin, 'http://127.0.0.1:8766', 'http://127.0.0.1:8765'))
            self.assertEqual(run.call_args.args[0], ['tailscale', 'serve', '--bg', '--https=443', 'http://127.0.0.1:8766'])
        with patch('subprocess.run', return_value=Mock(returncode=0, stdout=json.dumps(state))) as run:
            self.assertIsNotNone(sync_private_proxy(origin, 'http://127.0.0.1:8766', 'http://127.0.0.1:9999'))
            self.assertEqual(run.call_count, 1)
        with patch('subprocess.run', side_effect=[Mock(returncode=0, stdout=json.dumps(state)), Mock(returncode=1)]) as run:
            self.assertIn('尚未同步', sync_private_proxy(origin, 'http://127.0.0.1:8766', 'http://127.0.0.1:8765'))
