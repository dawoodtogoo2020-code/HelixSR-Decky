"""Reviewed model capabilities, separate from upstream versions and input routes.

An official URL/digest proves where an archive came from, not which network its
converter generates. New model families need a reviewed recipe and payload
adapter before they can become selectable in either frontend.
"""
import hashlib
import json
import struct

DEFAULT_VARIANT = 'helixsr-model-e'
ADAPTER = 'separate-network-v1'
RECIPE_FILES = (
    "helixsr-setup.sh",
    "setup/helixsr_setup.py",
    "setup/kernels/common/fp16.h",
    "setup/kernels/common/port_cpp.h",
    "setup/kernels/common/port_hlsl.hlsli",
    "setup/kernels/rt/px_common.h",
    "setup/kernels/rt/px_cpp.h",
    "setup/kernels/rt/px_hlsl.h",
    "setup/kernels/u5/u5_memory.h",
    "setup/lib/compact_hlsl.py",
    "setup/lib/compact_u5.py",
    "setup/lib/extract_ptx.py",
    "setup/lib/extract_weights.py",
    "setup/lib/family_hlsl.py",
    "setup/lib/family_k/gen_helper.py",
    "setup/lib/family_k/trace_frags.py",
    "setup/lib/family_k/two_sites.json",
    "setup/lib/family_k/validate.py",
    "setup/lib/family_u/gen_helper.py",
    "setup/lib/family_u/ptxsim_up.py",
    "setup/lib/family_u/trace_frags.py",
    "setup/lib/family_u/two_sites.json",
    "setup/lib/family_u/validate.py",
    "setup/lib/fast_tiles.py",
    "setup/lib/kernels.py",
    "setup/lib/load_fence.py",
    "setup/lib/model/launch_synth",
    "setup/lib/model/launch_synth.cpp",
    "setup/lib/model/launch_synth.exe",
    "setup/lib/model/model.cpp",
    "setup/lib/model/model.h",
    "setup/lib/model/model_gen.inc",
    "setup/lib/ptx2hlsl.py",
    "setup/lib/ptxsim.py",
    "setup/lib/regen_kernels.py",
    "setup/lib/samplers.py",
    "setup/lib/splitk_hlsl.py",
    "setup/lib/trace_tables.py",
    "setup/lib/u5_roll.py",
    "setup/lib/u5_rows.py",
)
REVIEWED_RECIPES = {
    'ac43f9144497a2e9f506d0bb05577328c667d3c657d466f469b9bf13558bb791': DEFAULT_VARIANT,
    '712dc923a8149fc0d2fcc6099d2f87df11d77c5999323a41bbc71075c8bd647d': DEFAULT_VARIANT,
    # Official 1.8.1 replacement: installer-only converter edits; separate output unchanged.
    '93930e9c131c82fe7810181cc8e6bc81cf18e9203737a9d28d769be5983acaef': DEFAULT_VARIANT,
}
VARIANTS = {
    DEFAULT_VARIANT: dict(id=DEFAULT_VARIANT, label='HelixSR Model E',
                         source='NVIDIA DLSS 310.7.0', adapter=ADAPTER,
                         routes=['direct', 'optiscaler']),
}
FUTURE_NOTE = ('DLSS 4 and FSR-derived models will appear here when upstream releases '
               'them and their preparation and installation are supported. Input '
               'routes and frame generation are separate from the model.')


def select_variant(variant_id=None):
    key = DEFAULT_VARIANT if variant_id is None else variant_id
    if not isinstance(key, str) or key not in VARIANTS:
        raise ValueError('This HelixSR model is not supported. Update the app and check available variants.')
    return dict(VARIANTS[key])


def catalog():
    return dict(variants=[dict(v) for v in VARIANTS.values()], default=DEFAULT_VARIANT,
                note=FUTURE_NOTE)


def recipe_digest(package):
    expected = {n for n in RECIPE_FILES if n.startswith('setup/')}
    actual = {p.relative_to(package).as_posix() for p in (package / 'setup').rglob('*') if p.is_file()}
    if actual != expected | {'setup/helixsr_install.py'}:
        raise ValueError('This upstream model recipe needs support in an app update: conversion files changed')
    hashes = {}
    for name in RECIPE_FILES:
        path = package / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 4 << 20:
            raise ValueError('HelixSR model recipe is missing or unsafe: ' + name)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def verify_recipe(package, variant_id=None):
    selected = select_variant(variant_id)
    digest = recipe_digest(package)
    if REVIEWED_RECIPES.get(digest) != selected['id']:
        raise ValueError('This upstream model recipe needs support in an app update. '
                         'No network was built and no game files were changed. '
                         'Check plugin or desktop app updates and report the HelixSR version.')
    return dict(id=selected['id'], adapter=selected['adapter'], recipe_sha256=digest)


