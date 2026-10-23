"""Pinned adapter for the reviewed official HelixSR 2.0.0 release.

The official setup stays unmodified.  This module only identifies its exact
recipe, validates the locally generated embedded network and frame-generation
payloads, and describes the files the installer is allowed to consume.
"""
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct

from optiscaler_setup import parse_config, pin_config

MODERN_VERSION = '2.0.0'
RELEASE_SHA256 = '0d60686eddbb0abd680b27d12a088344b212464ebf0a2dc18d10387e1c817f52'
RELEASE_SIZE = 136997025
RELEASE_URL = 'https://github.com/lonewolf0622/HelixSR/releases/download/v2.0.0/HelixSR-2.0.0.zip'
RELEASE_PAGE = 'https://github.com/lonewolf0622/HelixSR/releases/tag/v2.0.0'

# sha256(name NUL sha256(file) NUL ...) over the sorted, exact file sets.
RECIPE_SHA256 = '165e998fce651e06678aff56c485ec7ca2d190b9d053332f89a76a570e03af38'
RECIPE_FILE_COUNT = 117
STATIC_SHA256 = '36ca68660b65f8c67c07348426e8ef0059dd0bbc6603b3e88b3948e886aa6ae9'
STATIC_FILE_COUNT = 22

OUTPUT_DLL = 'HelixSR-fsrfg/amd_fidelityfx_dx12.dll'
MANIFEST_PATH = 'helixsr_setup.json'
FG_MANIFEST_PATH = 'helixsr_fg_setup.json'
NGX_RECEIPT_PATH = 'helixsr_ngx_core.txt'
MUTABLE_CONFIGS = ('helixsr-scaler/OptiScaler.ini', 'HelixSR-fsrfg/helixsr.ini')
AMD_UPSCALER_SOURCE = 'helixsr-scaler/OptiScaler/amd_fidelityfx_upscaler_dx12.dll'
AMD_UPSCALER_RUNTIME = 'HelixSR-fsrfg/amd_fidelityfx_upscaler_dx12.amd.dll'

BASE_DLL_SIZE = 7997952
BASE_DLL_SHA256 = '82b612a73759117d4203f0ca76f18b325e1c6f3c61c64481c94750abce392a09'
NVEXEC_SIZE = 846336
NVEXEC_SHA256 = '9ffe365807957babc199dccb74cbb2d3e564a94e9ecc8e2f04b98f851f411798'
HELIX_INI_SHA256 = '76dad9ad18ab657f123f047faae554b32e79337b0d3360a84b375d1ea62c04b6'
SOURCE_SHA256 = 'be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e'
WEIGHTS_SIZE = 1903872
WEIGHTS_SHA256 = '762adfde720035f7ac43910846e0ce6826c239bcd41f863196f77c547ae57153'
NGX_SHA256 = '0765fb7fb2b8be28ee1f0226679d7b2636a69cacce5a23891984978f690d81a4'
FG_SOURCES = {
    '310.3': '0a6212a33ebaa708e7907468db7345c92cfdc6f8dd29c6e1248f32dbea4bcdaf',
    '310.9.16': '8d59d49b36410dd6b62fef2503a5871d347415bd85d943fa0848563a95dd50c7',
}
FG_KERNEL_COUNTS = {'310.3': 59, '310.9.16': 65}

_BASE_KERNELS = tuple(('px_' + name).encode() for name in (
    'auto_exposure', 'auto_exposure_copy', 'clear_buffer', 'copy_exposure',
    'luma_convert', 'reduce_sum', 'u10', 'k8_rel', 'k8_hdr_colvar_mvhi',
    'k8_hdr_colvar_mvlo', 'k8_hdr_mvdiff_mvhi', 'k8_hdr_mvdiff_mvlo',
    'k8_ldr_colvar_mvhi', 'k8_ldr_colvar_mvlo', 'k8_ldr_mvdiff_mvhi',
    'k8_ldr_mvdiff_mvlo', 'k4', 'k9', 'k10', 'k11', 'u6', 'k7', 'u9',
    'u5', 'u8', 'k5', 'k5f', 'k5n', 'u4', 'k5nx', 'k5nxf', 'u5_table'))
