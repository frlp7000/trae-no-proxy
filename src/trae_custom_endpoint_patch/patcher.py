from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from string import ascii_uppercase

APP_NAMES = ('Trae CN', 'Trae')
APP_ROOT_ENV = 'TRAE_APP_ROOT'
SETTINGS_FILE_ENV = 'TRAE_SETTINGS_FILE'
BUNDLE_RELATIVE_PATH = Path('resources/app/node_modules/@byted-icube/ai-modules-chat/dist/index.js')
STRATEGY_KEY = 'ai_assistant.request.agent_task_service_strategy'
BACKUP_TAG = 'bak-trae-patch'


@dataclass(frozen=True)
class BundlePatchRule:
    name: str
    original: str
    replacement: str


PATCH_RULES = (
    BundlePatchRule(
        name='disable_scope_gate',
        original='let eDg=e=>e?.scope===v9.BYTEDANCE,',
        replacement='let eDg=e=>!1,',
    ),
    BundlePatchRule(
        name='always_render_model_management',
        original='!n&&i&&sm().createElement(eDf,{ref:o,container:s})',
        replacement='i&&sm().createElement(eDf,{ref:o,container:s})',
    ),
)


def timestamp() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M%S')


def path_identity_key(candidate: Path) -> str:
    value = os.path.normpath(str(candidate)).replace("\\", "/")
    if os.name == "nt":
        return value.lower()
    if len(value) >= 2 and value[1] == ":":
        return value.lower()
    if value.startswith("/mnt/") and len(value) > 6 and value[5].isalpha() and value[6] == "/":
        return value.lower()
    return value


def unique_paths(candidates: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = path_identity_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def first_existing(candidates: list[Path]) -> Path | None:
    for candidate in unique_paths(candidates):
        if candidate.exists():
            return candidate
    return None


def mounted_drive_roots() -> list[Path]:
    if os.name == 'nt':
        return [Path(f'{letter}:/') for letter in ascii_uppercase if Path(f'{letter}:/').exists()]
    mnt_root = Path('/mnt')
    if not mnt_root.exists():
        return []
    return [path for path in sorted(mnt_root.iterdir()) if len(path.name) == 1 and path.name.isalpha()]


def windows_user_homes() -> list[Path]:
    candidates: list[Path] = []
    userprofile = os.environ.get('USERPROFILE')
    if userprofile:
        candidates.append(Path(userprofile))
    for drive in mounted_drive_roots():
        users_root = drive / 'Users'
        if not users_root.exists():
            continue
        candidates.extend(path for path in users_root.iterdir() if path.is_dir())
    return unique_paths(candidates)


def bundle_path_for(app_root: Path) -> Path:
    return app_root / BUNDLE_RELATIVE_PATH


def discover_app_root(candidates: list[Path] | None = None) -> Path | None:
    matches = discover_app_roots(candidates)
    return matches[0] if matches else None


def discover_settings_file(candidates: list[Path] | None = None) -> Path | None:
    matches = discover_settings_files(candidates)
    return matches[0] if matches else None


def discover_app_roots(candidates: list[Path] | None = None) -> list[Path]:
    search_list = candidates if candidates is not None else default_app_roots()
    return [candidate for candidate in unique_paths(search_list) if bundle_path_for(candidate).exists()]


def discover_settings_files(candidates: list[Path] | None = None) -> list[Path]:
    search_list = candidates if candidates is not None else default_settings_files()
    return [candidate for candidate in unique_paths(search_list) if candidate.exists()]


def default_app_roots() -> list[Path]:
    candidates: list[Path] = []
    local_app_data = os.environ.get('LOCALAPPDATA')
    if local_app_data:
        local_programs = Path(local_app_data) / 'Programs'
        candidates.extend(local_programs / app_name for app_name in APP_NAMES)

    for variable_name in ('ProgramFiles', 'ProgramFiles(x86)'):
        variable_value = os.environ.get(variable_name)
        if variable_value:
            base_path = Path(variable_value)
            candidates.extend(base_path / app_name for app_name in APP_NAMES)

    for drive in mounted_drive_roots():
        for base_name in ('soft', 'Soft', 'Program Files', 'Program Files (x86)'):
            candidates.extend((drive / base_name / app_name) for app_name in APP_NAMES)

    for user_home in windows_user_homes():
        local_programs = user_home / 'AppData/Local/Programs'
        candidates.extend(local_programs / app_name for app_name in APP_NAMES)

    return unique_paths(candidates)


def default_settings_files() -> list[Path]:
    candidates: list[Path] = []
    appdata = os.environ.get('APPDATA')
    if appdata:
        appdata_path = Path(appdata)
        candidates.extend(appdata_path / app_name / 'User/settings.json' for app_name in APP_NAMES)

    for user_home in windows_user_homes():
        roaming_root = user_home / 'AppData/Roaming'
        candidates.extend(roaming_root / app_name / 'User/settings.json' for app_name in APP_NAMES)

    return unique_paths(candidates)


def resolve_app_root(app_root=None) -> Path:
    explicit_root = app_root or os.environ.get(APP_ROOT_ENV)
    if explicit_root is not None:
        root = Path(explicit_root)
        bundle = bundle_path_for(root)
        if not bundle.exists():
            raise FileNotFoundError(f'Bundle file not found: {bundle}')
        return root
    path = discover_app_root()
    if path is None:
        raise FileNotFoundError(
            f'Unable to locate Trae or Trae CN automatically. Pass --app-root or set {APP_ROOT_ENV}.'
        )
    return path


def resolve_settings_file(settings_file=None) -> Path:
    explicit_settings = settings_file or os.environ.get(SETTINGS_FILE_ENV)
    if explicit_settings is not None:
        return Path(explicit_settings)
    path = discover_settings_file()
    if path is None:
        raise FileNotFoundError(
            f'Unable to locate Trae or Trae CN settings.json automatically. Pass --settings-file or set {SETTINGS_FILE_ENV}.'
        )
    return path


def backup_pattern(path: Path) -> str:
    return f'{path.name}.{BACKUP_TAG}-*'


def find_backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(backup_pattern(path)), key=lambda item: item.stat().st_mtime, reverse=True)


