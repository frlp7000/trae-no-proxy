from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from . import __version__
from .patcher import (
    doctor,
    discover_app_roots,
    discover_settings_files,
    ensure_local_agent_strategy,
    inspect,
    list_backups,
    patch_all,
    patch_bundle,
    restore_all,
    restore_bundle,
    restore_settings,
)
from .relay import (
    add_arguments as add_relay_arguments,
    add_server_arguments as add_relay_server_arguments,
    default_log_dir,
    relay_status,
    run_from_args as run_relay_from_args,
    serve_from_args as run_relay_server_from_args,
    stop_relay,
)

TARGET_ACTIONS = (
    ('patch-all', '一键修补客户端（推荐）'),
    ('doctor', '查看当前状态'),
    ('inspect', '查看详细状态'),
    ('list-backups', '查看备份列表'),
    ('restore-all', '恢复最近一次完整备份'),
    ('patch-bundle', '仅修补客户端 bundle'),
    ('patch-settings', '仅修补 settings.json'),
    ('restore-bundle', '恢复最近一次 bundle 备份'),
    ('restore-settings', '恢复最近一次 settings 备份'),
)
MENU_STATE_ENV = 'TRAE_PATCH_STATE_FILE'


def configure_console_output():
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, 'reconfigure', None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding='utf-8', errors='replace')
        except (OSError, ValueError):
            try:
                reconfigure(errors='replace')
            except (OSError, ValueError):
                pass