_FP32_ONLY_KERNELS = tuple(('px_' + name).encode() for name in ('k5x', 'k5fx'))
KERNEL_NAMES = tuple(
    name + suffix
    for name in _BASE_KERNELS
    for suffix in (b'', b'_fp32', b'_fp32h', b'_w64', b'_w64_fp32', b'_w64_fp32h')
) + tuple(
    name + suffix
    for name in _FP32_ONLY_KERNELS
    for suffix in (b'_fp32', b'_fp32h', b'_w64_fp32', b'_w64_fp32h')
)

_FG_FILES = (
    'HelixSR-fsrfg/helixsr-fg/nvexec64.dll',
    'HelixSR-fsrfg/helixsr-fg/_nvngx.dll',
    'HelixSR-fsrfg/helixsr-fg/nvngx_dlssg.dll',
    'HelixSR-fsrfg/helixsr-fg/hxfg_data.bin',
    'HelixSR-fsrfg/helixsr-fg/310.9.16/nvngx_dlssg.dll',
    'HelixSR-fsrfg/helixsr-fg/310.9.16/hxfg_data.bin',
)
_SCALER_FILES = (
    'OptiScaler.dll', 'OptiScaler.ini',
    'Licenses/DirectX_LICENSE.txt', 'Licenses/FidelityFX_v2_LICENSE.md',
    'Licenses/OptiScaler_LICENSE.txt', 'Licenses/XeSS_LICENSE.txt',
    'OptiScaler/amd_fidelityfx_framegeneration_dx12.dll',
    'OptiScaler/amd_fidelityfx_loader_dx12.dll',
    'OptiScaler/amd_fidelityfx_upscaler_dx12.dll',
    'OptiScaler/amd_fidelityfx_vk.dll',
    'OptiScaler/D3D12_OptiScaler/D3D12Core.dll',
    'OptiScaler/libxell.dll', 'OptiScaler/libxess_dx11.dll',
    'OptiScaler/libxess_fg.dll', 'OptiScaler/libxess.dll',
)


def modern(value):
    return isinstance(value, Mapping) and value.get('version') == MODERN_VERSION


def validate_release(release):
    expected = dict(version=MODERN_VERSION, sha256=RELEASE_SHA256,
                    size=RELEASE_SIZE, url=RELEASE_URL, page=RELEASE_PAGE)
    if (not isinstance(release, Mapping) or type(release.get('size')) is not int
            or any(release.get(k) != v for k, v in expected.items())):
        raise ValueError('HelixSR 2.0.0 official release identity changed; an app update is required')
    return release


def _open(package, name, limit):
    package = Path(package)
    path = package.joinpath(*PurePosixPath(name).parts)
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
        while chunk := source.read(1 << 20):
            total += len(chunk)
            if total > size or total > limit:
                raise ValueError('HelixSR file changed during validation: ' + name)
            digest.update(chunk)
    if total != size:
        raise ValueError('Truncated HelixSR file: ' + name)
    return digest.hexdigest(), size


def _tree(package, relative):
    package, relative = Path(package), PurePosixPath(relative)
    root = package.joinpath(*relative.parts)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('HelixSR recipe directory is missing or unsafe: ' + relative.as_posix())
    names = []
    for current, directories, files in os.walk(root, followlinks=False):
        current = Path(current)
        for name in directories:
            if (current / name).is_symlink():
                raise ValueError('HelixSR recipe contains an unsafe link')
        for name in files:
            path = current / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('HelixSR recipe contains an unsafe file')
            names.append(path.relative_to(package).as_posix())
    return sorted(names)


def _identity(package, names, limit):
    digest = hashlib.sha256()
    for name in sorted(names):
        value, _ = _hash(package, name, limit)
        digest.update(name.encode())
        digest.update(b'\0')
        digest.update(value.encode())
        digest.update(b'\0')
    return digest.hexdigest()


