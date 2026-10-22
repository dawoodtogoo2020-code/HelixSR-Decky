"""Read-only checks and shared instructions for the installed proxy route."""
import configparser
import json
import os
import stat
from pathlib import Path
import re
import shlex


GUIDE = 'https://github.com/dawoodtogoo2020-code/HelixSR-Decky/blob/main/OPTISCALER_GUIDE.md'
KEYS = ('Dx12Upscaler', 'FfxDx12Path', 'FfxDx12SRPath', 'EnableDlssInputs',
        'NvapiPath', 'OverrideNvapiDll', 'UseFakenvapi', 'Dxgi', 'ShortcutKey',
        'FGInput', 'FGNvngxReplacement')


def parse_config(source):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(source.lstrip('\ufeff'))
    except configparser.Error as exc:
        raise ValueError('Invalid or repeated configuration setting: ' + str(exc)[:200]) from exc
    return parser


def pin_config(source, template, settings):
    """Change only unique managed settings in their upstream sections."""
    bom = '\ufeff' if source.startswith('\ufeff') else ''
    source = source.removeprefix('\ufeff')
    parsed, upstream = parse_config(source), parse_config(template)
    original = {s: dict(parsed.items(s)) for s in parsed.sections()}
    defaults = dict(parsed.defaults())
    managed = set()
    newline = '\r\n' if '\r\n' in source else '\n'
    for key, value in settings:
        expected = [s for s in upstream.sections() if upstream.has_option(s, key)]
        present = [s for s in parsed.sections() if parsed.has_option(s, key)]
        if len(expected) != 1:
            raise ValueError('Upstream OptiScaler configuration changed: ' + key)
        section = expected[0]
        managed.add((section, key.lower()))
        if present and present != [section]:
            raise ValueError('Managed configuration setting is misplaced or repeated: ' + key)
        lines = re.split(r'(?<=\n)', source)
        current, header, replaced = '', None, False
        for i, line in enumerate(lines):
            match = parsed.SECTCRE.match(line.strip())
            if match:
                current = match['header']
                if current == section:
                    header = i
            elif current == section and re.match(r'[ \t]*' + re.escape(key) + r'[ \t]*[=:]', line, re.I):
                ending = '\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
                lines[i] = key + '=' + value + ending
                replaced = True
        if not replaced:
            if header is None:
                source += ('' if not source or source.endswith(('\n', '\r')) else newline) + '[' + section + ']' + newline + key + '=' + value + newline
            else:
                if not lines[header].endswith(('\n', '\r')):
                    lines[header] += newline
                lines.insert(header + 1, key + '=' + value + newline)
                source = ''.join(lines)
        else:
            source = ''.join(lines)
        parsed = parse_config(source)
        if parsed.get(section, key) != value:
            raise ValueError('Managed configuration setting could not be safely updated: ' + key)
    unchanged = lambda data: {(s, k): v for s, items in data.items() for k, v in items.items() if (s, k) not in managed}
    if defaults != dict(parsed.defaults()) or unchanged(original) != unchanged({s: dict(parsed.items(s)) for s in parsed.sections()}):
        raise ValueError('Configuration structure needs manual review; unrelated settings would change')
    return bom + source


def configuration(path):
    path = Path(path)
    if not path.exists():
        return {}, 'Configuration is not installed'
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(path, flags), 'rb') as f:
            info = os.fstat(f.fileno())
            if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 1 << 20:
                raise ValueError('Configuration is not a regular file or is too large')
            raw = f.read((1 << 20) + 1)
        if len(raw) > 1 << 20 or b'\x00' in raw:
            raise ValueError('Configuration is too large or invalid')
        parser = parse_config(raw.decode('utf-8-sig'))
        values = {}
        for section in parser.sections():
            for key in KEYS:
                if parser.has_option(section, key):
                    if key in values:
                        raise ValueError('Repeated setting needs review: ' + key)
                    values[key] = parser.get(section, key).strip()
        return values, ''
    except (OSError, ValueError, UnicodeError, configparser.Error) as exc:
        return {}, 'Configuration needs review: ' + str(exc)[:200]


