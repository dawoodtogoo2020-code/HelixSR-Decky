"""Pinned adapter for the reviewed official HelixSR 1.9.3 release.

The upstream converter and installers remain intact. This adapter validates
its separate-file output and selects only reviewed game payloads.
"""
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import stat
import struct

# Model E identity is repeated here to keep this adapter independent of the registry.
RECIPE_FILES = (
    'helixsr-setup.sh',
    'setup/helixsr_setup.py',
    'setup/kernels/common/fp16.h',
    'setup/kernels/common/port_cpp.h',
    'setup/kernels/common/port_hlsl.hlsli',
    'setup/kernels/rt/px_common.h',
    'setup/kernels/rt/px_cpp.h',
    'setup/kernels/rt/px_hlsl.h',
    'setup/kernels/u5/u5_memory.h',
    'setup/lib/compact_hlsl.py',
    'setup/lib/compact_u5.py',
    'setup/lib/extract_ptx.py',
    'setup/lib/extract_weights.py',
    'setup/lib/family_hlsl.py',
    'setup/lib/family_k/gen_helper.py',
    'setup/lib/family_k/trace_frags.py',
    'setup/lib/family_k/two_sites.json',
    'setup/lib/family_k/validate.py',
    'setup/lib/family_u/gen_helper.py',
    'setup/lib/family_u/ptxsim_up.py',
    'setup/lib/family_u/trace_frags.py',
    'setup/lib/family_u/two_sites.json',
    'setup/lib/family_u/validate.py',
    'setup/lib/fast_tiles.py',
    'setup/lib/kernels.py',
    'setup/lib/load_fence.py',
    'setup/lib/model/launch_synth',
    'setup/lib/model/launch_synth.cpp',
    'setup/lib/model/launch_synth.exe',
    'setup/lib/model/model.cpp',
    'setup/lib/model/model.h',
    'setup/lib/model/model_gen.inc',
    'setup/lib/ptx2hlsl.py',
    'setup/lib/ptxsim.py',
    'setup/lib/regen_kernels.py',
    'setup/lib/samplers.py',
    'setup/lib/splitk_hlsl.py',
    'setup/lib/trace_tables.py',
    'setup/lib/u5_roll.py',
    'setup/lib/u5_rows.py',
)
SOURCE_SHA256 = 'be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e'
WEIGHTS_SIZE = 1903872
WEIGHTS_SHA256 = '762adfde720035f7ac43910846e0ce6826c239bcd41f863196f77c547ae57153'
KERNEL_NAMES = (
    b'px_auto_exposure',
    b'px_auto_exposure_copy',
    b'px_clear_buffer',
    b'px_copy_exposure',
    b'px_luma_convert',
    b'px_reduce_sum',
    b'px_u10',
    b'px_k8_rel',
    b'px_k8_hdr_colvar_mvhi',
    b'px_k8_hdr_colvar_mvlo',
    b'px_k8_hdr_mvdiff_mvhi',
    b'px_k8_hdr_mvdiff_mvlo',
    b'px_k8_ldr_colvar_mvhi',
    b'px_k8_ldr_colvar_mvlo',
    b'px_k8_ldr_mvdiff_mvhi',
    b'px_k8_ldr_mvdiff_mvlo',
    b'px_k4',
    b'px_k9',
    b'px_k10',
    b'px_k11',
    b'px_u6',
    b'px_k7',
    b'px_u9',
    b'px_u5',
    b'px_u8',
    b'px_k5',
    b'px_k5f',
    b'px_k5n',
    b'px_u4',
    b'px_u5_table',
)
from optiscaler_setup import parse_config, pin_config

MODERN_VERSION = '1.9.3'
RELEASE_SHA256 = '7094b7afd006ab56231c880fcd358f115b114ee0734baa19d497a3e42da0a1d1'
RELEASE_SIZE = 136076974
RELEASE_URL = 'https://github.com/lonewolf0622/HelixSR/releases/download/v1.9.3/HelixSR-1.9.3.zip'
RELEASE_PAGE = 'https://github.com/lonewolf0622/HelixSR/releases/tag/v1.9.3'
RECIPE_SHA256 = '2117ee291fffcaf4e87a352073c107a5964c439ff8b51b51aa538a9e4b48fcd0'
_RECIPE_FILES = RECIPE_FILES + ('setup/helixsr_install.py',)
_ROOT_FILES = ('amd_fidelityfx_dx12.dll', 'helixsr_weights.bin',
               'helixsr_kernels.pak', 'helixsr_setup.json')