def _static_names(package):
    return (['HelixSR-fsrfg/helixsr.ini', 'HelixSR-fsrfg/helixsr-fg/nvexec64.dll']
            + _tree(package, 'helixsr-scaler'))


def _verify_static(package):
    names = _static_names(package)
    if len(names) != STATIC_FILE_COUNT or _identity(package, names, 128 << 20) != STATIC_SHA256:
        raise ValueError('HelixSR 2.0 static payload changed; an app update is required')


def verify_recipe(package):
    recipe = ['helixsr-setup.sh'] + _tree(package, 'setup')
    if len(recipe) != RECIPE_FILE_COUNT or _identity(package, recipe, 4 << 20) != RECIPE_SHA256:
        raise ValueError('HelixSR 2.0 conversion recipe changed; an app update is required')
    digest, size = _hash(package, OUTPUT_DLL, 16 << 20)
    if size != BASE_DLL_SIZE or digest != BASE_DLL_SHA256:
        raise ValueError('HelixSR 2.0 base DLL changed; an app update is required')
    _verify_static(package)
    return dict(id='helixsr-model-e', adapter='separate-network-v1', recipe_sha256=RECIPE_SHA256)


def _json(package, name, limit):
    source, _ = _open(package, name, limit)
    with source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Oversized HelixSR manifest: ' + name)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Repeated HelixSR manifest key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid HelixSR manifest: ' + name) from exc


def _verify_dxil(source, offset, length):
    if not 40 <= length <= 16 << 20:
        raise ValueError('Generated shader has an invalid size')
    source.seek(offset)
    header = source.read(36)
    if (len(header) != 36 or header[:4] != b'DXBC'
            or struct.unpack_from('<I', header, 24)[0] != length):
        raise ValueError('Generated shader is not a complete DXIL container')
    chunks = struct.unpack_from('<I', header, 28)[0]
    if not 1 <= chunks <= 64 or 32 + chunks * 4 > length:
        raise ValueError('Generated shader has an invalid DXIL chunk table')


def _verify_network(package, manifest):
    if not isinstance(manifest, dict):
        raise ValueError('Generated HelixSR network manifest is invalid')
    expected_manifest = {
        'source_sha256': SOURCE_SHA256, 'ptx_target': manifest.get('ptx_target'),
        'shaders': len(KERNEL_NAMES), 'wave64': True, 'fp32': True,
        'fp32h': True, 'weights_sha256': WEIGHTS_SHA256,
    }
    if (set(manifest) != set(expected_manifest) or manifest != expected_manifest
            or manifest['ptx_target'] not in ('sm_80', 'sm_89')):
        raise ValueError('Generated HelixSR network does not match the full Model E recipe')
    source, total = _open(package, OUTPUT_DLL, 1 << 30)
    with source:
        if total < BASE_DLL_SIZE + WEIGHTS_SIZE + 48:
            raise ValueError('Generated HelixSR DLL has no embedded network')
        source.seek(total - 32)
        footer = source.read(32)
        if len(footer) != 32 or footer[:8] != b'HXSRNET1':
            raise ValueError('Generated HelixSR DLL has no embedded network footer')
        weights_size, pak_size, version = struct.unpack('<QQQ', footer[8:])
        if version != 1 or weights_size != WEIGHTS_SIZE or not 16 < pak_size < 512 << 20:
            raise ValueError('Generated HelixSR network footer is invalid')
        base_size = total - 32 - weights_size - pak_size
        if base_size != BASE_DLL_SIZE:
            raise ValueError('Generated HelixSR DLL base changed')
        source.seek(0)
        base_hash = hashlib.sha256(source.read(base_size)).hexdigest()
        if base_hash != BASE_DLL_SHA256:
            raise ValueError('Generated HelixSR DLL base changed')
        weights = source.read(weights_size)
        if hashlib.sha256(weights).hexdigest() != WEIGHTS_SHA256:
            raise ValueError('Generated HelixSR weights do not match Model E')
        pak_start = base_size + weights_size
        source.seek(pak_start)
        header = source.read(16)
        if len(header) != 16 or header[:8] != b'HXSRKPAK':
            raise ValueError('Generated HelixSR kernels have an unsupported format')
        pak_version, count = struct.unpack('<II', header[8:])
        if pak_version != 2 or count != len(KERNEL_NAMES):
            raise ValueError('Generated HelixSR kernel count is invalid')
        names, entries, end = set(), [], 16 + 40 * count
        for _ in range(count):
            row = source.read(40)
            if len(row) != 40:
                raise ValueError('Generated HelixSR kernel table is truncated')
            raw_name, offset, length = struct.unpack('<32sII', row)
            name = raw_name.split(b'\0', 1)[0]
            if (name not in KERNEL_NAMES or name in names or raw_name != name.ljust(32, b'\0')
                    or offset != end or offset + length > pak_size):
                raise ValueError('Generated HelixSR kernel table is invalid')
            names.add(name)
            entries.append((pak_start + offset, length))
            end += length
        if names != set(KERNEL_NAMES) or end != pak_size:
            raise ValueError('Generated HelixSR kernels are incomplete or have trailing bytes')
        for offset, length in entries:
            _verify_dxil(source, offset, length)