def create_backup(path: Path) -> Path:
    backup = path.with_name(f'{path.name}.{BACKUP_TAG}-{timestamp()}')
    shutil.copy2(path, backup)
    return backup


def restore_from_backup(path: Path, backup=None) -> dict[str, object]:
    candidate = Path(backup) if backup else None
    if candidate is None:
        backups = find_backups(path)
        if not backups:
            raise FileNotFoundError(f'No backup found for {path}')
        candidate = backups[0]
    if not candidate.exists():
        raise FileNotFoundError(f'Backup file not found: {candidate}')
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, path)
    return {
        'target': str(path),
        'backup': str(candidate),
        'restored': True,
    }


def patch_bundle(app_root=None) -> dict[str, object]:
    root = resolve_app_root(app_root)
    bundle = bundle_path_for(root)
    text = bundle.read_text(encoding='utf-8')
    changed = False
    applied: list[str] = []
    for rule in PATCH_RULES:
        if rule.replacement in text:
            applied.append(rule.name)
            continue
        if rule.original not in text:
            raise RuntimeError(f'Patch rule not found in bundle: {rule.name}')
        text = text.replace(rule.original, rule.replacement, 1)
        applied.append(rule.name)
        changed = True
    backup = None
    if changed:
        backup = create_backup(bundle)
        bundle.write_text(text, encoding='utf-8')
    return {
        'bundle': str(bundle),
        'app_root': str(root),
        'app_name': root.name,
        'backup': str(backup) if backup else None,
        'changed': changed,
        'applied': applied,
        'backups': [str(item) for item in find_backups(bundle)],
    }


def restore_bundle(app_root=None, backup=None) -> dict[str, object]:
    root = resolve_app_root(app_root)
    bundle = bundle_path_for(root)
    payload = restore_from_backup(bundle, backup)
    payload['app_root'] = str(root)
    payload['app_name'] = root.name
    return payload


def inspect_bundle(app_root=None) -> dict[str, object]:
    try:
        root = resolve_app_root(app_root)
    except FileNotFoundError as exc:
        return {
            'bundle': None,
            'app_root': str(app_root) if app_root else None,
            'app_name': None,
            'exists': False,
            'rules': {},
            'backups': [],
            'error': str(exc),
        }
    bundle = bundle_path_for(root)
    text = bundle.read_text(encoding='utf-8')
    return {
        'bundle': str(bundle),
        'app_root': str(root),
        'app_name': root.name,
        'exists': True,
        'rules': {rule.name: rule.replacement in text for rule in PATCH_RULES},
        'backups': [str(item) for item in find_backups(bundle)],
    }