_SCALER_FILES = (
    'OptiScaler.dll', 'OptiScaler.ini',
    'Licenses/DirectX_LICENSE.txt', 'Licenses/FidelityFX_v2_LICENSE.md',
    'Licenses/OptiScaler_LICENSE.txt', 'Licenses/Streamline_LICENSE.txt',
    'Licenses/XeSS_LICENSE.txt',
    'OptiScaler/amd_fidelityfx_framegeneration_dx12.dll',
    'OptiScaler/amd_fidelityfx_loader_dx12.dll',
    'OptiScaler/amd_fidelityfx_upscaler_dx12.dll',
    'OptiScaler/amd_fidelityfx_vk.dll', 'OptiScaler/libxell.dll',
    'OptiScaler/libxess_dx11.dll', 'OptiScaler/libxess_fg.dll',
    'OptiScaler/libxess.dll', 'OptiScaler/D3D12_OptiScaler/D3D12Core.dll',
    'OptiScaler/streamline/NvLowLatencyVk.dll',
    'OptiScaler/streamline/sl.common.dll', 'OptiScaler/streamline/sl.deepdvc.dll',
    'OptiScaler/streamline/sl.directsr.dll', 'OptiScaler/streamline/sl.dlss_d.dll',
    'OptiScaler/streamline/sl.dlss_g.dll', 'OptiScaler/streamline/sl.dlss.dll',
    'OptiScaler/streamline/sl.interposer.dll', 'OptiScaler/streamline/sl.nis.dll',
    'OptiScaler/streamline/sl.nvperf.dll', 'OptiScaler/streamline/sl.pcl.dll',
    'OptiScaler/streamline/sl.reflex.dll',
)


def modern(value):
    return isinstance(value, Mapping) and value.get('version') == MODERN_VERSION


def validate_release(release):
    expected = dict(version=MODERN_VERSION, sha256=RELEASE_SHA256,
                    size=RELEASE_SIZE, url=RELEASE_URL, page=RELEASE_PAGE)
    if (not isinstance(release, Mapping) or type(release.get('size')) is not int
            or any(release.get(k) != v for k, v in expected.items())):
        raise ValueError('HelixSR 1.9.3 official release identity changed; an app update is required')
    return release


def _open(package, name, limit):
    package = Path(package)
    path = package / name
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('Unsafe HelixSR file: ' + name)
        if parent == package:
            break
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= limit:
        raise ValueError('Missing, unsafe or oversized HelixSR file: ' + name)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    source = os.fdopen(os.open(path, flags), 'rb')
    opened = os.fstat(source.fileno())
    if not stat.S_ISREG(opened.st_mode) or opened.st_size != info.st_size:
        source.close()
        raise ValueError('HelixSR file changed during validation: ' + name)
    return source, info.st_size


def _hash(package, name, limit):
    source, size = _open(package, name, limit)
    digest, total = hashlib.sha256(), 0
    with source:
        while chunk := source.read(65536):
            total += len(chunk)
            if total > limit or total > size:
                raise ValueError('HelixSR file changed during validation: ' + name)
            digest.update(chunk)
    if total != size:
        raise ValueError('Truncated HelixSR file: ' + name)
    return digest.hexdigest(), size


def verify_recipe(package):
    package = Path(package)
    actual = {p.relative_to(package).as_posix() for p in (package / 'setup').rglob('*')
              if not p.is_dir() or p.is_symlink()}
    if actual != {n for n in _RECIPE_FILES if n.startswith('setup/')}:
        raise ValueError('HelixSR model conversion files changed; an app update is required')
    hashes = {n: _hash(package, n, 4 << 20)[0] for n in _RECIPE_FILES}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    if digest != RECIPE_SHA256:
        raise ValueError('HelixSR model recipe changed; an app update is required')
    return dict(id='helixsr-model-e', adapter='separate-network-v1', recipe_sha256=digest)


