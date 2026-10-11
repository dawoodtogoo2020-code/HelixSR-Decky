"""Read-only, shared explanation of a game's installation assessment.

This module does not decide whether a transaction may run. Existing manager
guards remain the authority for every file change.
"""
import json
import re

RUNNING_REASON = 'Game is running; close it before any file changes'
ADVISORY_CODES = frozenset({'dx12_unconfirmed', 'legacy_installation'})


def _steam_build_steps(game):
    steps = [
        'HelixSR file changes stay blocked after this game build change. Install, Update, Disable, and Remove cannot safely change old files; Remove would restore saved originals from the recorded build, which may replace files from the current build.',
        'Let Steam finish updating, close the game normally, then refresh the game status.',
        'Steam file verification may restore current game files, but does not reconcile HelixSR\'s installation receipt.',
    ]
    report = game.get('steam_build_review')
    if isinstance(report, dict):
        recorded, current = report.get('recorded_build'), report.get('current_build')
        if (isinstance(recorded, str) and isinstance(current, str)
                and re.fullmatch(r'(?:[0-9]+|unavailable)', recorded)
                and re.fullmatch(r'(?:[0-9]+|unavailable)', current)):
            steps.insert(0, f'Recorded Steam build: {recorded}; current Steam build: {current}.')
        states = {'installed bytes match', 'saved-original bytes match', 'missing',
                  'externally changed', 'retained configuration'}
        files = report.get('files')
        if isinstance(files, list):
            for item in files[:20]:
                if not isinstance(item, dict):
                    continue
                path, state = item.get('path'), item.get('state')
                if (not isinstance(path, str) or not path or not isinstance(state, str)
                        or state not in states or path.startswith(('/', '\\'))
                        or any(part in ('', '.', '..') for part in path.replace('\\', '/').split('/'))
                        or ':' in path or any(ord(char) < 32 for char in path)):
                    continue
                steps.append(f'Recorded file {json.dumps(path, ensure_ascii=True)}: {state}.')
        omitted = report.get('omitted_files')
        if type(omitted) is int and omitted > 0:
            steps.append(f'{omitted} more recorded files omitted from this check.')
    steps.append('Report the recorded and current Steam build IDs and relative file states for review; say if any are unavailable. Do not edit game_build, delete installation receipts, or bypass this guard.')
    return steps


def _issue(reason, game=None):
    """Classify a manager diagnostic without altering its original wording."""
    lower = reason.lower()
    if reason == RUNNING_REASON:
        return ('game_running', 'Game running',
                ['Close the game normally before changing its files, then refresh.'])
    if 'anti-cheat' in lower:
        return ('anti_cheat', 'Anti-cheat restriction',
                ['Keep HelixSR installation blocked for this game.'])
    if 'steam download staging' in lower or 'steam install/update is not complete' in lower:
        return ('steam_update', 'Steam update in progress',
                ['Let Steam finish the installation or update, then refresh.'])
    if 'managed files changed' in lower or 'ownership needs review' in lower:
        return ('managed_files_changed', 'Managed files changed',
                ['The file no longer matches the bytes recorded by HelixSR. This is not a Linux owner or administrator check.',
                 'If another mod changed it, use that mod\'s own restore option, then refresh. Otherwise report the named file and your app version for a safe review.',
                 'Update and Remove stay blocked until the recorded files match; do not delete DLLs or the installation record.'])
    if 'steam build changed' in lower:
        return ('steam_build_changed', 'Steam build changed',
                _steam_build_steps(game or {}))
    if 'existing unmanaged injector/configuration' in lower:
        return ('unmanaged_injector', 'Existing injector or configuration',
                ['Review the named files with the tool that installed them before using HelixSR.'])
    if 'unmanaged original dll backup' in lower:
        return ('unmanaged_backup', 'Unmanaged original DLL backup',
                ['Identify the backup and the tool that created it before installing HelixSR.'])
    if 'existing direct helixsr installation' in lower:
        return ('legacy_installation', 'Existing HelixSR installation',
                ['Use the explicit import flow to adopt this installation before managing it.'])
    if 'main executable is not x64' in lower or 'selected executable' in lower or 'select an eligible' in lower:
        return ('executable_selection', 'Executable needs review',
                ['Choose the x64 Windows game executable that the game actually launches, then refresh.'])
    if 'dx12 is not confirmed' in lower:
        return ('dx12_unconfirmed', 'DX12 needs confirmation',
                ['Select DX12 in the game and confirm that it actually runs with DX12 before installation.'])
    if 'x86_64 host' in lower or 'expected x64 fidelityfx' in lower or 'no supported dlss' in lower:
        return ('unsupported_route', 'Supported route unavailable',
                ["Review this game's architecture and supported upscaler files."])
    if 'without root permissions' in lower:
        return ('root_host', 'Unsupported host context',
                ['Run the plugin in the normal Steam user session.'])
    if 'permission' in lower or 'access denied' in lower or 'read' in lower and 'failed' in lower:
        return ('file_access', 'File access failed',
                ['Restore normal access to the named path, then rescan.',
                 'Treat any previously recorded installation as unverified until the scan succeeds.'])
    return ('review_required', 'Review required',
            ['Review the exact diagnostic and rescan after resolving it.'])


