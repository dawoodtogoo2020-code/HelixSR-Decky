"""Read-only packaged runtime probe; game folders and user paths are omitted."""
import argparse
import json
from pathlib import Path
from .backend import DesktopBackend
from .version import VERSION


def main(argv):
    parser = argparse.ArgumentParser(description='Read-only HelixSR desktop diagnostics')
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--home')
    parser.add_argument('--settings')
    parser.add_argument('--output')
    parser.add_argument('--check-updates', action='store_true')
    args = parser.parse_args(argv)
    if args.output and not Path(args.output).is_absolute():
        parser.error('--output must be an absolute path')
    service = DesktopBackend(args.home, args.settings)
    try:
        library = service.library()
        games = []
        for game in library['games']:
            entry = {k: game.get(k) for k in ('name', 'source', 'compatibility', 'route', 'managed', 'enabled')}
            if game.get('managed') or game.get('compatibility') == 'candidate':
                detail = service.details(game['id'])
                entry.update({k: detail.get(k) for k in ('version', 'prepared_version', 'helix_runtime', 'framegen_summary')})
            games.append(entry)
        system = service.system_status()
        system['vulkan'].pop('evidence', None)
        report = dict(app_version=VERSION, games=games, detected=len(games),
                      candidates=sum(g.get('compatibility') == 'candidate' for g in games),
                      system=system, warnings_count=len(library.get('warnings', [])))
        if args.check_updates:
            report['helix_update'] = service.check_helix_updates(True)
            report['app_update'] = service.check_app_updates(True)
        payload = json.dumps(report, indent=2)
        if args.output:
            Path(args.output).write_text(payload + '\n', encoding='utf-8')
        else:
            print(payload)
        return 0
    finally:
        service.close()
