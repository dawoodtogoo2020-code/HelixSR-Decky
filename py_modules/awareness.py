"""Read-only source-aware OptiScaler and frame-generation evidence."""
from pathlib import Path
import configparser
import json
import os
import re
import time
from library import text, read_json, vdf, steam_roots


def flag(value):
    s = str(value).strip().lower()
    if s in ('true', 'on', 'yes', '1', 'enabled'):
        return True
    if s in ('false', 'off', 'no', '0', 'disabled'):
        return False
    return None


def evidence(source, key, value, path, meaning='configured'):
    return dict(source=source, key=key, value=str(value), enabled=flag(value), path=str(path), meaning=meaning)


def profile_records(source):
    try:
        import tomllib
        return tomllib.loads(source).get('profile', [])
    except (ImportError, ValueError):
        records = []
        for block in re.split(r'(?m)^\[\[profile\]\]', source)[1:]:
            record = {}
            for key, value in re.findall(r'(?m)^\s*(\w+)\s*=\s*([^\r\n#]+)', block):
                value = value.strip()
                try:
                    record[key] = json.loads(value)
                except ValueError:
                    record[key] = value.strip("'\"")
            records.append(record)
        return records


def launch_options(home, appid):
    if not appid:
        return ''
    for root in steam_roots(home):
        for p in (root / 'userdata').glob('*/config/localconfig.vdf'):
            try:
                d = vdf(text(p))
                for k in ['UserLocalConfigStore', 'Software', 'Valve', 'Steam', 'apps', str(appid)]:
                    d = d.get(k, {})
                if isinstance(d, dict) and d.get('LaunchOptions'):
                    return str(d['LaunchOptions'])
            except ValueError:
                pass
    return ''