def _archive(package, name):
    source, size = _open(package, name, 1 << 30)
    digest = hashlib.sha256()
    with source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
        source.seek(0)
        header = source.read(12)
        if len(header) != 12 or header[:8] != b'HXFGARC1':
            raise ValueError('Generated frame-generation archive has an unsupported format')
        count = struct.unpack('<I', header[8:])[0]
        if not 1 <= count <= 8192:
            raise ValueError('Generated frame-generation archive entry count is invalid')
        entries, previous = {}, ''
        for _ in range(count):
            raw = source.read(4)
            if len(raw) != 4:
                raise ValueError('Generated frame-generation archive index is truncated')
            length = struct.unpack('<I', raw)[0]
            if not 1 <= length <= 512:
                raise ValueError('Generated frame-generation archive name is invalid')
            raw_name = source.read(length)
            row = source.read(16)
            try:
                entry = raw_name.decode('ascii')
            except UnicodeDecodeError as exc:
                raise ValueError('Generated frame-generation archive name is invalid') from exc
            if (len(row) != 16 or entry <= previous or entry in entries or '/' in entry
                    or entry.startswith('\\') or '..' in entry.split('\\')):
                raise ValueError('Generated frame-generation archive index is invalid')
            offset, entry_size = struct.unpack('<QQ', row)
            entries[entry] = (offset, entry_size)
            previous = entry
        index_end = source.tell()
        position = (index_end + 255) & ~255
        for offset, entry_size in entries.values():
            if offset != position or not entry_size or offset + entry_size > size:
                raise ValueError('Generated frame-generation archive layout is invalid')
            position = (offset + entry_size + 255) & ~255
        if position != size:
            raise ValueError('Generated frame-generation archive is truncated or has trailing bytes')
    return entries, size, digest.hexdigest()


def _entry(package, archive, entries, name, limit=64 << 20):
    if name not in entries or entries[name][1] > limit:
        raise ValueError('Generated frame-generation archive is missing ' + name)
    source, _ = _open(package, archive, 1 << 30)
    with source:
        source.seek(entries[name][0])
        data = source.read(entries[name][1])
    if len(data) != entries[name][1]:
        raise ValueError('Generated frame-generation archive entry is truncated')
    return data


