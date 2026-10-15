"""Optional game-resource labels. Cosmetic state never proves upscaler execution."""
import hashlib
import os
from pathlib import Path
import stat

from menu_label_profiles import LABEL, WITCHER_XML, patch_witcher3, profile_for

LIMIT = 128 << 10
ACTIONS = ('labels_enable', 'labels_disable')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_resource(path):
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT
                or os.name == 'posix' and info.st_uid != os.getuid()):
            raise ValueError('Unsafe menu resource type, owner, size or hardlink')
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Menu resource exceeds size limit')
    return raw


def process_scan_ready():
    """A missing/unreadable user process view is unknown, never a closed game."""
    proc = Path('/proc')
    if os.name != 'posix' or not (proc / 'self').is_dir():
        raise ValueError('Menu changes require a readable Linux process view; game state is unknown')
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            with (entry / 'cmdline').open('rb') as stream:
                if len(stream.read(65537)) > 65536:
                    raise ValueError('User process command line exceeds inspection limit')
            os.readlink(entry / 'exe')
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as exc:
            raise ValueError('User process inspection incomplete; close games and retry') from exc


def checked_receipt(rec):
    value = rec.get('menu_labels')
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get('enabled')) is not bool
            or value.get('path') != str(Path(WITCHER_XML))
            or not isinstance(value.get('profile'), str)
            or value['path'] not in rec.get('baseline', {})
            or value['path'] not in rec.get('current', {})
            or value.get('original_sha256') != rec['baseline'][value['path']]):
        raise ValueError('Invalid menu-label ownership record')
    for key in ('original_sha256', 'patched_sha256'):
        value_hash = value.get(key)
        if not isinstance(value_hash, str) or len(value_hash) != 64 or any(c not in '0123456789abcdef' for c in value_hash):
            raise ValueError('Invalid menu-label digest')
    return value


def inspect(manager, game, data, rec, detailed=True):
    profile = profile_for(game, data.get('route'))
    state = dict(supported=bool(profile['supported']), available=False, enabled=False,
                 label=LABEL, reason=profile['reason'], path=profile.get('path'),
                 profile=profile['id'], resource_sha256=None, experimental=True)
    saved = checked_receipt(rec)
    if saved:
        state['enabled'] = saved['enabled']
    if not detailed:
        state['reason'] = 'Select this game to inspect its optional menu labels.'
        return state
    if not profile['supported']:
        return state
    rel = str(Path(profile['path']))
    path = manager.checked_menu_path(game, rel)
    raw = read_resource(path)
    state.update(path=rel, resource_sha256=digest(raw))
    if saved:
        if saved['profile'] != profile['id']:
            raise ValueError('Menu-label profile changed; review required')
        original = read_resource(manager.checked_menu_original(game, rel))
        if digest(original) != saved['original_sha256']:
            raise ValueError('Menu-label original is missing or changed')
        # Older clients restore all tracked files but do not know this flag.
        # Trust restored bytes only when their current receipt agrees too.
        if (saved['enabled'] and rec['current'][rel] == saved['original_sha256']
                and state['resource_sha256'] == saved['original_sha256']):
            state['enabled'] = False
        expected = saved['patched_sha256'] if state['enabled'] else saved['original_sha256']
        if digest(raw) != expected:
            raise ValueError('Menu resource changed outside this installation; automatic replacement is blocked')
        if digest(patch_witcher3(original)) != saved['patched_sha256']:
            raise ValueError('Menu-label transformation changed; review required')
    else:
        patch_witcher3(raw)
        original_path = manager.checked_menu_original(game, rel)
        if original_path.exists() and digest(read_resource(original_path)) != state['resource_sha256']:
            raise ValueError('Menu original backup conflicts with current source')
    if not rec or not rec.get('enabled'):
        state['reason'] = 'Enable a managed HelixSR installation first. Menu labels are off by default.'
    elif data.get('compatibility') != 'candidate' or data.get('recovery_available'):
        state['reason'] = 'Resolve this game\'s file, build or running-state checks before changing menu labels.'
    else:
        try:
            manager.menu_process_guard(game)
        except (OSError, ValueError) as exc:
            state['reason'] = str(exc)
        else:
            state.update(available=True, reason='Optional cosmetic FSR menu label. Original bytes are restored when disabled. Menu appearance still needs in-game confirmation.')
    return state


def new_original_intent(journal):
    """Validate durable ownership of a backup created by an interrupted opt-in."""
    intent = journal.get('new_menu_original')
    if intent is None:
        return None
    rel = str(Path(WITCHER_XML))
    if (not isinstance(intent, dict) or intent.get('path') != rel
            or rel in journal.get('previous', {}).get('baseline', {})
            or journal.get('before', {}).get(rel) != intent.get('sha256')):
        raise ValueError('Invalid new menu-original ownership journal')
    value = intent.get('sha256')
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid new menu-original journal digest')
    return intent


def plan(manager, game, data, rec, action):
    state = inspect(manager, game, data, rec)
    if not state['available']:
        raise ValueError(state['reason'])
    if (action == 'labels_enable') == state['enabled']:
        raise ValueError('Menu labels are already in the requested state')
    rel = state['path']
    if action == 'labels_disable':
        raw = read_resource(manager.checked_menu_original(game, rel))
    else:
        raw = read_resource(manager.checked_menu_path(game, rel))
    return dict(path=rel, profile=state['profile'],
                original=raw, payload=patch_witcher3(raw) if action == 'labels_enable' else raw)
