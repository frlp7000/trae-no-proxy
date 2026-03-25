from __future__ import annotations

import argparse
import datetime as dt
import http.client
import http.server
import json
import os
import pathlib
import secrets
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse

PID_FILE_NAME = 'relay.pid'
STDOUT_LOG_NAME = 'relay.stdout.log'
STDERR_LOG_NAME = 'relay.stderr.log'
CONTROL_PREFIX = '/__trae_relay/control'
HEALTH_PATH = CONTROL_PREFIX + '/health'
SHUTDOWN_PATH = CONTROL_PREFIX + '/shutdown'
START_TIMEOUT_SECONDS = 8.0
STOP_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.1


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()



def default_log_dir() -> str:
    return str(pathlib.Path.cwd() / '.tmp' / 'trae-newapi-tap')



def relay_pid_file(log_dir: pathlib.Path) -> pathlib.Path:
    return log_dir / PID_FILE_NAME



def relay_stdout_log(log_dir: pathlib.Path) -> pathlib.Path:
    return log_dir / STDOUT_LOG_NAME



def relay_stderr_log(log_dir: pathlib.Path) -> pathlib.Path:
    return log_dir / STDERR_LOG_NAME



def mask(value):
    if not value:
        return value
    if value.lower().startswith('bearer '):
        token = value[7:]
        if len(token) <= 10:
            return 'Bearer ***'
        return 'Bearer {0}...{1}'.format(token[:6], token[-4:])
    return '***'



def decode_text(body: bytes) -> str:
    return body.decode('utf-8', errors='replace')



def flatten_text_parts(value):
    if isinstance(value, list) and all(isinstance(item, dict) and item.get('type') == 'text' for item in value):
        return ''.join(item.get('text', '') for item in value)
    return value



def normalize_chat_body(body: bytes) -> bytes:
    try:
        payload = json.loads(decode_text(body))
    except Exception:
        return body
    changed = False
    if isinstance(payload, dict) and isinstance(payload.get('messages'), list):
        for message in payload['messages']:
            if isinstance(message, dict) and message.get('role') == 'tool' and 'content' in message:
                normalized = flatten_text_parts(message.get('content'))
                if normalized != message.get('content'):
                    message['content'] = normalized
                    changed = True
    if not changed:
        return body
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')



def parse_pid(value) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        pid = int(value)
        return pid if pid > 0 else None
    return None



def read_relay_state(log_dir: pathlib.Path) -> dict[str, object] | None:
    path = relay_pid_file(log_dir)
    if not path.exists():
        return None
    raw = path.read_text(encoding='utf-8').strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        pid = parse_pid(raw)
        return {'pid': pid} if pid is not None else None
    return payload if isinstance(payload, dict) else None



def process_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True