def verify_outputs(package):
    source, _ = _open(package, 'helixsr_setup.json', 4096)
    with source:
        raw = source.read(4097)
    if len(raw) > 4096:
        raise ValueError('Generated HelixSR manifest is oversized')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Repeated HelixSR manifest key')
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid generated HelixSR manifest') from exc
    if (not isinstance(data, dict)
            or set(data) != {'source_sha256', 'ptx_target', 'shaders', 'wave64', 'fp32', 'weights_sha256'}
            or data['source_sha256'] != SOURCE_SHA256
            or data['weights_sha256'] != WEIGHTS_SHA256
            or data['ptx_target'] not in ('sm_80', 'sm_89')
            or type(data['wave64']) is not bool or type(data['fp32']) is not bool
            or type(data['shaders']) is not int):
        raise ValueError('Generated HelixSR model does not match the selected Model E recipe')
    expected = set(KERNEL_NAMES)
    if data['wave64']:
        expected |= {n + b'_w64' for n in KERNEL_NAMES}
    if data['fp32']:
        expected |= {n + b'_fp32' for n in tuple(expected)}
    if data['shaders'] != len(expected):
        raise ValueError('Generated HelixSR shader count does not match the recipe')
    digest, size = _hash(package, 'helixsr_weights.bin', WEIGHTS_SIZE)
    if size != WEIGHTS_SIZE or digest != WEIGHTS_SHA256:
        raise ValueError('Generated HelixSR weights do not match Model E')
    source, size = _open(package, 'helixsr_kernels.pak', 512 << 20)
    with source:
        header = source.read(16)
        if len(header) != 16 or header[:8] != b'HXSRKPAK':
            raise ValueError('Generated HelixSR kernels have an unsupported format')
        version, count = struct.unpack('<II', header[8:])
        if version != 2 or count != len(expected):
            raise ValueError('Generated HelixSR kernel table count is invalid')
        names, end = set(), 16 + 40 * count
        for _ in range(count):
            row = source.read(40)
            if len(row) != 40:
                raise ValueError('Generated HelixSR kernel table is truncated')
            raw_name, offset, length = struct.unpack('<32sII', row)
            name = raw_name.split(b'\0', 1)[0]
            if (name not in expected or name in names or raw_name != name.ljust(32, b'\0')
                    or offset != end or not length or offset + length > size):
                raise ValueError('Generated HelixSR kernel table is invalid')
            names.add(name)
            end += length
        if names != expected or end != size:
            raise ValueError('Generated HelixSR kernels are truncated or have trailing bytes')


def payload_files():
    return _ROOT_FILES + tuple('helixsr-scaler/' + n for n in _SCALER_FILES)


def scaler_pairs():
    return (('amd_fidelityfx_dx12.dll', 'HelixSR/helixsr.dll'),
            ('helixsr_weights.bin', 'HelixSR/helixsr_weights.bin'),
            ('helixsr_kernels.pak', 'HelixSR/helixsr_kernels.pak')) + tuple(
                ('helixsr-scaler/' + n, 'dxgi.dll' if n == 'OptiScaler.dll' else n)
                for n in _SCALER_FILES if n != 'OptiScaler.ini')


def configuration(source, template):
    upstream = parse_config(template)
    # The reviewed Scaler explicitly exposes HelixSR through its DLSS route.
    for section, key in (('Upscalers', 'Dx12Upscaler'), ('HelixSR', 'FrameGeneration'),
                         ('FrameGen', 'FGNvngxReplacement')):
        if not upstream.has_option(section, key):
            raise ValueError('Upstream HelixSR Scaler configuration changed: ' + key)
    parsed = parse_config(source)
    settings = [('Dx12Upscaler', 'dlss'), ('FrameGeneration', 'off')]
    if parsed.get('FrameGen', 'FGNvngxReplacement', fallback='').strip().lower() == 'helixsr':
        settings.append(('FGNvngxReplacement', 'FFX'))
    return pin_config(source, template, settings)