def _verify_weight_pack(data):
    if len(data) < 12 or data[:8] != b'HXFGWPK1':
        raise ValueError('Generated frame-generation weights have an unsupported format')
    count = struct.unpack_from('<I', data, 8)[0]
    if count != 67 or 12 + 20 * count > len(data):
        raise ValueError('Generated frame-generation weights are incomplete')
    seen, position = set(), (12 + 20 * count + 255) & ~255
    for index in range(count):
        block_id, offset, size = struct.unpack_from('<IQQ', data, 12 + index * 20)
        if block_id in seen or offset != position or not size or offset + size > len(data):
            raise ValueError('Generated frame-generation weight table is invalid')
        seen.add(block_id)
        position = (offset + size + 255) & ~255
    if position != len(data):
        raise ValueError('Generated frame-generation weights have trailing or missing bytes')


def _verify_fg_archive(package, archive, version, summary):
    entries, size, digest = _archive(package, archive)
    source_sha = FG_SOURCES[version]
    table_name = 'kernels\\kernels-v2.txt' if version == '310.9.16' else 'kernels\\kernels.txt'
    required = {'source.txt', table_name, 'kernels\\vkreset.cso', 'weights\\weights.pack'}
    if version == '310.3':
        required |= {'fgprog.txt', 'fgprog.small.txt'}
    if not required.issubset(entries) or any(
            not (name.startswith('kernels\\') or name.startswith('weights\\')
                 or name in {'source.txt', 'fgprog.txt', 'fgprog.small.txt'}) for name in entries):
        raise ValueError('Generated frame-generation archive has unexpected contents')
    expected_summary = dict(source_sha256=source_sha, source_version=version,
                            files=len(entries), archive_bytes=size, archive_sha256=digest)
    if summary != expected_summary:
        raise ValueError('Generated frame-generation manifest does not match its archive')
    expected_source = f'nvngx_dlssg {version} {source_sha}\n'.encode()
    if _entry(package, archive, entries, 'source.txt', 256) != expected_source:
        raise ValueError('Generated frame-generation archive source is invalid')
    _verify_weight_pack(_entry(package, archive, entries, 'weights\\weights.pack', 256 << 20))
    table = _entry(package, archive, entries, table_name, 4 << 20).decode('utf-8')
    kernels, references, variants = [], set(), {}
    for line in table.splitlines():
        words = line.split()
        if words and words[0] == 'kernel' and len(words) >= 5:
            kernels.append(words[3])
            references.add('kernels\\' + words[4].replace('/', '\\'))
            variants[words[3]] = set()
        elif words and words[0] == 'fuse' and len(words) >= 3:
            references.add('kernels\\' + words[2].replace('/', '\\'))
        elif words and words[0] == 'variant' and len(words) >= 3:
            references.add('kernels\\' + words[2].replace('/', '\\'))
            if kernels:
                variants[kernels[-1]].add(words[1])
    if (len(kernels) != FG_KERNEL_COUNTS[version] or len(set(kernels)) != len(kernels)
            or any(not {'w64', 'fp32', 'w64_fp32'}.issubset(value) for value in variants.values())
            or not references.issubset(entries)):
        raise ValueError('Generated frame-generation kernel table is incomplete')
    for name in references | {'kernels\\vkreset.cso'}:
        if name.endswith('.cso'):
            data = _entry(package, archive, entries, name, 16 << 20)
            from io import BytesIO
            _verify_dxil(BytesIO(data), 0, len(data))


def verify_outputs(package):
    package = Path(package)
    manifest = _json(package, MANIFEST_PATH, 4096)
    _verify_network(package, manifest)
    _verify_static(package)
    for name, digest, size in (
            ('HelixSR-fsrfg/helixsr-fg/nvexec64.dll', NVEXEC_SHA256, NVEXEC_SIZE),
            ('HelixSR-fsrfg/helixsr-fg/_nvngx.dll', NGX_SHA256, None),
            ('HelixSR-fsrfg/helixsr-fg/nvngx_dlssg.dll', FG_SOURCES['310.3'], None),
            ('HelixSR-fsrfg/helixsr-fg/310.9.16/nvngx_dlssg.dll', FG_SOURCES['310.9.16'], None)):
        actual, actual_size = _hash(package, name, 32 << 20)
        if actual != digest or (size is not None and actual_size != size):
            raise ValueError('Generated frame-generation dependency changed: ' + name)
    receipt, _ = _open(package, NGX_RECEIPT_PATH, 16)
    with receipt:
        if receipt.read() != b'yes\n':
            raise ValueError('NVIDIA NGX core was not completed for frame generation')
    fg = _json(package, FG_MANIFEST_PATH, 8192)
    if not isinstance(fg, dict) or set(fg) != set(FG_SOURCES):
        raise ValueError('Generated frame-generation manifest is incomplete')
    _verify_fg_archive(package, 'HelixSR-fsrfg/helixsr-fg/hxfg_data.bin', '310.3', fg['310.3'])
    _verify_fg_archive(package, 'HelixSR-fsrfg/helixsr-fg/310.9.16/hxfg_data.bin', '310.9.16', fg['310.9.16'])