def print_result(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def add_target_arguments(parser, *, include_app_root=True, include_settings_file=True):
    if include_app_root:
        parser.add_argument('--app-root')
    if include_settings_file:
        parser.add_argument('--settings-file')


def menu_state_file() -> Path:
    override = os.environ.get(MENU_STATE_ENV)
    if override:
        return Path(override)
    return Path.cwd() / '.tmp' / 'trae-menu-state.json'


def load_menu_state() -> dict[str, object]:
    path = menu_state_file()
    try:
        raw = path.read_text(encoding='utf-8').strip()
    except OSError:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_menu_state(payload: dict[str, object]):
    path = menu_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def relay_defaults() -> dict[str, object]:
    relay_state = load_menu_state().get('relay', {})
    if not isinstance(relay_state, dict):
        relay_state = {}
    listen_port = relay_state.get('listen_port', 8787)
    if isinstance(listen_port, str) and listen_port.isdigit():
        listen_port = int(listen_port)
    if not isinstance(listen_port, int):
        listen_port = 8787
    return {
        'upstream_base': str(relay_state.get('upstream_base') or ''),
        'listen_host': str(relay_state.get('listen_host') or '127.0.0.1'),
        'listen_port': listen_port,
        'log_dir': str(relay_state.get('log_dir') or default_log_dir()),
    }


def remember_relay_defaults(args):
    state = load_menu_state()
    state['relay'] = {
        'upstream_base': args.upstream_base,
        'listen_host': args.listen_host,
        'listen_port': args.listen_port,
        'log_dir': args.log_dir,
    }
    save_menu_state(state)


def current_relay_log_dir() -> str:
    return str(relay_defaults().get('log_dir') or default_log_dir())


def build_parser():
    parser = argparse.ArgumentParser(
        prog='trae-patch',
        description='Trae CN custom endpoint patcher and compatibility relay',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--version', action='version', version='%(prog)s {0}'.format(__version__))
    subparsers = parser.add_subparsers(dest='command')

    menu_parser = subparsers.add_parser('menu', help='Open the interactive menu')
    add_target_arguments(menu_parser)

    doctor_parser = subparsers.add_parser('doctor', help='Check whether Trae or Trae CN is ready for custom endpoints')
    add_target_arguments(doctor_parser)

    inspect_parser = subparsers.add_parser('inspect', help='Show current patch status')
    add_target_arguments(inspect_parser)

    backups_parser = subparsers.add_parser('list-backups', help='List discovered backup files')
    add_target_arguments(backups_parser)

    bundle_parser = subparsers.add_parser('patch-bundle', help='Patch the Trae or Trae CN frontend bundle')
    add_target_arguments(bundle_parser, include_settings_file=False)

    settings_parser = subparsers.add_parser('patch-settings', help='Force local request routing in settings.json')
    add_target_arguments(settings_parser, include_app_root=False)

    all_parser = subparsers.add_parser('patch-all', help='Apply both bundle and settings patches')
    add_target_arguments(all_parser)

    restore_bundle_parser = subparsers.add_parser('restore-bundle', help='Restore the bundle from the latest or specified backup')
    add_target_arguments(restore_bundle_parser, include_settings_file=False)
    restore_bundle_parser.add_argument('--backup')

    restore_settings_parser = subparsers.add_parser('restore-settings', help='Restore settings.json from the latest or specified backup')
    add_target_arguments(restore_settings_parser, include_app_root=False)
    restore_settings_parser.add_argument('--backup')

    restore_all_parser = subparsers.add_parser('restore-all', help='Restore both bundle and settings from backups')
    add_target_arguments(restore_all_parser)
    restore_all_parser.add_argument('--bundle-backup')
    restore_all_parser.add_argument('--settings-backup')

    relay_parser = subparsers.add_parser('relay', help='Run the compatibility relay in the background')
    add_relay_arguments(relay_parser)

    relay_serve_parser = subparsers.add_parser('relay-serve', help=argparse.SUPPRESS)
    add_relay_arguments(relay_serve_parser)
    add_relay_server_arguments(relay_serve_parser)

    relay_status_parser = subparsers.add_parser('relay-status', help='Show relay status')
    relay_status_parser.add_argument('--log-dir', default=current_relay_log_dir())

    relay_stop_parser = subparsers.add_parser('relay-stop', help='Stop relay')
    relay_stop_parser.add_argument('--log-dir', default=current_relay_log_dir())
    return parser


def target_label(app_root: str | None, settings_file: str | None) -> str:
    if app_root:
        return Path(app_root).name
    if settings_file:
        return Path(settings_file).parent.parent.name
    return 'Manual target'


def make_target(app_root: str | None, settings_file: str | None) -> dict[str, str | None]:
    return {
        'label': target_label(app_root, settings_file),
        'app_root': app_root,
        'settings_file': settings_file,
    }


def discover_targets() -> list[dict[str, str | None]]:
    roots = discover_app_roots()
    settings_files = discover_settings_files()
    settings_by_name: dict[str, list[str]] = {}
    for settings_file in settings_files:
        settings_by_name.setdefault(settings_file.parent.parent.name, []).append(str(settings_file))

    targets: list[dict[str, str | None]] = []
    used_settings: set[str] = set()

    for root in roots:
        match = None
        for candidate in settings_by_name.get(root.name, []):
            if candidate in used_settings:
                continue
            match = candidate
            used_settings.add(candidate)
            break
        targets.append(make_target(str(root), match))

    for settings_file in settings_files:
        value = str(settings_file)
        if value in used_settings:
            continue
        targets.append(make_target(None, value))

    return targets


def summarize_target(target: dict[str, str | None]) -> dict[str, object]:
    payload = doctor(app_root=target['app_root'], settings_file=target['settings_file'])
    if payload['ready']:
        state = '已就绪'
    elif payload['bundle'].get('exists') or payload['settings'].get('exists'):
        state = '待修补'
    else:
        state = '路径不完整'
    return {
        'target': target,
        'doctor': payload,
        'state': state,
    }


def collect_target_summaries() -> list[dict[str, object]]:
    return [summarize_target(target) for target in discover_targets()]


def print_target(target: dict[str, str | None]):
    label = target['label']
    app_root = target['app_root'] or '(未设置)'
    settings_file = target['settings_file'] or '(未设置)'
    print('目标: {0}'.format(label))
    print('  app_root: {0}'.format(app_root))
    print('  settings: {0}'.format(settings_file))


def prompt(prompt_text: str) -> str:
    return input(prompt_text).strip()


def prompt_with_default(prompt_text: str, default: str | int | None = None) -> str:
    suffix = ' [{0}]'.format(default) if default not in (None, '') else ''
    raw = prompt('{0}{1}: '.format(prompt_text, suffix))
    if raw:
        return raw
    return '' if default is None else str(default)


def prompt_backup_path(label: str) -> str | None:
    value = prompt('{0} 备份路径，直接回车使用最近一次: '.format(label))
    return value or None


def prompt_manual_target() -> dict[str, str | None] | None:
    manual_app_root = prompt('输入 app_root，留空则跳过: ') or None
    manual_settings = prompt('输入 settings.json 路径，留空则跳过: ') or None
    if manual_app_root is None and manual_settings is None:
        return None
    return make_target(manual_app_root, manual_settings)


def bundle_status_text(payload: dict[str, object]) -> str:
    bundle = payload['bundle']
    if not bundle.get('exists'):
        return '未找到'
    if payload['bundle_ready']:
        return '已生效'
    rules = bundle.get('rules', {})
    if isinstance(rules, dict) and rules:
        enabled = sum(1 for value in rules.values() if value)
        return '未完成 ({0}/{1})'.format(enabled, len(rules))
    return '未生效'


def settings_status_text(payload: dict[str, object]) -> str:
    settings = payload['settings']
    if not settings.get('exists'):
        return '未找到'
    if payload['settings_ready']:
        return 'local'
    return str(settings.get('strategy') or '未设置')


def relay_summary_status_text(payload: dict[str, object]) -> str:
    if payload.get('running'):
        return '运行中'
    if payload.get('stale'):
        return '已停止（残留状态文件）'
    return '未运行'


def relay_upstream_text(payload: dict[str, object]) -> str:
    value = payload.get('upstream_base') or relay_defaults().get('upstream_base')
    return str(value or '未记录')


def print_relay_details(payload: dict[str, object]):
    print('\nRelay 详情:')
    print('  状态: {0}'.format(relay_summary_status_text(payload)))
    if payload.get('listen_host') and payload.get('listen_port'):
        print('  监听: {0}:{1}'.format(payload['listen_host'], payload['listen_port']))
    print('  上游: {0}'.format(relay_upstream_text(payload)))
    print('  日志目录: {0}'.format(payload['log_dir']))
    if payload.get('pid'):
        print('  PID: {0}'.format(payload['pid']))
    if payload.get('stale'):
        print('  提示: 检测到陈旧 pid 文件，执行停止操作时会自动清理。')


def print_home_dashboard(target_summaries: list[dict[str, object]], relay_info: dict[str, object]):
    print('\nTrae Patch 菜单')
    print('==============')
    print('客户端状态:')
    if target_summaries:
        for index, summary in enumerate(target_summaries, start=1):
            target = summary['target']
            payload = summary['doctor']
            print('[{0}] {1}  {2}'.format(index, target['label'], summary['state']))
            print('    bundle: {0}  settings: {1}'.format(bundle_status_text(payload), settings_status_text(payload)))
    else:
        print('  未自动发现客户端，按 M 手动输入路径。')

    print('Relay: {0}'.format(relay_summary_status_text(relay_info)))
    if relay_info.get('listen_host') and relay_info.get('listen_port'):
        print('  监听: {0}:{1}'.format(relay_info['listen_host'], relay_info['listen_port']))
    print('  上游: {0}'.format(relay_upstream_text(relay_info)))
    print('  日志目录: {0}'.format(relay_info['log_dir']))

    print('\n快捷操作:')
    if target_summaries:
        print('  直接输入客户端编号进入管理')
    print('  [P] 一键修补某个客户端')
    print('  [R] {0}'.format('停止 Relay' if relay_info.get('running') else '启动 Relay'))
    print('  [S] 查看 Relay 详情')
    print('  [M] 手动输入路径')
    print('  [Q] 退出')


def choose_home_action(target_summaries: list[dict[str, object]], relay_info: dict[str, object]):
    while True:
        raw = prompt('选择操作或客户端编号: ').lower()
        if raw == 'q':
            return ('quit', None)
        if raw == 'p':
            return ('patch-target', None)
        if raw == 'r':
            return ('relay-stop' if relay_info.get('running') else 'relay-start', None)
        if raw == 's':
            return ('relay-status', None)
        if raw == 'm':
            return ('manual-target', None)
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(target_summaries):
                return ('target', target_summaries[index - 1]['target'])
        print('输入无效，请重新选择。')


def choose_target_from_summaries(target_summaries: list[dict[str, object]], purpose: str) -> dict[str, str | None] | None:
    while True:
        print('\n选择客户端: {0}'.format(purpose))
        if target_summaries:
            for index, summary in enumerate(target_summaries, start=1):
                target = summary['target']
                print('[{0}] {1}  {2}'.format(index, target['label'], summary['state']))
        else:
            print('未自动发现客户端。')
        print('[M] 手动输入路径')
        print('[B] 返回')

        raw = prompt('选择目标: ').lower()
        if raw == 'b':
            return None
        if raw == 'm':
            return prompt_manual_target()
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(target_summaries):
                return target_summaries[index - 1]['target']
        print('输入无效，请重新选择。')


def prompt_relay_args():
    defaults = relay_defaults()
    while True:
        upstream_base = prompt_with_default('输入你的网关地址，例如 https://your.gateway.example/v1', defaults['upstream_base'])
        if upstream_base:
            break
        print('网关地址不能为空。')

    customize = prompt('高级设置可选。直接回车使用默认监听地址/端口/日志目录，输入 y 自定义: ').lower()
    listen_host = str(defaults['listen_host'])
    listen_port = int(defaults['listen_port'])
    log_dir = str(defaults['log_dir'])

    if customize in {'y', 'yes'}:
        listen_host = prompt_with_default('监听地址', listen_host)
        while True:
            listen_port_text = prompt_with_default('监听端口', listen_port)
            try:
                listen_port = int(listen_port_text)
                break
            except ValueError:
                print('端口必须是整数。')
        log_dir = prompt_with_default('日志目录', log_dir)

    return SimpleNamespace(
        listen_host=listen_host,
        listen_port=listen_port,
        upstream_base=upstream_base,
        log_dir=log_dir,
    )


def run_relay_interactive() -> dict[str, object]:
    print('\n即将启动 Relay。只需要填网关地址，高级参数可以直接回车使用上次或默认值。')
    args = prompt_relay_args()
    remember_relay_defaults(args)
    return run_relay_from_args(args)


def run_target_action(action: str, target: dict[str, str | None]) -> dict[str, object]:
    if action == 'doctor':
        return doctor(app_root=target['app_root'], settings_file=target['settings_file'])
    if action == 'inspect':
        return inspect(app_root=target['app_root'], settings_file=target['settings_file'])
    if action == 'list-backups':
        return list_backups(app_root=target['app_root'], settings_file=target['settings_file'])
    if action == 'patch-bundle':
        return patch_bundle(app_root=target['app_root'])
    if action == 'patch-settings':
        return ensure_local_agent_strategy(settings_file=target['settings_file'])
    if action == 'patch-all':
        return patch_all(app_root=target['app_root'], settings_file=target['settings_file'])
    if action == 'restore-bundle':
        return restore_bundle(app_root=target['app_root'], backup=prompt_backup_path('bundle'))
    if action == 'restore-settings':
        return restore_settings(settings_file=target['settings_file'], backup=prompt_backup_path('settings'))
    if action == 'restore-all':
        return restore_all(
            app_root=target['app_root'],
            settings_file=target['settings_file'],
            bundle_backup=prompt_backup_path('bundle'),
            settings_backup=prompt_backup_path('settings'),
        )
    raise RuntimeError('Unknown target action: {0}'.format(action))


def print_target_dashboard(summary: dict[str, object], relay_info: dict[str, object]):
    target = summary['target']
    payload = summary['doctor']
    bundle = payload['bundle']
    settings = payload['settings']

    print('')
    print_target(target)
    print('  总体状态: {0}'.format(summary['state']))
    print('  bundle: {0}'.format(bundle_status_text(payload)))
    print('  settings: {0}'.format(settings_status_text(payload)))
    print('  bundle 备份: {0} 个'.format(len(bundle.get('backups', []))))
    print('  settings 备份: {0} 个'.format(len(settings.get('backups', []))))
    suggestions = payload.get('suggestions') or []
    if suggestions:
        print('  建议: {0}'.format(suggestions[0]))

    print('\n客户端操作:')
    for index, (_, label) in enumerate(TARGET_ACTIONS, start=1):
        print('[{0}] {1}'.format(index, label))
    print('[R] {0}'.format('停止 Relay' if relay_info.get('running') else '启动 Relay'))
    print('[S] 查看 Relay 详情')
    print('[C] 切换客户端')
    print('[B] 返回首页')
    print('[Q] 退出')


def choose_target_action(relay_info: dict[str, object]) -> str:
    while True:
        raw = prompt('选择操作: ').lower()
        if raw in {'q', 'b', 'c', 'r', 's'}:
            return raw
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(TARGET_ACTIONS):
                return TARGET_ACTIONS[index - 1][0]
        print('输入无效，请重新选择。')


def run_target_menu(target: dict[str, str | None]) -> str:
    while True:
        relay_info = relay_status(current_relay_log_dir())
        summary = summarize_target(target)
        print_target_dashboard(summary, relay_info)
        action = choose_target_action(relay_info)
        if action == 'q':
            return 'quit'
        if action == 'b':
            return 'back'
        if action == 'c':
            return 'switch'
        if action == 'r':
            if relay_info.get('running'):
                print_result(stop_relay(current_relay_log_dir()))
            else:
                print_result(run_relay_interactive())
            continue
        if action == 's':
            print_relay_details(relay_status(current_relay_log_dir()))
            continue

        try:
            print_result(run_target_action(action, target))
        except Exception as exc:
            print_result(
                {
                    'action': action,
                    'app_root': target['app_root'],
                    'settings_file': target['settings_file'],
                    'error': str(exc),
                }
            )


def run_interactive_menu(initial_app_root: str | None = None, initial_settings_file: str | None = None) -> int:
    current_target = None
    if initial_app_root is not None or initial_settings_file is not None:
        current_target = make_target(initial_app_root, initial_settings_file)

    while True:
        if current_target is not None:
            outcome = run_target_menu(current_target)
            if outcome == 'quit':
                return 0
            current_target = None
            continue

        target_summaries = collect_target_summaries()
        relay_info = relay_status(current_relay_log_dir())
        print_home_dashboard(target_summaries, relay_info)
        action, payload = choose_home_action(target_summaries, relay_info)

        if action == 'quit':
            return 0
        if action == 'target':
            current_target = payload
            continue
        if action == 'manual-target':
            current_target = prompt_manual_target()
            continue
        if action == 'patch-target':
            target = choose_target_from_summaries(target_summaries, '一键修补客户端')
            if target is not None:
                print_result(run_target_action('patch-all', target))
            continue
        if action == 'relay-start':
            print_result(run_relay_interactive())
            continue
        if action == 'relay-stop':
            print_result(stop_relay(current_relay_log_dir()))
            continue
        if action == 'relay-status':
            print_relay_details(relay_status(current_relay_log_dir()))
            continue


def run_command(args) -> int:
    if args.command == 'doctor':
        print_result(doctor(app_root=args.app_root, settings_file=args.settings_file))
        return 0

    if args.command == 'inspect':
        print_result(inspect(app_root=args.app_root, settings_file=args.settings_file))
        return 0

    if args.command == 'list-backups':
        print_result(list_backups(app_root=args.app_root, settings_file=args.settings_file))
        return 0

    if args.command == 'patch-bundle':
        print_result(patch_bundle(app_root=args.app_root))
        return 0

    if args.command == 'patch-settings':
        print_result(ensure_local_agent_strategy(settings_file=args.settings_file))
        return 0

    if args.command == 'patch-all':
        print_result(patch_all(app_root=args.app_root, settings_file=args.settings_file))
        return 0

    if args.command == 'restore-bundle':
        print_result(restore_bundle(app_root=args.app_root, backup=args.backup))
        return 0

    if args.command == 'restore-settings':
        print_result(restore_settings(settings_file=args.settings_file, backup=args.backup))
        return 0

    if args.command == 'restore-all':
        print_result(
            restore_all(
                app_root=args.app_root,
                settings_file=args.settings_file,
                bundle_backup=args.bundle_backup,
                settings_backup=args.settings_backup,
            )
        )
        return 0

    if args.command == 'relay':
        print_result(run_relay_from_args(args))
        return 0

    if args.command == 'relay-serve':
        return run_relay_server_from_args(args)

    if args.command == 'relay-status':
        print_result(relay_status(args.log_dir))
        return 0

    if args.command == 'relay-stop':
        print_result(stop_relay(args.log_dir))
        return 0

    raise RuntimeError('Unknown command: {0}'.format(args.command))


def main(argv=None) -> int:
    configure_console_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == 'menu':
        return run_interactive_menu(initial_app_root=args.app_root, initial_settings_file=args.settings_file)

    if args.command is None:
        if sys.stdin.isatty():
            return run_interactive_menu()
        parser.print_help()
        return 1

    return run_command(args)