def valid_variant(value):
    return (isinstance(value, dict) and isinstance(value.get('id'), str) and value['id'] in VARIANTS
            and set(value) == {'id', 'adapter', 'recipe_sha256'}
            and value.get('adapter') == VARIANTS[value['id']]['adapter']
            and isinstance(value.get('recipe_sha256'), str)
            and REVIEWED_RECIPES.get(value['recipe_sha256']) == value['id'])


SOURCE_SHA256 = 'be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e'
WEIGHTS_SIZE = 1903872
WEIGHTS_SHA256 = '762adfde720035f7ac43910846e0ce6826c239bcd41f863196f77c547ae57153'
KERNEL_NAMES = tuple(('px_' + name).encode() for name in (
    'auto_exposure', 'auto_exposure_copy', 'clear_buffer', 'copy_exposure',
    'luma_convert', 'reduce_sum', 'u10', 'k8_rel', 'k8_hdr_colvar_mvhi',
    'k8_hdr_colvar_mvlo', 'k8_hdr_mvdiff_mvhi', 'k8_hdr_mvdiff_mvlo',
    'k8_ldr_colvar_mvhi', 'k8_ldr_colvar_mvlo', 'k8_ldr_mvdiff_mvhi',
    'k8_ldr_mvdiff_mvlo', 'k4', 'k9', 'k10', 'k11', 'u6', 'k7', 'u9',
    'u5', 'u8', 'k5', 'k5f', 'k5n', 'u4', 'u5_table'))


def verify_outputs(package):
    weights = package / 'helixsr_weights.bin'
    manifest = package / 'helixsr_setup.json'
    if not manifest.is_file() or manifest.stat().st_size > 4096:
        raise ValueError('Generated HelixSR model identity is missing; see the build log')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or set(data) != {'source_sha256', 'ptx_target', 'shaders', 'wave64', 'weights_sha256'}
            or data['source_sha256'] != SOURCE_SHA256 or data['weights_sha256'] != WEIGHTS_SHA256
            or data['ptx_target'] not in ('sm_80', 'sm_89') or type(data['wave64']) is not bool
            or type(data['shaders']) is not int
            or data['shaders'] != len(KERNEL_NAMES) * (2 if data['wave64'] else 1)
            or weights.stat().st_size != WEIGHTS_SIZE
            or hashlib.sha256(weights.read_bytes()).hexdigest() != WEIGHTS_SHA256):
        raise ValueError('Generated HelixSR model does not match the selected Model E recipe')
    pak = package / 'helixsr_kernels.pak'
    with pak.open('rb') as source:
        header = source.read(16)
        if len(header) != 16 or header[:8] != b'HXSRKPAK':
            raise ValueError('Generated HelixSR kernels have an unsupported format')
        version, count = struct.unpack('<II', header[8:])
        if version != 2 or count != data['shaders']:
            raise ValueError('Generated HelixSR kernels do not match the model manifest')
        names, end = set(), 16 + 40 * count
        size = pak.stat().st_size
        for _ in range(count):
            row = source.read(40)
            if len(row) != 40:
                raise ValueError('Generated HelixSR kernel table is truncated')
            name, offset, length = struct.unpack('<32sII', row)
            name = name.split(b'\0', 1)[0]
            if not name or name in names or offset != end or not length or offset + length > size:
                raise ValueError('Generated HelixSR kernel table is invalid')
            names.add(name)
            end += length
        if end != size:
            raise ValueError('Generated HelixSR kernels have unexpected trailing bytes')
        expected = set(KERNEL_NAMES)
        if data['wave64']:
            expected |= {name + b'_w64' for name in KERNEL_NAMES}
        if names != expected:
            raise ValueError('Generated HelixSR kernels do not match the selected model recipe')


def variant_label(value):
    return VARIANTS[value['id']]['label'] if valid_variant(value) else 'Model unverified'


def package_selection(record):
    """Path-independent identity binds model, release, recipe and output hashes."""
    fields = {k: record.get(k) for k in ('version', 'release_sha256', 'variant', 'files')}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def same_release(left, right):
    return all(left.get(key) == right.get(key) for key in ('version', 'sha256'))
