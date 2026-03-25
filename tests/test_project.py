import io
import json
import os
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trae_custom_endpoint_patch.cli import MENU_STATE_ENV, main as cli_main
from trae_custom_endpoint_patch.patcher import (
    APP_ROOT_ENV,
    BUNDLE_RELATIVE_PATH,
    SETTINGS_FILE_ENV,
    STRATEGY_KEY,
    discover_app_root,
    discover_app_roots,
    discover_settings_file,
    discover_settings_files,
    doctor,
    ensure_local_agent_strategy,
    list_backups,
    patch_bundle,
    resolve_app_root,
    resolve_settings_file,
    restore_bundle,
    restore_settings,
    unique_paths,
)
from trae_custom_endpoint_patch.relay import normalize_chat_body, relay_status, run_from_args as run_relay_from_args, stop_relay


def sample_bundle_text():
    bang = chr(33)
    return f'let eDg=e=>e?.scope===v9.BYTEDANCE,{bang}n&&i&&sm().createElement(eDf,{{ref:o,container:s}})'


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


class PatcherTests(unittest.TestCase):
    def setUp(self):
        self.state_dir = tempfile.TemporaryDirectory()
        self.state_file = str(Path(self.state_dir.name) / 'menu-state.json')
        self.state_env = patch.dict(os.environ, {MENU_STATE_ENV: self.state_file}, clear=False)
        self.state_env.start()

    def tearDown(self):
        self.state_env.stop()
        self.state_dir.cleanup()

    def test_patch_bundle_applies_rules(self):
        bang = chr(33)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / BUNDLE_RELATIVE_PATH
            bundle.parent.mkdir(parents=True, exist_ok=True)
            bundle.write_text(sample_bundle_text(), encoding='utf-8')
            result = patch_bundle(root)
            text = bundle.read_text(encoding='utf-8')
            self.assertTrue(result['changed'])
            self.assertIn(f'let eDg=e=>{bang}1,', text)
            self.assertIn('i&&sm().createElement(eDf,{ref:o,container:s})', text)

    def test_patch_bundle_creates_backup_and_can_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / BUNDLE_RELATIVE_PATH
            bundle.parent.mkdir(parents=True, exist_ok=True)
            original = sample_bundle_text()
            bundle.write_text(original, encoding='utf-8')

            result = patch_bundle(root)
            backups = list_backups(app_root=root, settings_file=root / 'settings.json')

            self.assertTrue(result['backup'])
            self.assertEqual(len(backups['bundle']), 1)

            restored = restore_bundle(root)
            self.assertTrue(restored['restored'])
            self.assertEqual(bundle.read_text(encoding='utf-8'), original)

    def test_ensure_local_agent_strategy_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = root / 'settings.json'
            settings.write_text(json.dumps({STRATEGY_KEY: 'remote'}), encoding='utf-8')

            result = ensure_local_agent_strategy(settings)
            backups = list_backups(app_root=root, settings_file=settings)
            data = json.loads(settings.read_text(encoding='utf-8'))

            self.assertTrue(result['changed'])
            self.assertEqual(data[STRATEGY_KEY], 'local')
            self.assertEqual(len(backups['settings']), 1)

            restored = restore_settings(settings)
            self.assertTrue(restored['restored'])
            restored_data = json.loads(settings.read_text(encoding='utf-8'))
            self.assertEqual(restored_data[STRATEGY_KEY], 'remote')

    def test_doctor_and_cli_doctor_report_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / BUNDLE_RELATIVE_PATH
            settings = root / 'settings.json'
            bundle.parent.mkdir(parents=True, exist_ok=True)
            bundle.write_text(sample_bundle_text(), encoding='utf-8')
            settings.write_text(json.dumps({STRATEGY_KEY: 'remote'}), encoding='utf-8')

            patch_bundle(root)
            ensure_local_agent_strategy(settings)

            payload = doctor(app_root=root, settings_file=settings)
            self.assertTrue(payload['ready'])
            self.assertTrue(payload['bundle_ready'])
            self.assertTrue(payload['settings_ready'])

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cli_main(['doctor', '--app-root', str(root), '--settings-file', str(settings)])

            self.assertEqual(exit_code, 0)
            cli_payload = json.loads(output.getvalue())
            self.assertTrue(cli_payload['ready'])

    def test_discover_app_root_supports_trae_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            trae_root = base / 'Trae'
            bundle = trae_root / BUNDLE_RELATIVE_PATH
            bundle.parent.mkdir(parents=True, exist_ok=True)
            bundle.write_text(sample_bundle_text(), encoding='utf-8')

            discovered = discover_app_root([base / 'Trae CN', trae_root])
            self.assertEqual(discovered, trae_root)

    def test_discover_settings_file_supports_trae_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            settings = base / 'Trae' / 'User' / 'settings.json'
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text('{}', encoding='utf-8')

            discovered = discover_settings_file([base / 'Trae CN' / 'User' / 'settings.json', settings])
            self.assertEqual(discovered, settings)

    def test_discover_all_helpers_return_every_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            trae_cn_root = base / 'Trae CN'
            trae_root = base / 'Trae'
            for root in (trae_cn_root, trae_root):
                bundle = root / BUNDLE_RELATIVE_PATH
                bundle.parent.mkdir(parents=True, exist_ok=True)
                bundle.write_text(sample_bundle_text(), encoding='utf-8')

            trae_cn_settings = base / 'Trae CN' / 'User' / 'settings.json'
            trae_settings = base / 'Trae' / 'User' / 'settings.json'
            for settings in (trae_cn_settings, trae_settings):
                settings.parent.mkdir(parents=True, exist_ok=True)
                settings.write_text('{}', encoding='utf-8')

            roots = discover_app_roots([trae_cn_root, trae_root])
            settings_files = discover_settings_files([trae_cn_settings, trae_settings])

            self.assertEqual(roots, [trae_cn_root, trae_root])
            self.assertEqual(settings_files, [trae_cn_settings, trae_settings])

    def test_unique_paths_collapses_windows_case_only_duplicates(self):
        candidates = [Path('D:/soft/Trae CN'), Path('D:/Soft/Trae CN'), Path('D:/soft/Trae')]
        self.assertEqual(unique_paths(candidates), [Path('D:/soft/Trae CN'), Path('D:/soft/Trae')])

    def test_environment_variable_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'Trae'
            bundle = root / BUNDLE_RELATIVE_PATH
            settings = Path(tmp) / 'Trae' / 'User' / 'settings.json'
            bundle.parent.mkdir(parents=True, exist_ok=True)
            settings.parent.mkdir(parents=True, exist_ok=True)
            bundle.write_text(sample_bundle_text(), encoding='utf-8')
            settings.write_text('{}', encoding='utf-8')

            previous_root = os.environ.get(APP_ROOT_ENV)
            previous_settings = os.environ.get(SETTINGS_FILE_ENV)
            os.environ[APP_ROOT_ENV] = str(root)
            os.environ[SETTINGS_FILE_ENV] = str(settings)
            try:
                self.assertEqual(resolve_app_root(), root)
                self.assertEqual(resolve_settings_file(), settings)
            finally:
                if previous_root is None:
                    os.environ.pop(APP_ROOT_ENV, None)
                else:
                    os.environ[APP_ROOT_ENV] = previous_root
                if previous_settings is None:
                    os.environ.pop(SETTINGS_FILE_ENV, None)
                else:
                    os.environ[SETTINGS_FILE_ENV] = previous_settings

    def test_cli_menu_patch_all_with_explicit_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / BUNDLE_RELATIVE_PATH
            settings = root / 'settings.json'
            bundle.parent.mkdir(parents=True, exist_ok=True)
            bundle.write_text(sample_bundle_text(), encoding='utf-8')
            settings.write_text(json.dumps({STRATEGY_KEY: 'remote'}), encoding='utf-8')

            output = io.StringIO()
            with patch('builtins.input', side_effect=['1', 'q']):
                with redirect_stdout(output):
                    exit_code = cli_main(['menu', '--app-root', str(root), '--settings-file', str(settings)])

            self.assertEqual(exit_code, 0)
            payload = doctor(app_root=root, settings_file=settings)
            self.assertTrue(payload['ready'])
            self.assertIn('一键修补客户端', output.getvalue())

    def test_cli_menu_relay_action_uses_prompted_values(self):
        captured = {}

        def fake_run(args):
            captured['listen_host'] = args.listen_host
            captured['listen_port'] = args.listen_port
            captured['upstream_base'] = args.upstream_base
            captured['log_dir'] = args.log_dir
            return {'started': True, 'message': 'Relay started.'}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / BUNDLE_RELATIVE_PATH
            settings = root / 'settings.json'
            bundle.parent.mkdir(parents=True, exist_ok=True)
            bundle.write_text(sample_bundle_text(), encoding='utf-8')
            settings.write_text('{}', encoding='utf-8')

            with patch('trae_custom_endpoint_patch.cli.run_relay_from_args', side_effect=fake_run):
                with patch('builtins.input', side_effect=['r', 'https://example.com/v1', '', 'q']):
                    exit_code = cli_main(['menu', '--app-root', str(root), '--settings-file', str(settings)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured['listen_host'], '127.0.0.1')
        self.assertEqual(captured['listen_port'], 8787)
        self.assertEqual(captured['upstream_base'], 'https://example.com/v1')
        self.assertIn('trae-newapi-tap', captured['log_dir'])

    def test_cli_menu_can_start_relay_before_target_selection(self):
        captured = {}

        def fake_run(args):
            captured['listen_host'] = args.listen_host
            captured['listen_port'] = args.listen_port
            captured['upstream_base'] = args.upstream_base
            captured['log_dir'] = args.log_dir
            return {'started': True, 'message': 'Relay started.'}

        with patch('trae_custom_endpoint_patch.cli.run_relay_from_args', side_effect=fake_run):
            with patch('builtins.input', side_effect=['r', 'https://relay.example/v1', 'y', '0.0.0.0', '8899', '/tmp/relay-logs', 'q']):
                exit_code = cli_main(['menu'])

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured['listen_host'], '0.0.0.0')
        self.assertEqual(captured['listen_port'], 8899)
        self.assertEqual(captured['upstream_base'], 'https://relay.example/v1')
        self.assertEqual(captured['log_dir'], '/tmp/relay-logs')

    def test_cli_menu_reuses_saved_relay_defaults(self):
        captures = []

        def fake_run(args):
            captures.append(
                {
                    'listen_host': args.listen_host,
                    'listen_port': args.listen_port,
                    'upstream_base': args.upstream_base,
                    'log_dir': args.log_dir,
                }
            )
            return {'started': True, 'message': 'Relay started.'}

        with patch('trae_custom_endpoint_patch.cli.run_relay_from_args', side_effect=fake_run):
            with patch('builtins.input', side_effect=['r', 'https://relay.example/v1', 'y', '0.0.0.0', '8899', '/tmp/relay-logs', 'q']):
                first_exit = cli_main(['menu'])
            with patch('builtins.input', side_effect=['r', '', '', 'q']):
                second_exit = cli_main(['menu'])

        self.assertEqual(first_exit, 0)
        self.assertEqual(second_exit, 0)
        self.assertEqual(len(captures), 2)
        self.assertEqual(captures[1], captures[0])

    def test_cli_relay_status_command_reports_not_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cli_main(['relay-status', '--log-dir', tmp])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload['exists'])
        self.assertFalse(payload['running'])
        self.assertEqual(payload['log_dir'], tmp)

    def test_cli_menu_can_show_relay_status_before_target_selection(self):
        output = io.StringIO()
        relay_payload = {
            'log_dir': '/tmp/relay-logs',
            'running': False,
            'stale': False,
            'listen_host': '127.0.0.1',
            'listen_port': 8787,
            'upstream_base': 'https://relay.example/v1',
            'pid': None,
        }
        with patch('trae_custom_endpoint_patch.cli.relay_status', return_value=relay_payload) as status_mock:
            with patch('builtins.input', side_effect=['s', 'q']):
                with redirect_stdout(output):
                    exit_code = cli_main(['menu'])

        self.assertEqual(exit_code, 0)
        self.assertGreaterEqual(status_mock.call_count, 2)
        self.assertIn('Relay 详情', output.getvalue())
        self.assertIn('/tmp/relay-logs', output.getvalue())

    def test_cli_menu_can_stop_relay_before_target_selection(self):
        output = io.StringIO()
        relay_payload = {'log_dir': '/tmp/relay-logs', 'running': True, 'stale': False}
        with patch('trae_custom_endpoint_patch.cli.current_relay_log_dir', return_value='/tmp/relay-logs'):
            with patch('trae_custom_endpoint_patch.cli.relay_status', return_value=relay_payload):
                with patch('trae_custom_endpoint_patch.cli.stop_relay', return_value={'message': 'Relay stopped.', 'stopped': True}) as stop_mock:
                    with patch('builtins.input', side_effect=['r', 'q']):
                        with redirect_stdout(output):
                            exit_code = cli_main(['menu'])

        self.assertEqual(exit_code, 0)
        stop_mock.assert_called_once_with('/tmp/relay-logs')
        self.assertIn('Relay stopped.', output.getvalue())


