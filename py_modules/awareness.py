"""Read-only source-aware OptiScaler and frame-generation evidence."""
from pathlib import Path
import configparser
import json
import os
import re
import stat
import time
from library import text, read_json, vdf, steam_roots
from optiscaler_setup import setup_report

OPTISCALER_PROXIES = ('dxgi.dll', 'winmm.dll', 'version.dll', 'dbghelp.dll',
                     'd3d12.dll', 'wininet.dll', 'winhttp.dll', 'optiscaler.asi')


def optiscaler_proxy(path):
    """Identify supported proxy aliases without treating ordinary game DLLs as injectors."""
    path = Path(path)
    if path.name.lower() not in OPTISCALER_PROXIES or path.is_symlink() or not path.is_file():
        return False
    try:
        with path.open('rb') as stream:
            return b'OptiScaler' in stream.read(32 << 20)
    except OSError:
        return False


def flag(value):
    s = str(value).strip().lower()
    if s in ('true', 'on', 'yes', '1', 'enabled'):
        return True
    if s in ('false', 'off', 'no', '0', 'disabled'):
        return False
    return None


def evidence(source, key, value, path, meaning='configured'):
    return dict(source=source, key=key, value=str(value), enabled=flag(value), path=str(path), meaning=meaning)


def profile_records(source, warnings=None, label='Frame-generation profile data'):
    """Return only schema-safe TOML profile mappings from optional local files."""
    warnings = warnings if warnings is not None else []
    if not source.strip():
        return []
    try:
        import tomllib
        parsed = tomllib.loads(source)
    except ValueError:
        warnings.append(f'{label} is malformed; configuration is unknown')
        return []
    except ImportError:
        warnings.append(f'{label}: using limited profile parsing because TOML support is unavailable')
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
    else:
        records = parsed.get('profile', []) if isinstance(parsed, dict) else []
    if not isinstance(records, list):
        warnings.append(f'{label} has an invalid profile list')
        return []
    clean = []
    for record in records:
        if not isinstance(record, dict):
            warnings.append(f'{label} has a non-mapping profile entry')
            continue
        record = dict(record)
        if 'name' in record and not isinstance(record['name'], str):
            warnings.append(f'{label} profile name must be text')
            record.pop('name')
        clean.append(record)
    return clean