def active_processes(folder, appid=''):
    out = []
    root = Path(folder).resolve()
    if not Path('/proc').is_dir():
        return out
    for p in Path('/proc').glob('[0-9]*'):
        try:
            if p.stat().st_uid != os.getuid():
                continue
            env = (p / 'environ').read_bytes()
            values = dict(item.split(b'=', 1) for item in env.split(b'\0') if b'=' in item)
            sid = values.get(b'SteamAppId', values.get(b'SteamGameId', b'')).decode(errors='replace')
            if sid.isdigit() and int(sid) > 0xffffffff:
                sid = str((int(sid) >> 32) & 0xffffffff)
            cmd = (p / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            # Avoid matching the scanner itself and launcher clients.
            is_game = '.exe' in cmd.lower() and 'helixsr_setup' not in cmd and 'dxc.exe' not in cmd.lower()
            try:
                cwd = (p / 'cwd').resolve()
                inside = cwd == root or root in cwd.parents
            except OSError:
                inside = False
            if is_game and ((appid and sid == str(appid)) or inside or str(root) + '/' in cmd):
                runtime = {k.decode(): v.decode(errors='replace') for k, v in values.items()
                           if k.decode(errors='ignore') in ['WINEDLLOVERRIDES', 'DISABLE_MAKO', 'DISABLE_LSFGVK',
                                                           'DISABLE_LSFG', 'ENABLE_LSFG', 'LSFG_MULTIPLIER']}
                started = 0
                try:
                    statline = (p / 'stat').read_text().rsplit(')', 1)[1].split()
                    ticks = float(statline[19])
                    uptime = float(Path('/proc/uptime').read_text().split()[0])
                    started = time.time() - uptime + ticks / os.sysconf('SC_CLK_TCK')
                except (OSError, ValueError, IndexError):
                    pass
                out.append(dict(pid=int(p.name), env=runtime, started_at=started))
        except (OSError, ValueError):
            continue
    return out


def awareness(game, tree, home, route, target=None):
    fg, opti_files, configs, logs = [], [], [], []
    for d, names in tree:
        for name in names:
            lower = name.lower()
            p = d / name
            if lower == 'optiscaler.ini':
                configs.append(p)
                section = re.search(r'(?ims)^\[FrameGen\]\s*(.*?)(?=^\[|\Z)', text(p, 256 << 10))
                if section:
                    value = re.search(r'(?im)^\s*Enabled\s*=\s*([^\r\n;]+)', section[1])
                    if value:
                        fg.append(evidence('OptiScaler', 'FrameGen.Enabled', value[1].strip(), p))
            if lower in ('dxgi.dll', 'winmm.dll', 'version.dll', 'dbghelp.dll', 'd3d12.dll', 'optiscaler.asi'):
                try:
                    with p.open('rb') as f:
                        if b'OptiScaler' in f.read(32 << 20):
                            opti_files.append(str(p))
                except OSError:
                    pass
            if lower in ('config.ini', 'user.settings', 'dx12user.settings', 'engine.ini', 'gameusersettings.ini', 'optiscaler.ini'):
                src = text(p, 256 << 10)
                for k, value in re.findall(r'(?im)^\s*([^;#\r\n=]*(?:framegen|framegeneration|dlssg|xessfg|fginput|fgoutput)[^=\r\n]*)\s*=\s*([^\r\n;]+)', src):
                    source = 'OptiScaler' if lower == 'optiscaler.ini' else 'Native game'
                    fg.append(evidence(source, k.strip(), value.strip(), p))
            for lp in (d / 'helixsr.log', d / 'HelixSR/helixsr.log', d / 'OptiScaler.log'):
                if lp.is_file() and str(lp) not in [x['path'] for x in logs]:
                    logs.append(dict(path=str(lp), modified=lp.stat().st_mtime,
                                     excerpt=text_tail(lp)))
    options = game.get('launch_options') or launch_options(home, game.get('appid'))
    if options:
        for feature, pattern in [('MAKO', r'mako'), ('LSFG-VK', r'lsfg|lossless'), ('OptiScaler proxy override', r'WINEDLLOVERRIDES')]:
            if re.search(pattern, options, re.I):
                fg.append(evidence(feature, 'Steam launch route', 'present; activation unknown', 'Steam launch options', 'launch route'))
    h, appid = Path(home), str(game.get('appid', ''))
    mako = h / '.config/mako-render/conf.toml'
    metadata = read_json(h / '.config/mako-render/profile-metadata.json').get('profiles', {})
    associated = set()
    exenames = {n.lower() for _, ns in tree for n in ns if n.lower().endswith('.exe')}
    for name, meta in metadata.items():
        if (appid and str(meta.get('steam_app_id')) == appid or
                any(str(p).lower() in exenames for p in meta.get('captured_processes', []))):
            associated.add(name)
    if re.search(r'mako', options, re.I):
        match = re.search(r'--profile\s+["\']?([^\s"\']+)', options)
        if match:
            associated.add(match[1])
    # Known per-game shell case records: inspect static values, never execute wrappers.
    wrapper = h / '.lsfg'
    if appid and '.lsfg' in options:
        blocks = re.findall(r'(?ms)^\s*' + re.escape(appid) + r'\)\s*(.*?)^\s*;;', text(wrapper, 512 << 10))
        for block in blocks:
            match = re.search(r'(?:MAKO_PROFILE=|--profile\s+)["\']?([^\s"\']+)', block)
            if match:
                associated.add(match[1])
            for key, value in re.findall(r'\b(DISABLE_MAKO|DISABLE_LSFGVK|DISABLE_LSFG)=["\']?(\w+)', block):
                e = evidence('Per-game wrapper', key, value, wrapper, 'configured launch environment')
                if e['enabled'] is not None:
                    e['enabled'] = not e['enabled']
                fg.append(e)
    for profile in profile_records(text(mako)):
        if profile.get('name') in associated:
            for key in ('frame_generation_enabled', 'frame_generation_provisioned', 'multiplier'):
                if key in profile:
                    fg.append(evidence('MAKO', key, profile[key], mako))
    lsfg = h / '.config/lsfg-vk/conf.toml'
    for profile in profile_records(text(lsfg)):
        active = profile.get('active_in', [profile.get('exe', '')])
        if not isinstance(active, list):
            active = []
        if (appid and appid in [str(x) for x in active]) or any(str(x).lower() in exenames for x in active):
            multiplier = profile.get('multiplier')
            if isinstance(multiplier, (int, float)):
                e = evidence('LSFG-VK', 'multiplier', multiplier, lsfg)
                e['enabled'] = multiplier > 1
                fg.append(e)
    processes = active_processes(game['folder'], appid)
    for proc in processes:
        for k, value in proc['env'].items():
            e = evidence('Running process', k, value, f'PID {proc["pid"]}', 'runtime environment')
            if k.startswith('DISABLE_') and e['enabled'] is not None:
                e['enabled'] = not e['enabled']
            fg.append(e)
    opti_runtime = 'unknown'
    for proc in processes:
        maps = text(Path('/proc') / str(proc['pid']) / 'maps', 4 << 20)
        if any(p in maps for p in opti_files):
            opti_runtime = 'module mapped (rendering involvement unverified)'
    evidence_state = 'unknown'
    starts = [p.get('started_at', 0) for p in processes]
    started = min(starts, default=0)
    managed_disabled = game.get('managed') and game.get('enabled') is False
    fresh = [x for x in logs if processes and started > 0 and not managed_disabled and
             x['modified'] >= started and time.time() - x['modified'] < 120]
    helix_fresh = [x for x in fresh if x['path'].lower().endswith('helixsr.log')]
    if any(re.search(r'fallback|network (?:not|failed)|cannot|red border', x['excerpt'], re.I) for x in helix_fresh):
        evidence_state = 'current log reports failure/fallback; inspect log'
    elif any(re.search(r'network running|launches per frame|output directly', x['excerpt'], re.I) for x in helix_fresh):
        evidence_state = 'recent running-process log reports neural output; visual/stability check required'
    elif any(x['path'].lower().endswith('helixsr.log') for x in logs):
        evidence_state = 'historical log available; current runtime unverified'
    configured_helix = any(re.search(r'(?im)^\s*FfxDx12(?:SR)?Path\s*=\s*[^\r\n]*helixsr', text(p)) for p in configs)
    return dict(optiscaler=dict(present=bool(opti_files or configs), dlls=opti_files,
                               configs=[str(p) for p in configs], involved=route == 'optiscaler' or configured_helix,
                               helix_configured=configured_helix, runtime=opti_runtime),
                framegen=fg, framegen_summary='No supported per-game evidence' if not fg else 'See source-specific evidence below',
                helix_runtime=evidence_state, processes=processes, logs=logs,
                launch_options=options, observed_at=time.time())


def text_tail(path, limit=16384):
    try:
        with Path(path).open('rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - limit))
            return f.read(limit).decode(errors='replace')
    except OSError:
        return ''