def override_status(options):
    if re.search(r'[$`\n\r]|&&|\|\||[<>]', options):
        return 'unknown'
    try:
        tokens = shlex.split(options)
    except ValueError:
        return 'unknown'
    overrides = [t for t in tokens if t.startswith('WINEDLLOVERRIDES=')]
    if not overrides:
        return 'missing'
    if len(overrides) != 1:
        return 'conflict'
    # An assignment after the command can be a game argument, not its environment.
    position = tokens.index(overrides[0])
    if any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*=.*', t) for t in tokens[:position]):
        return 'unknown'
    rules = []
    for rule in overrides[0].split('=', 1)[1].split(';'):
        names, _, modes = rule.partition('=')
        names = [n.strip().lower().removesuffix('.dll') for n in names.split(',')]
        if '*' in names:
            return 'unknown'
        if 'dxgi' in names:
            rules.append(modes.replace(' ', '').lower())
    return 'correct' if rules == ['n,b'] else 'conflict' if rules else 'missing'


def setup_report(target, route, options, proxy_files=()):
    directory = Path(target) if target else None
    if directory and (directory.is_file() or directory.suffix.lower() == '.dll'):
        directory = directory.parent
    values, error = configuration(directory / 'OptiScaler.ini') if directory else ({}, 'No target folder detected')
    expected = {key: 'Z:' + str(directory / 'HelixSR' / name).replace('/', '\\')
                for key, name in [('FfxDx12Path', 'helixsr.dll'), ('FfxDx12SRPath', 'helixsr_upscaler.dll')]} if directory else {}
    paths_match = bool(expected) and all(values.get(k, '').strip('"\'') == v for k, v in expected.items())
    configured = route == 'optiscaler' and values.get('Dx12Upscaler', '').lower() == 'fsr31' and paths_match and not error
    required = ('dxgi.dll', 'fakenvapi.dll', 'fakenvapi.ini', 'HelixSR/helixsr.dll',
                'HelixSR/helixsr_upscaler.dll', 'HelixSR/helixsr_weights.bin', 'HelixSR/helixsr_kernels.pak')
    modern = False
    modern20 = False
    if directory:
        marker = directory / 'HelixSR/helixsr-install.json'
        try:
            if not marker.is_symlink() and marker.stat().st_size <= 4096:
                installed = json.loads(marker.read_text()).get('helixsr')
                modern = installed in ('1.9.3', '2.0.0')
                modern20 = installed == '2.0.0'
        except (OSError, ValueError, AttributeError):
            pass
    if modern20:
        from helix20_release import scaler_pairs
        required = tuple(dest for _, dest in scaler_pairs())
        paths_match = (directory / 'HelixSR-fsrfg/amd_fidelityfx_dx12.dll').is_file()
        configured = (route == 'optiscaler'
                      and values.get('Dx12Upscaler', '').lower() in ('auto', 'ffx')
                      and paths_match and not error)
    elif modern:
        from modern_release import scaler_pairs
        required = tuple(dest for _, dest in scaler_pairs())
        paths_match = (directory / 'HelixSR/helixsr.dll').is_file()
        configured = route == 'optiscaler' and values.get('Dx12Upscaler', '').lower() == 'dlss' and paths_match and not error
    fg_configured = (modern20 and values.get('FGInput', '').lower() == 'nvngxfg'
                     and values.get('FGNvngxReplacement', '').lower() == 'helixsr')
    missing = [name for name in required if not directory or not (directory / name).is_file()]
    launch = override_status(options)
    key = values.get('ShortcutKey', 'auto')
    shortcut = 'Insert (default)' if key.lower() == 'auto' else 'overlay shortcut disabled' if key == '-1' else 'configured ShortcutKey=' + key
    checks = []
    if route == 'optiscaler':
        checks.append(('Install adds HelixSR 2.0 Scaler, its embedded upscaler and both frame-generation modes automatically.'
                       if modern20 else
                       'Install adds HelixSR Scaler and its complete runtime assets automatically.') if modern else
                      'Install adds OptiScaler, fakenvapi and HelixSR automatically for this route.')
        if missing:
            checks.append('Missing setup files: ' + ', '.join(missing))
        if error:
            checks.append(error)
        elif not configured:
            checks.append('HelixSR backend or provider paths differ. Review Update HelixSR to restore the managed route while retaining other settings.')
        if launch != 'correct':
            checks.append('DXGI launch override: ' + launch + '. Review the proxy launch option in Steam or your launcher.')
        if not any(Path(p).parent == directory and Path(p).name.lower() == 'dxgi.dll' for p in proxy_files):
            checks.append('OptiScaler DXGI proxy identity has not been detected in the target folder.')
        if values.get('EnableDlssInputs', '').lower() in ('false', 'off', '0'):
            checks.append('DLSS input is disabled in OptiScaler.ini. Review EnableDlssInputs before expecting the game to offer DLSS.')
        if values.get('UseFakenvapi', '').lower() in ('false', 'off', '0') or values.get('OverrideNvapiDll', '').lower() in ('false', 'off', '0'):
            checks.append('Automatic fakenvapi/NVAPI handling is disabled. Review this per-game choice if DLSS input is missing.')
        if directory and (directory / 'nvapi64.dll').exists():
            checks.append('An existing nvapi64.dll may affect DLSS input. It is not replaced; review OptiScaler.log and NvapiPath.')
        if values.get('NvapiPath', 'auto').lower() != 'auto':
            checks.append('Custom NvapiPath is configured. Verify it points to your intended per-game NVAPI provider.')
        checks.append(('Run the game in DX12. Select an upscaler supported by the game. Open HelixSR Scaler using ' + shortcut + '; auto selects the embedded HelixSR FidelityFX backend.' if modern20 else
                       'Run the game in DX12. Select DLSS (or a supported FSR/XeSS input). Open HelixSR Scaler using ' + shortcut + '; HelixSR uses the DLSS backend.' if modern else
                       'Run the game in DX12. Open OptiScaler using ' + shortcut + '. Select Upscaling → Upscalers → FFX: FSR HelixSR (3.1.5).'))
        checks.append('If DLSS is unavailable, use a supported FSR or XeSS input if the game offers one. Input name alone does not identify the output backend. Otherwise collect a fresh OptiScaler.log.')
        checks.append('Check a fresh helixsr.log for neural output, then check gameplay for artifacts or crashes. Installed files and a mapped proxy alone do not prove rendering.')
    elif route == 'direct':
        checks.append('Native FSR 3.1 replacement: select AMD FSR in the game. This route does not need OptiScaler or an additional DXGI override.')
    else:
        checks.append('No supported route detected. Review compatibility reasons before installing.')
    if modern20:
        checks.append(('HelixSR frame generation is configured for DLSS FG input. The game must support and enable DLSS frame generation. '
                       'Installed files and settings do not prove frame generation ran.' if fg_configured else
                       'HelixSR frame-generation files are installed, but the current provider settings do not select them. '
                       'This is configuration evidence only; runtime activation is unknown.'))
    else:
        checks.append('Frame generation is separate. Existing settings are preserved; this HelixSR version does not add frame generation.')
    return dict(configured=configured, backend=values.get('Dx12Upscaler', 'unknown'),
                provider_paths_match=paths_match, override=launch, overlay_shortcut=shortcut,
                settings=values, missing=missing, checks=checks, guide=GUIDE,
                framegen_configured=fg_configured,
                framegen_evidence=('configured; runtime unverified' if fg_configured else
                                   'not selected; runtime unknown' if modern20 else 'not provided by this release'))