def launch_options(home, appid, warnings=None):
    """Read a Steam launch option only from the expected mapping structure."""
    warnings = warnings if warnings is not None else []
    if not appid:
        return ''
    for root in steam_roots(home):
        try:
            configs = (root / 'userdata').glob('*/config/localconfig.vdf')
            for p in configs:
                try:
                    d = vdf(text(p))
                    for k in ['UserLocalConfigStore', 'Software', 'Valve', 'Steam', 'apps', str(appid)]:
                        if not isinstance(d, dict):
                            warnings.append(f'Steam launch options have an invalid VDF structure: {p}')
                            d = None
                            break
                        d = d.get(k, {})
                    if d is not None and not isinstance(d, dict):
                        warnings.append(f'Steam launch options have an invalid VDF structure: {p}')
                    elif isinstance(d, dict) and d.get('LaunchOptions'):
                        if isinstance(d['LaunchOptions'], str):
                            return d['LaunchOptions']
                        warnings.append(f'Steam launch options must be text: {p}')
                except ValueError:
                    warnings.append(f'Steam launch options are malformed: {p}')
        except OSError:
            warnings.append(f'Steam launch options cannot be read: {root}')
            continue
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
    fg, opti_files, configs, logs, awareness_warnings = [], [], [], [], []
    for d, names in tree:
        for name in names:
            lower = name.lower()
            p = d / name
            if lower == 'optiscaler.ini' and (p.is_symlink() or not p.is_file()):
                continue
            if lower == 'optiscaler.ini':
                configs.append(p)
                section = re.search(r'(?ims)^\[FrameGen\]\s*(.*?)(?=^\[|\Z)', text(p, 256 << 10))
                if section:
                    value = re.search(r'(?im)^\s*Enabled\s*=\s*([^\r\n;]+)', section[1])
                    if value:
                        fg.append(evidence('OptiScaler', 'FrameGen.Enabled', value[1].strip(), p))
            if optiscaler_proxy(p):
                opti_files.append(str(p))
            if lower in ('config.ini', 'user.settings', 'dx12user.settings', 'engine.ini', 'gameusersettings.ini', 'optiscaler.ini'):
                src = text(p, 256 << 10)
                for k, value in re.findall(r'(?im)^\s*([^;#\r\n=]*(?:framegen|framegeneration|dlssg|xessfg|fginput|fgoutput|fgnvngxreplacement|fgpreset|quickflow)[^=\r\n]*)\s*=\s*([^\r\n;]+)', src):
                    source = 'OptiScaler' if lower == 'optiscaler.ini' else 'Native game'
                    fg.append(evidence(source, k.strip(), value.strip(), p))
        # Log candidates belong to a directory, not each asset inside it. Avoid
        # thousands of identical existence/symlink checks in large game folders.
        candidates = [d / 'helixsr.log', d / 'OptiScaler.log']
        # HelixSR's managed subfolders live beside the game executable. Do not
        # probe those subfolders again for every directory in the scanned tree.
        if d in (Path(game['folder']), Path(target) if target else None):
            candidates.extend((d / 'HelixSR/helixsr.log', d / 'HelixSR-fsrfg/helixsr.log'))
        for lp in candidates:
            if str(lp) not in [x['path'] for x in logs] and safe_log(lp, game['folder']):
                logs.append(dict(path=str(lp), modified=lp.stat().st_mtime,
                                 excerpt=text_tail(lp)))
    options = game.get('launch_options') or launch_options(home, game.get('appid'), awareness_warnings)
    if options:
        for feature, pattern in [('MAKO', r'mako'), ('LSFG-VK', r'lsfg|lossless'), ('OptiScaler proxy override', r'WINEDLLOVERRIDES')]:
            if re.search(pattern, options, re.I):
                fg.append(evidence(feature, 'Steam launch route', 'present; activation unknown', 'Steam launch options', 'launch route'))
    h, appid = Path(home), str(game.get('appid', ''))
    mako = h / '.config/mako-render/conf.toml'
    metadata = read_json(h / '.config/mako-render/profile-metadata.json')
    metadata = metadata.get('profiles', {}) if isinstance(metadata, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    associated = set()
    exenames = {n.lower() for _, ns in tree for n in ns if n.lower().endswith('.exe')}
    for name, meta in metadata.items():
        if not isinstance(name, str) or not isinstance(meta, dict):
            continue
        captured = meta.get('captured_processes', [])
        captured = captured if isinstance(captured, list) else []
        if (appid and str(meta.get('steam_app_id')) == appid or
                any(str(p).lower() in exenames for p in captured)):
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
    for profile in profile_records(text(mako), awareness_warnings, 'MAKO profile data'):
        if profile.get('name') in associated:
            for key in ('frame_generation_enabled', 'frame_generation_provisioned', 'multiplier'):
                if key in profile:
                    fg.append(evidence('MAKO', key, profile[key], mako))
    lsfg = h / '.config/lsfg-vk/conf.toml'
    for profile in profile_records(text(lsfg), awareness_warnings, 'LSFG-VK profile data'):
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
    # A one-shot assessment has no cursor/session boundary. File timestamps
    # cannot authenticate historical text; the optional monitor reads new events.
    if any(x['path'].lower().endswith('helixsr.log') for x in logs):
        evidence_state = 'historical log available; current runtime unverified'
    elif processes:
        evidence_state = 'game running; current HelixSR output unverified'
    setup = setup_report(target, route, options, opti_files)
    configured_helix = setup['configured']
    if setup.get('framegen_evidence') != 'not provided by this release':
        item = evidence('HelixSR 2.0', 'Frame generation provider', setup['framegen_evidence'],
                        Path(target or game['folder']) / 'OptiScaler.ini',
                        'configuration only; runtime activation unverified')
        item['enabled'] = setup.get('framegen_configured')
        fg.append(item)
    helix20_fg = any(item['source'] == 'HelixSR 2.0' for item in fg)
    return dict(optiscaler=dict(present=bool(opti_files or configs), dlls=opti_files,
                               configs=[str(p) for p in configs], involved=route == 'optiscaler' or configured_helix,
                               helix_configured=configured_helix, runtime=opti_runtime, setup=setup),
                framegen=fg,
                framegen_summary=('HelixSR FG configuration unavailable; state unknown'
                                  if helix20_fg and setup.get('framegen_configured') is None else
                                  'HelixSR FG selected; generated-frame output unverified'
                                  if helix20_fg and setup.get('framegen_configured') else
                                  'HelixSR FG not selected; see per-provider settings below'
                                  if helix20_fg else
                                  'Frame-generation configuration unavailable; state unknown'
                                  if awareness_warnings and not fg else
                                  'See source-specific evidence below; some metadata is invalid'
                                  if awareness_warnings else
                                  'No supported per-game evidence' if not fg else
                                  'See source-specific evidence below'),
                awareness_warnings=list(dict.fromkeys(awareness_warnings)),
                helix_runtime=evidence_state, processes=processes, logs=logs,
                launch_options=options, observed_at=time.time())


def text_tail(path, limit=16384):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as f:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return ''
            f.seek(0, 2)
            f.seek(max(0, f.tell() - limit))
            return f.read(limit).decode(errors='replace')
    except OSError:
        return ''


def safe_log(path, root):
    try:
        path.relative_to(root)
        for parent in (path, *path.parents):
            if parent.is_symlink():
                return False
            if parent == Path(root):
                break
        return path.is_file()
    except (OSError, ValueError):
        return False