def payload_files():
    return ((OUTPUT_DLL, MANIFEST_PATH, FG_MANIFEST_PATH, NGX_RECEIPT_PATH,
             'HelixSR-fsrfg/helixsr.ini') + _FG_FILES
            + tuple('helixsr-scaler/' + name for name in _SCALER_FILES))


def mutable_configs():
    return MUTABLE_CONFIGS


def direct_pairs():
    """Sources for a native FSR route; ``{dll}`` means the detected game DLL."""
    return ((OUTPUT_DLL, '{dll}'), ('HelixSR-fsrfg/helixsr.ini', 'helixsr.ini'))


def scaler_pairs():
    runtime = ((OUTPUT_DLL, OUTPUT_DLL),
               ('HelixSR-fsrfg/helixsr.ini', 'HelixSR-fsrfg/helixsr.ini'))
    runtime += tuple((name, name) for name in _FG_FILES)
    scaler = tuple(
        ('helixsr-scaler/' + name, 'dxgi.dll' if name == 'OptiScaler.dll' else name)
        for name in _SCALER_FILES if name != 'OptiScaler.ini')
    # Scaler otherwise creates this as a hard link on first launch. Install an
    # owned regular copy after its source so the runtime accepts it as current,
    # the manager's hard-link guard stays effective, and removal cleans it up.
    return runtime + scaler + ((AMD_UPSCALER_SOURCE, AMD_UPSCALER_RUNTIME),)


def configuration(source, template, previous_version=None):
    upstream = parse_config(template)
    for section, key in (('Upscalers', 'Dx12Upscaler'), ('FrameGen', 'FGInput'),
                         ('FrameGen', 'FGNvngxReplacement')):
        if not upstream.has_option(section, key):
            raise ValueError('Upstream HelixSR Scaler configuration changed: ' + key)
    parsed = parse_config(source)
    expected = (('Upscalers', 'Dx12Upscaler'), ('FrameGen', 'FGInput'),
                ('FrameGen', 'FGNvngxReplacement'))
    for section, key in expected:
        present = [name for name in parsed.sections() if parsed.has_option(name, key)]
        if present and present != [section]:
            raise ValueError('Managed configuration setting is misplaced or repeated: ' + key)
    # A fresh install gets working 2.0 defaults. Existing 2.0 choices remain
    # user-owned. The narrow 1.9 migration only changes values the old adapter
    # itself selected for its retired DLSS-style layout.
    if source == template:
        settings = [('Dx12Upscaler', 'auto'), ('FGInput', 'nvngxfg'),
                    ('FGNvngxReplacement', 'HelixSR')]
    elif previous_version == '1.9.3':
        settings = []
        if parsed.get('Upscalers', 'Dx12Upscaler', fallback='').strip().lower() == 'dlss':
            settings.append(('Dx12Upscaler', 'auto'))
        if parsed.get('FrameGen', 'FGNvngxReplacement', fallback='').strip().lower() == 'ffx':
            settings += [('FGInput', 'nvngxfg'), ('FGNvngxReplacement', 'HelixSR')]
    else:
        settings = []
    return pin_config(source, template, settings)