def process_command_line(pid: int | None) -> str | None:
    if pid is None:
        return None
    if os.name == 'posix':
        proc_cmdline = pathlib.Path('/proc/{0}/cmdline'.format(pid))
        if proc_cmdline.exists():
            try:
                raw = proc_cmdline.read_bytes().replace(b'\x00', b' ').strip()
                if raw:
                    return raw.decode('utf-8', errors='replace')
            except OSError:
                pass
        try:
            completed = subprocess.run(
                ['ps', '-o', 'command=', '-p', str(pid)],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        output = completed.stdout.strip()
        return output or None

    command = (
        'powershell.exe -NoProfile -Command '
        '"$p = Get-CimInstance Win32_Process -Filter \"ProcessId = {0}\"; '
        'if ($p) {{ $p.CommandLine }}"'
    ).format(pid)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            shell=True,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = completed.stdout.strip()
    return output or None



def process_matches_state(state: dict[str, object]) -> bool:
    pid = parse_pid(state.get('pid'))
    if not process_alive(pid):
        return False
    command_line = process_command_line(pid)
    if not command_line:
        return False
    signature = str(state.get('command_signature') or 'relay-serve')
    normalized = command_line.lower()
    return signature.lower() in normalized and (
        'trae_custom_endpoint_patch' in normalized or 'trae-patch' in normalized or 'relay.py' in normalized
    )



def control_host(listen_host: str | None) -> str | None:
    if not listen_host:
        return None
    if listen_host == '0.0.0.0':
        return '127.0.0.1'
    if listen_host == '::':
        return '::1'
    return listen_host



def request_control(state: dict[str, object], path: str, *, timeout: float = 2.0) -> dict[str, object]:
    listen_host = control_host(str(state.get('listen_host') or ''))
    listen_port = state.get('listen_port')
    if isinstance(listen_port, str) and listen_port.isdigit():
        listen_port = int(listen_port)
    shutdown_token = state.get('shutdown_token')
    if not listen_host or not isinstance(listen_port, int) or not shutdown_token:
        return {'ok': False, 'reason': 'missing_control_metadata'}

    connection = http.client.HTTPConnection(listen_host, listen_port, timeout=timeout)
    try:
        connection.request('POST', path, headers={'X-Trae-Relay-Token': str(shutdown_token), 'Connection': 'close'})
        response = connection.getresponse()
        raw_body = response.read()
    except OSError as exc:
        return {'ok': False, 'reason': str(exc)}
    finally:
        connection.close()

    payload: dict[str, object] | None = None
    if raw_body:
        try:
            parsed = json.loads(decode_text(raw_body))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed
    return {
        'ok': response.status == 200,
        'status': response.status,
        'reason': response.reason,
        'payload': payload,
    }



def wait_for_process_exit(pid: int | None, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return not process_alive(pid)



def relay_status(log_dir: str | pathlib.Path | None = None) -> dict[str, object]:
    path = pathlib.Path(log_dir or default_log_dir())
    state_file = relay_pid_file(path)
    state = read_relay_state(path) or {}
    pid = parse_pid(state.get('pid'))
    running = process_alive(pid)
    return {
        'log_dir': str(path),
        'pid_file': str(state_file),
        'exists': state_file.exists(),
        'running': running,
        'stale': bool(state_file.exists() and not running),
        'pid': pid,
        'listen_host': state.get('listen_host'),
        'listen_port': state.get('listen_port'),
        'upstream_base': state.get('upstream_base'),
        'started_at': state.get('started_at'),
        'instance_id': state.get('instance_id'),
    }



def remove_state_file_if_matches(path: pathlib.Path, pid: int | None = None, instance_id: str | None = None):
    if not path.exists():
        return
    if pid is None and instance_id is None:
        path.unlink()
        return
    state = read_relay_state(path.parent) or {}
    state_pid = parse_pid(state.get('pid'))
    state_instance_id = state.get('instance_id')
    if pid is not None and state_pid != pid:
        return
    if instance_id is not None and state_instance_id != instance_id:
        return
    path.unlink()



def validate_upstream_base(value: str) -> urllib.parse.ParseResult:
    upstream = urllib.parse.urlparse(value)
    if upstream.scheme not in {'http', 'https'} or not upstream.netloc:
        raise SystemExit('--upstream-base must be http://host or https://host')
    return upstream



def build_child_command(args, *, instance_id: str, shutdown_token: str) -> list[str]:
    base_args = [
        'relay-serve',
        '--listen-host',
        args.listen_host,
        '--listen-port',
        str(args.listen_port),
        '--upstream-base',
        args.upstream_base,
        '--log-dir',
        args.log_dir,
        '--instance-id',
        instance_id,
        '--shutdown-token',
        shutdown_token,
    ]
    if getattr(sys, 'frozen', False):
        return [sys.executable, *base_args]
    return [sys.executable, '-m', 'trae_custom_endpoint_patch', *base_args]



def build_child_env() -> dict[str, str]:
    env = os.environ.copy()
    package_root = str(pathlib.Path(__file__).resolve().parents[1])
    current = env.get('PYTHONPATH')
    if current:
        env['PYTHONPATH'] = os.pathsep.join([package_root, current])
    else:
        env['PYTHONPATH'] = package_root
    return env


def spawn_child_process(command: list[str], *, stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> subprocess.Popen[bytes]:
    stdout_handle = stdout_path.open('ab')
    stderr_handle = stderr_path.open('ab')
    try:
        kwargs: dict[str, object] = {
            'stdin': subprocess.DEVNULL,
            'stdout': stdout_handle,
            'stderr': stderr_handle,
            'cwd': str(pathlib.Path.cwd()),
            'env': build_child_env(),
        }
        if os.name == 'nt':
            creationflags = 0
            creationflags |= getattr(subprocess, 'DETACHED_PROCESS', 0)
            creationflags |= getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            creationflags |= getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            kwargs['creationflags'] = creationflags
        else:
            kwargs['start_new_session'] = True
        return subprocess.Popen(command, **kwargs)
    finally:
        stdout_handle.close()
        stderr_handle.close()



def forget_process_handle(process: subprocess.Popen[bytes]):
    if process.poll() is not None:
        return
    if hasattr(process, '_child_created'):
        process._child_created = False
    process.returncode = 0


def wait_for_startup(log_dir: pathlib.Path, *, instance_id: str, process: subprocess.Popen[bytes]) -> dict[str, object]:
    stdout_log = str(relay_stdout_log(log_dir))
    stderr_log = str(relay_stderr_log(log_dir))
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    last_status = relay_status(log_dir)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return {
                **last_status,
                'started': False,
                'message': 'Relay exited during startup.',
                'exit_code': process.returncode,
                'stdout_log': stdout_log,
                'stderr_log': stderr_log,
            }
        state = read_relay_state(log_dir) or {}
        last_status = relay_status(log_dir)
        if state.get('instance_id') == instance_id and last_status['running']:
            health = request_control(state, HEALTH_PATH)
            payload = health.get('payload') if isinstance(health.get('payload'), dict) else {}
            if health.get('ok') and payload.get('instance_id') == instance_id:
                forget_process_handle(process)
                return {
                    **last_status,
                    'started': True,
                    'message': 'Relay started.',
                    'shutdown_via': None,
                    'stdout_log': stdout_log,
                    'stderr_log': stderr_log,
                }
        time.sleep(POLL_INTERVAL_SECONDS)

    forget_process_handle(process)
    return {
        **last_status,
        'started': False,
        'message': 'Timed out waiting for relay startup.',
        'stdout_log': stdout_log,
        'stderr_log': stderr_log,
    }



def run_from_args(args) -> dict[str, object]:
    validate_upstream_base(args.upstream_base)
    log_dir = pathlib.Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    state_file = relay_pid_file(log_dir)
    status = relay_status(log_dir)
    if status['running']:
        return {
            **status,
            'started': False,
            'message': 'Relay already running.',
        }
    if state_file.exists() and not status['running']:
        state_file.unlink()

    instance_id = secrets.token_hex(12)
    shutdown_token = secrets.token_urlsafe(24)
    command = build_child_command(args, instance_id=instance_id, shutdown_token=shutdown_token)
    process = spawn_child_process(
        command,
        stdout_path=relay_stdout_log(log_dir),
        stderr_path=relay_stderr_log(log_dir),
    )
    return wait_for_startup(log_dir, instance_id=instance_id, process=process)



def stop_relay(log_dir: str | pathlib.Path | None = None) -> dict[str, object]:
    path = pathlib.Path(log_dir or default_log_dir())
    state_file = relay_pid_file(path)
    state = read_relay_state(path) or {}
    status = relay_status(path)
    pid = parse_pid(state.get('pid'))
    instance_id = state.get('instance_id') if isinstance(state.get('instance_id'), str) else None

    if pid is None:
        if state_file.exists():
            state_file.unlink()
            return {
                **status,
                'stopped': False,
                'cleaned_stale_state': True,
                'message': 'Relay state file did not contain a valid pid. Removed stale pid file.',
            }
        return {
            **status,
            'stopped': False,
            'message': 'No relay pid file found.',
        }

    if not status['running']:
        if state_file.exists():
            state_file.unlink()
        return {
            **status,
            'stopped': False,
            'cleaned_stale_state': True,
            'message': 'Relay is not running. Removed stale pid file.',
        }

    control_result = request_control(state, SHUTDOWN_PATH)
    if control_result.get('ok'):
        if wait_for_process_exit(pid, STOP_TIMEOUT_SECONDS):
            remove_state_file_if_matches(state_file, pid=pid, instance_id=instance_id)
            return {
                **relay_status(path),
                'stopped': True,
                'shutdown_via': 'control',
                'message': 'Relay stopped.',
            }
        current_status = relay_status(path)
        if not current_status['running']:
            remove_state_file_if_matches(state_file, pid=pid, instance_id=instance_id)
            return {
                **current_status,
                'stopped': True,
                'shutdown_via': 'control',
                'message': 'Relay stopped.',
            }

    if process_matches_state(state):
        try:
            os.kill(pid, getattr(signal, 'SIGTERM', signal.SIGINT))
        except OSError as exc:
            signal_error = str(exc)
        else:
            signal_error = None
        if wait_for_process_exit(pid, STOP_TIMEOUT_SECONDS):
            remove_state_file_if_matches(state_file, pid=pid, instance_id=instance_id)
            return {
                **relay_status(path),
                'stopped': True,
                'shutdown_via': 'signal',
                'message': 'Relay stopped.' if signal_error is None else 'Relay stopped after a signal retry.',
            }
        current_status = relay_status(path)
        if not current_status['running']:
            remove_state_file_if_matches(state_file, pid=pid, instance_id=instance_id)
            return {
                **current_status,
                'stopped': True,
                'shutdown_via': 'signal',
                'message': 'Relay stopped.' if signal_error is None else 'Relay stopped after a signal retry.',
            }
        if signal_error is not None:
            return {
                **relay_status(path),
                'stopped': False,
                'shutdown_via': None,
                'message': 'Failed to signal relay process: {0}'.format(signal_error),
            }

    return {
        **relay_status(path),
        'stopped': False,
        'shutdown_via': None,
        'message': 'Relay stop request was sent, but shutdown could not be verified.',
    }



class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'TraeRelay/1.0'

    def log_message(self, *_args):
        return

    def do_GET(self):
        self.handle_proxy()

    def do_POST(self):
        self.handle_proxy()

    def do_PUT(self):
        self.handle_proxy()

    def do_PATCH(self):
        self.handle_proxy()

    def do_DELETE(self):
        self.handle_proxy()

    def do_OPTIONS(self):
        self.handle_proxy()

    def send_json(self, status: int, payload: dict[str, object]):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)

    def authorize_control(self) -> bool:
        token = self.headers.get('X-Trae-Relay-Token')
        if token == self.server.shutdown_token:
            return True
        self.send_json(403, {'ok': False, 'message': 'Forbidden'})
        return False

    def handle_control(self, parsed: urllib.parse.ParseResult):
        if not self.authorize_control():
            return
        if parsed.path == HEALTH_PATH:
            self.send_json(
                200,
                {
                    'ok': True,
                    'instance_id': self.server.instance_id,
                    'pid': os.getpid(),
                    'started_at': self.server.started_at,
                },
            )
            return
        if parsed.path == SHUTDOWN_PATH:
            self.send_json(
                200,
                {
                    'ok': True,
                    'instance_id': self.server.instance_id,
                    'message': 'Relay stopping.',
                },
            )
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self.send_json(404, {'ok': False, 'message': 'Unknown control path'})

    def handle_proxy(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith(CONTROL_PREFIX):
            self.handle_control(parsed)
            return

        request_id = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        content_length = int(self.headers.get('Content-Length', '0') or '0')
        original_body = self.rfile.read(content_length) if content_length else b''
        request_file = self.server.log_dir / '{0}.request.body.txt'.format(request_id)
        request_file.write_text(decode_text(original_body), encoding='utf-8')
        request_record = {
            'kind': 'request',
            'request_id': request_id,
            'timestamp': now(),
            'client_address': self.client_address[0],
            'method': self.command,
            'path': self.path,
            'headers': {key: (mask(value) if key.lower() == 'authorization' else value) for key, value in self.headers.items()},
            'body_file': request_file.name,
        }
        with self.server.summary.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(request_record, ensure_ascii=False) + '\n')

        body = normalize_chat_body(original_body) if parsed.path.endswith('/chat/completions') else original_body
        upstream = self.server.upstream
        path = self.path if self.path.startswith('/') else '/' + self.path
        if upstream.path and upstream.path != '/':
            path = upstream.path.rstrip('/') + path
        headers = {key: value for key, value in self.headers.items() if key.lower() not in {'host', 'content-length'}}
        headers['Host'] = upstream.netloc
        headers['Connection'] = 'close'

        connection = None
        try:
            if upstream.scheme == 'https':
                connection = http.client.HTTPSConnection(
                    upstream.hostname,
                    upstream.port or 443,
                    context=ssl.create_default_context(),
                    timeout=300,
                )
            else:
                connection = http.client.HTTPConnection(upstream.hostname, upstream.port or 80, timeout=300)
            connection.request(self.command, path, body=body if body else None, headers=headers)
            response = connection.getresponse()
            response_headers = dict(response.getheaders())
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in {'transfer-encoding', 'connection', 'content-length', 'keep-alive'}:
                    self.send_header(key, value)
            self.send_header('Connection', 'close')
            self.end_headers()
            preview = bytearray()
            preview_limit = 65536
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                if len(preview) < preview_limit:
                    preview.extend(chunk[: preview_limit - len(preview)])
                self.wfile.write(chunk)
                self.wfile.flush()
            status = response.status
            reason = response.reason
            response_body = bytes(preview)
        except Exception as exc:
            response_body = 'proxy error: {0}\n'.format(exc).encode('utf-8')
            status = 502
            reason = 'Bad Gateway'
            response_headers = {'proxy-error': str(exc)}
            self.send_response(status, reason)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(response_body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(response_body)
        finally:
            if connection is not None:
                connection.close()

        response_file = self.server.log_dir / '{0}.response.preview.txt'.format(request_id)
        response_file.write_text(decode_text(response_body), encoding='utf-8')
        response_record = {
            'kind': 'response',
            'request_id': request_id,
            'timestamp': now(),
            'status': status,
            'reason': reason,
            'headers': response_headers,
            'preview_file': response_file.name,
        }
        with self.server.summary.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(response_record, ensure_ascii=False) + '\n')



class ThreadedHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True



def add_arguments(parser):
    parser.add_argument('--listen-host', default='127.0.0.1')
    parser.add_argument('--listen-port', type=int, default=8787)
    parser.add_argument('--upstream-base', required=True)
    parser.add_argument('--log-dir', default=default_log_dir())



def add_server_arguments(parser):
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--shutdown-token', required=True)



def serve_from_args(args) -> int:
    upstream = validate_upstream_base(args.upstream_base)
    log_dir = pathlib.Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    state_file = relay_pid_file(log_dir)
    status = relay_status(log_dir)
    current_pid = os.getpid()
    if status['running'] and status['pid'] != current_pid:
        raise SystemExit('relay already running on pid {0} (log dir: {1})'.format(status['pid'], log_dir))
    if state_file.exists() and not status['running']:
        state_file.unlink()

    server = ThreadedHTTPServer((args.listen_host, args.listen_port), ProxyHandler)
    server.upstream = upstream
    server.log_dir = log_dir
    server.summary = log_dir / 'requests.jsonl'
    server.instance_id = args.instance_id
    server.shutdown_token = args.shutdown_token
    server.started_at = now()

    state = {
        'pid': current_pid,
        'listen_host': args.listen_host,
        'listen_port': args.listen_port,
        'upstream_base': args.upstream_base,
        'started_at': server.started_at,
        'instance_id': args.instance_id,
        'shutdown_token': args.shutdown_token,
        'command_signature': 'relay-serve',
    }
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print('Listening on http://{0}:{1}'.format(args.listen_host, args.listen_port))
    print('Forwarding to {0}'.format(args.upstream_base))
    print('Logs written to {0}'.format(args.log_dir))
    print('PID file: {0}'.format(state_file))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('Relay stopped.')
    finally:
        server.server_close()
        remove_state_file_if_matches(state_file, pid=current_pid, instance_id=args.instance_id)
    return 0



def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Trae custom endpoint compatibility relay')
    add_arguments(parser)
    parser.add_argument('--instance-id')
    parser.add_argument('--shutdown-token')
    args = parser.parse_args(argv)
    if args.instance_id and args.shutdown_token:
        return serve_from_args(args)
    result = run_from_args(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