def ensure_local_agent_strategy(settings_file=None) -> dict[str, object]:
    path = resolve_settings_file(settings_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if path.exists():
        raw = path.read_text(encoding='utf-8-sig').strip()
        if raw:
            data = json.loads(raw)
    previous = data.get(STRATEGY_KEY)
    changed = previous != 'local'
    backup = create_backup(path) if path.exists() and changed else None
    data[STRATEGY_KEY] = 'local'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {
        'settings_file': str(path),
        'app_name': path.parent.parent.name,
        'backup': str(backup) if backup else None,
        'changed': changed,
        'previous': previous,
        'current': 'local',
        'backups': [str(item) for item in find_backups(path)] if path.exists() else [],
    }


def restore_settings(settings_file=None, backup=None) -> dict[str, object]:
    path = resolve_settings_file(settings_file)
    payload = restore_from_backup(path, backup)
    payload['app_name'] = path.parent.parent.name
    return payload


def inspect_settings(settings_file=None) -> dict[str, object]:
    try:
        path = resolve_settings_file(settings_file)
    except FileNotFoundError as exc:
        return {
            'settings_file': str(settings_file) if settings_file else None,
            'app_name': None,
            'exists': False,
            'strategy': None,
            'backups': [],
            'error': str(exc),
        }
    raw = path.read_text(encoding='utf-8-sig').strip() if path.exists() else ''
    data = json.loads(raw) if raw else {}
    return {
        'settings_file': str(path),
        'app_name': path.parent.parent.name,
        'exists': path.exists(),
        'strategy': data.get(STRATEGY_KEY),
        'backups': [str(item) for item in find_backups(path)] if path.exists() else [],
    }


def list_backups(app_root=None, settings_file=None) -> dict[str, object]:
    bundle_info = inspect_bundle(app_root)
    settings_info = inspect_settings(settings_file)
    return {
        'bundle': bundle_info.get('backups', []),
        'settings': settings_info.get('backups', []),
    }


def doctor(app_root=None, settings_file=None) -> dict[str, object]:
    bundle_info = inspect_bundle(app_root)
    settings_info = inspect_settings(settings_file)
    suggestions: list[str] = []

    bundle_ready = bundle_info.get('exists') and all(bundle_info.get('rules', {}).values())
    settings_ready = settings_info.get('exists') and settings_info.get('strategy') == 'local'

    if bundle_info.get('error'):
        suggestions.append(
            f'Check the Trae or Trae CN installation path, pass --app-root, or set {APP_ROOT_ENV}.'
        )
    elif not bundle_ready:
        suggestions.append('Run trae-patch patch-bundle or trae-patch patch-all to apply the client bundle patch.')

    if settings_info.get('error'):
        suggestions.append(
            f'Check the Trae or Trae CN settings path, pass --settings-file, or set {SETTINGS_FILE_ENV}.'
        )
    elif not settings_ready:
        suggestions.append('Run trae-patch patch-settings or trae-patch patch-all to force local request routing.')

    if bundle_ready and settings_ready:
        suggestions.append('Client patch is ready. Configure your gateway in Trae or Trae CN and only use relay if your gateway breaks tool-call history.')

    return {
        'ready': bool(bundle_ready and settings_ready),
        'bundle_ready': bool(bundle_ready),
        'settings_ready': bool(settings_ready),
        'bundle': bundle_info,
        'settings': settings_info,
        'suggestions': suggestions,
    }


def patch_all(app_root=None, settings_file=None) -> dict[str, object]:
    return {
        'bundle': patch_bundle(app_root=app_root),
        'settings': ensure_local_agent_strategy(settings_file=settings_file),
    }


def restore_all(app_root=None, settings_file=None, bundle_backup=None, settings_backup=None) -> dict[str, object]:
    return {
        'bundle': restore_bundle(app_root=app_root, backup=bundle_backup),
        'settings': restore_settings(settings_file=settings_file, backup=settings_backup),
    }


def inspect(app_root=None, settings_file=None) -> dict[str, object]:
    return {
        'bundle': inspect_bundle(app_root),
        'settings': inspect_settings(settings_file),
    }