def installation_status(game):
    """Return an additive UI status; leave compatibility and reasons untouched."""
    reasons = [reason for reason in game.get('reasons', []) if isinstance(reason, str) and reason]
    running = RUNNING_REASON in reasons or bool(game.get('processes'))
    if running and RUNNING_REASON not in reasons:
        # Awareness may observe a process after the earlier mutation check.
        # Keep raw reasons unchanged, but show the observed running process.
        reasons.insert(0, RUNNING_REASON)
    # A recovery journal is a blocker even if assessment failed before it
    # could collect ordinary game evidence.
    recovery = bool(game.get('recovery_available'))
    compatibility = game.get('compatibility')
    material = compatibility == 'blocked' or recovery
    issues = []
    for reason in reasons:
        code, title, steps = _issue(reason, game)
        issues.append(dict(code=code, title=title, reason=reason, steps=steps,
                           blocking=(material or running) and code not in ADVISORY_CODES))
    if recovery:
        issues.insert(0, dict(code='recovery_needed', title='Recovery needed',
                              reason='An interrupted HelixSR transaction needs recovery.',
                              steps=['Close the game and let Steam finish any update.',
                                     'Use Recover and review its file list before applying it.'],
                              blocking=True))

    other_material = material and (recovery or any(
        issue['code'] not in ADVISORY_CODES | {'game_running'} for issue in issues))
    if recovery:
        state, label = 'recovery', 'Recovery needed'
    elif compatibility == 'unsupported':
        state, label = 'unsupported', 'Unsupported'
    elif other_material or compatibility == 'blocked' and not running:
        state, label = 'review', ('Choose executable' if game.get('executable_selection_needed')
                                  else 'Needs review')
    elif running:
        state, label = 'running', 'Game running'
    else:
        state, label = 'ready', ('Enabled' if game.get('managed') and game.get('enabled') else
                               'Disabled' if game.get('managed') else
                               'Existing HelixSR' if game.get('legacy') else 'Not installed')

    if state == 'running':
        summary = 'File changes paused until the game closes.'
    elif state in ('review', 'unsupported', 'recovery'):
        primary = next((i for i in issues if i['code'] not in ('game_running', 'dx12_unconfirmed')),
                       issues[0] if issues else None)
        summary = primary['reason'] if primary else 'Review the game assessment before making changes.'
    elif issues:
        summary = issues[0]['reason']
    else:
        summary = 'Ready for review and file changes.'

    selectable = (compatibility == 'candidate' or state == 'running' or bool(game.get('managed'))
                  or recovery or bool(game.get('executable_selection_needed')))
    return dict(state=state, label=label, summary=summary, running=running,
                selectable=selectable, can_modify=state == 'ready', issues=issues)