class RelayTests(unittest.TestCase):
    def test_relay_status_reports_missing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = relay_status(tmp)

        self.assertFalse(payload['exists'])
        self.assertFalse(payload['running'])
        self.assertIsNone(payload['pid'])

    def test_stop_relay_removes_stale_pid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            pid_file = log_dir / 'relay.pid'
            pid_file.write_text(json.dumps({'pid': 999999, 'listen_port': 8787}), encoding='utf-8')

            payload = stop_relay(log_dir)

        self.assertFalse(pid_file.exists())
        self.assertFalse(payload['stopped'])
        self.assertTrue(payload['cleaned_stale_state'])

    def test_relay_background_process_can_start_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            args = SimpleNamespace(
                listen_host='127.0.0.1',
                listen_port=free_port(),
                upstream_base='http://127.0.0.1:9',
                log_dir=str(log_dir),
            )

            start_payload = run_relay_from_args(args)
            try:
                self.assertTrue(start_payload['started'])
                status_payload = relay_status(log_dir)
                self.assertTrue(status_payload['running'])
                self.assertEqual(status_payload['listen_port'], args.listen_port)

                stop_payload = stop_relay(log_dir)
                self.assertTrue(stop_payload['stopped'])
            finally:
                final_status = relay_status(log_dir)
                if final_status.get('running'):
                    stop_relay(log_dir)

            final_status = relay_status(log_dir)
            self.assertFalse(final_status['exists'])
            self.assertFalse(final_status['running'])

    def test_normalize_tool_content_arrays(self):
        payload = {
            'messages': [
                {
                    'role': 'tool',
                    'content': [{'type': 'text', 'text': 'abc'}],
                }
            ]
        }
        output = json.loads(normalize_chat_body(json.dumps(payload).encode('utf-8')))
        self.assertEqual(output['messages'][0]['content'], 'abc')

    def test_leave_non_tool_content_alone(self):
        payload = {
            'messages': [
                {
                    'role': 'assistant',
                    'content': [{'type': 'text', 'text': 'abc'}],
                }
            ]
        }
        output = json.loads(normalize_chat_body(json.dumps(payload).encode('utf-8')))
        self.assertIsInstance(output['messages'][0]['content'], list)


if __name__ == '__main__':
    unittest.main()
