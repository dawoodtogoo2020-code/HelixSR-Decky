"""Validated per-game Scaler settings. No filesystem or runtime claims."""
import re
from optiscaler_setup import parse_config


def read_settings(source):
    p = parse_config(source)
    get = lambda s, k, d: p.get(s, k, fallback=d).strip().lower()
    inp, out = get('FrameGen', 'FGInput', 'auto'), get('FrameGen', 'FGOutput', 'auto')
    replacement = get('FrameGen', 'FGNvngxReplacement', 'auto')
    enabled = get('FrameGen', 'Enabled', 'auto')
    if enabled == 'false' or inp == 'nofg' or (inp == 'auto' and out == 'auto'):
        provider = 'off'
    elif inp == 'nvngxfg' and replacement == 'helixsr':
        provider = 'helixsr'
    elif out == 'xefg':
        provider = 'xess'
    elif out == 'fsrfg':
        provider = 'fsr'
    else:
        provider = 'unsupported'
    count = get('XeFG', 'InterpolationCount', '1')
    try:
        multiplier = 2 if count == 'auto' else int(count) + 1
    except ValueError:
        multiplier = 2
    return dict(provider=provider,
                model='full' if get('HelixSR', 'FGPreset', 'c') == 'full' else 'light',
                quick_flow=get('HelixSR', 'QuickFlow', 'off').replace('auto', 'off'),
                multiplier=multiplier if provider == 'xess' else 2,
                upscaler=('fsr' if get('Upscalers', 'Dx12Upscaler', 'auto') in ('auto', 'ffx')
                          and get('FSR', 'UpscalerIndex', 'auto') == '2' else
                          'helixsr' if get('Upscalers', 'Dx12Upscaler', 'auto') in ('auto', 'ffx')
                          and get('FSR', 'UpscalerIndex', 'auto') in ('auto', '0') else 'unsupported'),
                int8=get('HelixSR', 'Int8', 'auto'), wave_size=get('HelixSR', 'WaveSize', 'auto'),
                restart_required=True, multiplier_choices=[2, 3] if provider == 'xess' else [2],
                notes='HelixSR FG needs a DirectX 12 game with DLSS frame generation enabled in-game. 3x uses XeSS FG.')


def _patch(source, section, key, value):
    newline = '\r\n' if '\r\n' in source else '\n'
    lines = source.splitlines(keepends=True)
    current, header = '', None
    for i, line in enumerate(lines):
        match = re.match(r'\s*\[([^]]+)\]', line)
        if match:
            current = match[1]
            if current == section:
                header = i
        elif current == section and re.match(r'\s*' + re.escape(key) + r'\s*[=:]', line, re.I):
            ending = '\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
            lines[i] = key + '=' + str(value) + ending
            return ''.join(lines)
    entry = key + '=' + str(value) + newline
    if header is None:
        return source + ('' if not source or source.endswith('\n') else newline) + '[' + section + ']' + newline + entry
    if not lines[header].endswith('\n'):
        lines[header] += newline
    lines.insert(header + 1, entry)
    return ''.join(lines)


def update_settings(source, changes):
    choices = dict(provider=('off', 'helixsr', 'fsr', 'xess'), model=('light', 'full'),
                   quick_flow=('off', 'fast', 'fastest'), multiplier=(2, 3),
                   upscaler=('helixsr', 'fsr'), int8=('auto', 'on', 'off'), wave_size=('auto', '32', '64'))
    if not isinstance(changes, dict) or not set(changes) <= set(choices):
        raise ValueError('Unknown HelixSR setting')
    for k, v in changes.items():
        expected = int if k == 'multiplier' else str
        if type(v) is not expected or v not in choices[k]:
            raise ValueError('Unsupported HelixSR setting: ' + k)
    state = read_settings(source)
    state.update(changes)
    if state['quick_flow'] != 'off' and state['model'] != 'full':
        raise ValueError('QuickFlow requires Full frame generation')
    if state['multiplier'] != 2 and state['provider'] != 'xess':
        raise ValueError('3x is supported only by the XeSS provider')
    edits = []
    if 'provider' in changes:
        routes = {'off': ('false', 'nofg', None, None),
                  'helixsr': ('true', 'nvngxfg', 'auto', 'HelixSR'),
                  'fsr': ('true', 'upscaler', 'fsrfg', 'FFX'),
                  'xess': ('true', 'upscaler', 'xefg', 'None')}
        edits.extend(('FrameGen', k, v) for k, v in zip(
            ('Enabled', 'FGInput', 'FGOutput', 'FGNvngxReplacement'), routes[state['provider']]) if v is not None)
    mapping = {'model': ('HelixSR', 'FGPreset', 'c' if state['model'] == 'light' else 'full'),
               'quick_flow': ('HelixSR', 'QuickFlow', state['quick_flow']),
               'multiplier': ('XeFG', 'InterpolationCount', state['multiplier'] - 1),
               'upscaler': ('Upscalers', 'Dx12Upscaler', 'ffx'),
               'int8': ('HelixSR', 'Int8', state['int8']),
               'wave_size': ('HelixSR', 'WaveSize', state['wave_size'])}
    edits.extend(mapping[k] for k in changes if k in mapping)
    if 'upscaler' in changes:
        edits.extend([('Libraries', 'FfxDx12SRPath', 'auto'),
                      ('FSR', 'UpscalerIndex', '0' if state['upscaler'] == 'helixsr' else '2')])
    bom = '\ufeff' if source.startswith('\ufeff') else ''
    result = source.removeprefix('\ufeff')
    before = parse_config(source)
    for section, key, value in edits:
        if key.lower() in before.defaults():
            raise ValueError('Managed setting in DEFAULT needs manual review')
        result = _patch(result, section, key, value)
    after = parse_config(result)
    managed = {(s, k.lower()) for s, k, _ in edits}
    unrelated = lambda p: {(s, k): v for s in p.sections() for k, v in p.items(s) if (s, k) not in managed}
    if dict(before.defaults()) != dict(after.defaults()) or unrelated(before) != unrelated(after):
        raise ValueError('Unrelated settings would change')
    return bom + result
