"""Exercise the shared manager against a private test copy (no Steam launch or UI)."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch
from contextlib import nullcontext

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import hlx_fsr_release as hlx
from library import ident, safe_root
from manager import Manager


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['status', 'install', 'repair', 'enable', 'disable', 'remove', 'recover', 'settings'])
    ap.add_argument('folder', type=Path, help='An isolated test copy of an installed game')
    ap.add_argument('--settings-dir', required=True, type=Path)
    ap.add_argument('--accept-terms', action='store_true', help='Accept the official 3.2.0 license and notices for this test')
    ap.add_argument('--archive', type=Path, help='Local copy of the official ZIP; all normal verification still runs')
    ap.add_argument('--scaler', action='store_true', help='Explicitly select the Scaler route when installing')
    ap.add_argument('--dx12', action='store_true', help='Confirm that the selected Scaler game runs in DirectX 12')
    ap.add_argument('--executable', help='Relative game executable for a Scaler installation')
    ap.add_argument('--set', action='append', default=[], metavar='SETTING=VALUE')
    args = ap.parse_args()
    root = safe_root(args.folder.resolve())
    mgr = Manager(Path.home(), args.settings_dir.resolve())
    gid = ident('hlx-trial', root)
    game = dict(folder=str(root), id=gid, name=root.name, source='Imported')
    mgr.entries[gid] = game
    if args.action == 'install':
        if not args.accept_terms:
            ap.error('Read the upstream LICENSE and THIRD_PARTY_NOTICES.md; installation requires --accept-terms.')
        if args.scaler:
            existing = mgr.record(game)
            if existing and existing.get('route') != 'optiscaler':
                ap.error('Remove the installed direct route before selecting Scaler')
            if not existing:
                mgr.set_installation_route(gid, 'optiscaler')
        review = mgr.preview_latest(gid, dx12_confirmed=args.dx12, variant_id=hlx.VARIANT_ID,
                                    executable=args.executable, release_choice='reviewed-3.2.0')
        print(json.dumps(review, indent=2), flush=True)
        mgr.accept_license(True, review['token'])
        # Test transport only. No change to the production downloader or integrity checks.
        local = patch('manager.urllib.request.urlopen', side_effect=lambda req, **kw:
                      args.archive.open('rb') if req.full_url == hlx.RELEASE_URL else
                      (_ for _ in ()).throw(ValueError('Unexpected URL during offline trial'))) if args.archive else nullcontext()
        with local:
            job = mgr.execute_latest(review['token'])
            mgr.worker.join()
        job = mgr.jobs[job['id']]
        print(json.dumps(job, indent=2))
        if job['state'] != 'completed':
            return 1
    elif args.action == 'settings':
        saved = mgr.game_settings(game)
        if args.set:
            changes = dict(x.split('=', 1) for x in args.set)
            if 'multiplier' in changes:
                changes['multiplier'] = int(changes['multiplier'])
            mgr.set_game_settings(gid, changes, saved['revision'])
            saved = mgr.game_settings(game)
        print(json.dumps(saved, indent=2))
    elif args.action != 'status':
        review = mgr.preview(gid, args.action)
        print(json.dumps(review, indent=2), flush=True)
        print(json.dumps(mgr.execute(review['token']), indent=2))
    status = mgr.assess(game)
    keys = ('route', 'compatibility', 'reasons', 'installed_model', 'installed_variant',
            'installed_version', 'enabled', 'repair_files', 'recovery_available', 'targets')
    print(json.dumps({k: status.get(k) for k in keys}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
