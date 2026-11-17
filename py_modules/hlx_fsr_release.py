"""Pinned, prebuilt HLX FSR 4 from official HelixSR releases (3.4.1; 3.3.0 and 3.2.0 for existing installs).

AMD's SDK 2.4.0 supplies the FSR 4.1.2 network. Each release contains the HLX
implementation and AMD's own provider; 3.3.0 adds HLX FSR 4 Full as a Scaler
custom upscaler, and 3.4.1 adds HelixSR's own frame generation (Scaler's
HelixSR-FG custom DLSS FG replacement) with NVIDIA Streamline 2.14.16. None is
Model E, and no upstream setup code is executed. New installs use 3.4.1 only.
3.3.0 and 3.2.0 stay recognized so their installs keep working and can update.
"""
from collections.abc import Mapping
import hashlib

from helix20_release import _hash
import helix_settings
from optiscaler_setup import parse_config, pin_config

VARIANT_ID = 'hlx-fsr4-1-2'
ADAPTER = 'hlx-fsr4-prebuilt-v1'
OUTPUT_DLL = 'HLX-FSR4/amd_fidelityfx_upscaler_dx12.dll'
MANIFEST_PATH = 'HLX-FSR4/HLX-FSR4-built.txt'
SCALER_DIR = 'helixsr-scaler/'
SCALER_INI = SCALER_DIR + 'OptiScaler.ini'
FULL_NAME = 'HLX FSR 4 Full'
FULL_DIR = SCALER_DIR + 'OptiScaler/custom/' + FULL_NAME + '/ffx/'
# HelixSR's frame generation in 3.4.x: a Scaler custom folder with an nvngx_dlssg replacement,
# selected by FGInput=nvngxfg with FGNvngxReplacement=HelixSR-FG in games with DLSS Frame Generation.
FG_NAME = 'HelixSR-FG'
FG_DIR = SCALER_DIR + 'OptiScaler/custom/' + FG_NAME + '/dlssg/'
STREAMLINE_DIR = SCALER_DIR + 'OptiScaler/streamline/'
# 0 keeps the game's own DLSS FG multiplier; 2-6 set [DLSSG] OverrideInterpolationCount (1-5 generated frames).
FG_MULTIPLIERS = (0, 2, 3, 4, 5, 6)
_OUTPUT_320 = 'b9f906ca669e444a9fc4d3727192a0d881c8e4c62557bf3a8063d2d694e806ae'
_OUTPUT_330 = '4b90351a93cdfb055fb1f2b7224e0cb26fa6aecf3e5ef491acaf6f89dbb7da3b'
_OUTPUT_330_20261111 = '143164cf365335d6abaa8a72707c06b6586ce487b22e61284aaba44b169e4108'
_OUTPUT_341 = '8b3def5f363e3221c484ef6d196360c4695ac0ea66c02d8a88c26f51fc63fc94'

# SHA-256 of each exact file consumed or kept as evidence. The plugin verifies the complete ZIP, then
# caches only this reviewed subset locally. No setup code is executed.
_PINS_320 = {
    OUTPUT_DLL: (57549124, _OUTPUT_320),
    MANIFEST_PATH: (221, 'dd0876440bf02274da6d7af8c5f1f207b2bba6ed25d1a837096df986342e81d9'),
    'LICENSE': (2531, '8898ab9d1ae5e59f5e222aca87e6a30bb073e0b927fe0971dd20c49b79fb81e6'),
    'THIRD_PARTY_NOTICES.md': (9433, '30af91343f4eb16df9ab933cd28b62f95a8d9796ec5955884dffa1e636db865c'),
    'SOURCE.md': (1126, '895c6ff5be9df738a0a23434a979fc6b2d3d704d8cf386a8b5926894c21acbaf'),
    SCALER_INI: (61790, 'b297222f1a482db8afece150d0b3181a2e8efbb8971b9ea06dd50a2214f0a375'),
    SCALER_DIR + 'OptiScaler.dll': (29447168, '7c7bcfe27bf2b1da1af9b96cb78f3efaf744bdf1184c87ef7dbce6b2f189e458'),
    SCALER_DIR + 'Licenses/DirectX_LICENSE.txt': (13147, '5239850894610071566f7ecee0b751fde43c862032d92b99d7d0f596b3433ebd'),
    SCALER_DIR + 'Licenses/FidelityFX_v2_LICENSE.md': (61784, 'f0da09d71ad5c82759a179e774535d4a829e5c96c49294167c1152402b2cb400'),
    SCALER_DIR + 'Licenses/OptiPatcher_LICENSE.txt': (1067, '886806761aff7c3ad36c23b7eabbf46860039c277cba25dda49232ca4e84d05b'),
    SCALER_DIR + 'Licenses/OptiScaler_LICENSE.txt': (35149, '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986'),
    SCALER_DIR + 'Licenses/XeSS_LICENSE.txt': (4194, '784be42c39a4a4d03cf85d88e15e59d75828fca773ce45b8dbfffbd7eaf208df'),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_framegeneration_dx12.dll': (40085776, '02297beedd285e822d3a64f314cf00faf378dcec0edc47ff0c4dd71b3a8c2f18'),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_loader_dx12.dll': (26376, 'e2d85aa05a9bd9ed8b38935fdf5199372cca6f74c12015143bb6f945ee1608aa'),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_upscaler_dx12.amd.dll': (57664272, 'aad4fccccb29084a655f9a4f9f613bd22c8c03fb4a0f8840148cc6543b4ccace'),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll': (57549124, _OUTPUT_320),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_vk.dll': (9332432, 'a1624cc4238fef046f30c4d80ce3f47be63fc5f5373f49e3ee9edb9960f54c78'),
    SCALER_DIR + 'OptiScaler/libxell.dll': (415368, 'd2030dcd694fda8f2ec7e044b13e6db8f0b56d4ba9113a5efad334e3f3ded8c7'),
    SCALER_DIR + 'OptiScaler/libxess.dll': (77795704, '251659dd84a3e84de67c886a4186e01f3eca49b00641906fe38bb6b807e5d5b7'),
    SCALER_DIR + 'OptiScaler/libxess_dx11.dll': (156016, 'c7cfe86f0c9d94e4fb3696d3cd5035e2bbb6a8b1b0572f8b7395a4cdfd0c625e'),
    SCALER_DIR + 'OptiScaler/libxess_fg.dll': (22957432, 'ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27'),
    SCALER_DIR + 'OptiScaler/D3D12_OptiScaler/D3D12Core.dll': (3351064, '07d286c306f8117321422affd9e6388c12d0fb4be1c7fc689d9e899324feeb24'),
    SCALER_DIR + 'OptiScaler/plugins/OptiPatcher.asi': (123392, 'b36590bbb57a587a55f535aa0d4e618c5f43f5d2e6bc332837acd5604600ce6d'),
}

# HelixSR 3.3.0 as republished on 2026-11-12 (upstream updated the asset in place again;
# its notes: per-pass timing for HelixSR Desktop's speed test, pictures unchanged).
# The Vulkan-only HLX FSR 4 file and the unbuilt HLX DLSS / Preset K files are not used.
_PINS_330 = {
    OUTPUT_DLL: (56846148, _OUTPUT_330),
    MANIFEST_PATH: (178, '9bd255377e96dd39d34b4244184e50f9c6aa23694a42bbaab071a3ec3f430367'),
    'LICENSE': (2531, '8898ab9d1ae5e59f5e222aca87e6a30bb073e0b927fe0971dd20c49b79fb81e6'),
    'THIRD_PARTY_NOTICES.md': (9727, '87a6813d2b037ada224fe3178090c2eedd66b75b064a7f3d5c40f239dad4003b'),
    'SOURCE.md': (1110, '8aa028e9cd23b349c9af30bbb9a74965ec05473a961e0a1c034c6ab08e21beb9'),
    SCALER_INI: (62215, '434ca2c49c33ca581c400863243e376f3bd2f14324ea89ecd3771dff7b8fadee'),
    SCALER_DIR + 'OptiScaler.dll': (29664256, '74614d631767c299750d14daa14483a495491ff75bcde8965f161cdb3c7fc1b0'),
    SCALER_DIR + 'Licenses/DirectX_LICENSE.txt': (13147, '5239850894610071566f7ecee0b751fde43c862032d92b99d7d0f596b3433ebd'),
    SCALER_DIR + 'Licenses/FidelityFX_v2_LICENSE.md': (61784, 'f0da09d71ad5c82759a179e774535d4a829e5c96c49294167c1152402b2cb400'),
    SCALER_DIR + 'Licenses/OptiPatcher_LICENSE.txt': (1067, '886806761aff7c3ad36c23b7eabbf46860039c277cba25dda49232ca4e84d05b'),
    SCALER_DIR + 'Licenses/OptiScaler_LICENSE.txt': (35149, '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986'),
    SCALER_DIR + 'Licenses/XeSS_LICENSE.txt': (4194, '784be42c39a4a4d03cf85d88e15e59d75828fca773ce45b8dbfffbd7eaf208df'),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_framegeneration_dx12.dll': (40085776, '02297beedd285e822d3a64f314cf00faf378dcec0edc47ff0c4dd71b3a8c2f18'),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_loader_dx12.dll': (26376, 'e2d85aa05a9bd9ed8b38935fdf5199372cca6f74c12015143bb6f945ee1608aa'),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_upscaler_dx12.amd.dll': (57664272, 'aad4fccccb29084a655f9a4f9f613bd22c8c03fb4a0f8840148cc6543b4ccace'),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll': (56846148, _OUTPUT_330),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_vk.dll': (9332432, 'a1624cc4238fef046f30c4d80ce3f47be63fc5f5373f49e3ee9edb9960f54c78'),
    SCALER_DIR + 'OptiScaler/libxell.dll': (415368, 'd2030dcd694fda8f2ec7e044b13e6db8f0b56d4ba9113a5efad334e3f3ded8c7'),
    SCALER_DIR + 'OptiScaler/libxess.dll': (77795704, '251659dd84a3e84de67c886a4186e01f3eca49b00641906fe38bb6b807e5d5b7'),
    SCALER_DIR + 'OptiScaler/libxess_dx11.dll': (156016, 'c7cfe86f0c9d94e4fb3696d3cd5035e2bbb6a8b1b0572f8b7395a4cdfd0c625e'),
    SCALER_DIR + 'OptiScaler/libxess_fg.dll': (22957432, 'ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27'),
    SCALER_DIR + 'OptiScaler/D3D12_OptiScaler/D3D12Core.dll': (3351064, '07d286c306f8117321422affd9e6388c12d0fb4be1c7fc689d9e899324feeb24'),
    SCALER_DIR + 'OptiScaler/plugins/OptiPatcher.asi': (123392, 'b36590bbb57a587a55f535aa0d4e618c5f43f5d2e6bc332837acd5604600ce6d'),
    FULL_DIR + 'amd_fidelityfx_upscaler_dx12.dll': (12945096, '1808af1ae4a495c9eb6e7b0c745532c45d5d1c85a0e6c917f949efe726c9c61b'),
    FULL_DIR + 'hlx_fsr4.ini': (1077, '60bbe761da9d0063a46fbb6c624e8e6b633166f685da28fd0503dd6ffe6949a8'),
}

# The 2026-11-11 build of 3.3.0 that plugin 0.1.44 installed. Upstream replaced it in place on
# 2026-11-12, so it is never downloaded again. Its recipe and output stay recognized only so
# existing installs keep their model identity, are never mistaken for a game's original DLL,
# and can update to the current build.
_PINS_330_20261111 = {**_PINS_330,
    OUTPUT_DLL: (56843076, _OUTPUT_330_20261111),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll': (56843076, _OUTPUT_330_20261111),
    FULL_DIR + 'amd_fidelityfx_upscaler_dx12.dll': (12942024, '9a72fe1b5c4fcfa5dd23e0d25c0488df7c5c93c78a16cfeb80a178b4992c7757'),
}


# HelixSR 3.4.1 (2026-11-17), with HelixSR Scaler 2.3.1. 3.4.0 was replaced the next day and is not
# reviewed. Same layout as 3.3.0: new HLX FSR 4 and HLX FSR 4 Full builds (Full no longer needs AMD's
# DLL beside it), HelixSR frame generation in Scaler's custom folder, and NVIDIA Streamline 2.14.16
# in OptiScaler/streamline (Scaler uses it in place of a game's older Streamline for up to 6x).
_PINS_341 = {**_PINS_330,
    OUTPUT_DLL: (58185808, _OUTPUT_341),
    'THIRD_PARTY_NOTICES.md': (14665, '9b6481e2a7ae58f2d54c7015ecb253c6ec21f2f9e10ad59e9de279323a7f8f7b'),
    'SOURCE.md': (1110, '49d56c50ab03f2396c35b209e8ad9d98704aee0c0ecb5af83d05dfe5d5efde9f'),
    SCALER_INI: (62634, '1006eaf4dc706254c57ab6fba87ba7e76cec18d74fb4398b9d60ff3f3efed8d9'),
    SCALER_DIR + 'OptiScaler.dll': (29667328, 'af976f52ceb60e90d8bb099267d734169b398511f5007144419179890f86f8f3'),
    SCALER_DIR + 'Licenses/Streamline_LICENSE.txt': (1591, '7b6f23e7d6f3ad6292f9308d2b42cdc3d82ae4e9b2abb55f230279d83bedd43d'),
    SCALER_DIR + 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll': (58185808, _OUTPUT_341),
    FULL_DIR + 'amd_fidelityfx_upscaler_dx12.dll': (22876979, '31d59a0f95bcdaf268d2f37ed6885c05037ad07b4d07131bb29835365d70fc57'),
    FULL_DIR + 'hlx_fsr4.ini': (1104, 'd78dc1d929ed10b0d3fb2c9a9c5f8e420a9339a0f4fd5c261720eb49b392cab7'),
    FG_DIR + 'helixsr.ini': (618, 'a386592daa86fc05040a5e1f233896d06d62bf7227bcc2df954228e9683834d8'),
    FG_DIR + 'nvngx_dlssg.dll': (1256448, '81fbb36d5d318f2b2fda254e87f69e641d67a2a2cc026f23031912b609b9ec8a'),
    STREAMLINE_DIR + 'sl.common.dll': (843904, '38eea3b4209afc455636ea372b5933d65fcc13becec6c84d101dcfc4d8648f75'),
    STREAMLINE_DIR + 'sl.dlss_g.dll': (637056, '3ed9538df724993bea8a050195a6a78b9c8c8a566d5b05ade477aab3c390e90f'),
    STREAMLINE_DIR + 'sl.interposer.dll': (652928, 'b1d7395aebd7b9722841d64dcf7433680020b6a8e421f851c16d5ba0c2182edf'),
    STREAMLINE_DIR + 'sl.pcl.dll': (360064, '5698c38e722318681f215c9fe68e45b9bedd51378acc699d8eee26e961e57770'),
    STREAMLINE_DIR + 'sl.reflex.dll': (388736, '443577e869352436ff7ec8f4d9c90418d3e95368436ce219261e0f4f07a38122'),
}


def _recipe(pins):
    return hashlib.sha256(b''.join((name + '\0' + digest + '\0').encode()
                                   for name, (_, digest) in sorted(pins.items()))).hexdigest()


def _custom_library(parsed):
    return next((key for key in ('OptiDllPath', 'FfxDx12Path', 'FfxDx12SRPath')
                 if parsed.get('Libraries', key, fallback='auto').strip().lower() != 'auto'), None)


def _helixsr_fg(parsed):
    """FGInput=nvngxfg with Scaler's HelixSR-FG replacement, frame generation not switched off."""
    get = lambda section, key: parsed.get(section, key, fallback='auto').strip().lower()
    return (get('FrameGen', 'Enabled') not in ('false', 'off', '0') and get('FrameGen', 'FGInput') == 'nvngxfg'
            and get('FrameGen', 'FGNvngxReplacement') == FG_NAME.lower())


def _fg_multiplier(parsed):
    count = parsed.get('DLSSG', 'OverrideInterpolationCount', fallback='auto').strip()
    return int(count) + 1 if count in ('1', '2', '3', '4', '5') else 0


class Release:
    """One reviewed HLX FSR 4 release. Attribute names match the other release adapters."""
    VARIANT_ID, ADAPTER, OUTPUT_DLL, MANIFEST_PATH = VARIANT_ID, ADAPTER, OUTPUT_DLL, MANIFEST_PATH
    SCALER_DIR, SCALER_INI = SCALER_DIR, SCALER_INI

    def __init__(self, version, sha256, size, pins, full, fg=False, replaced=()):
        self.MODERN_VERSION = version
        self.RELEASE_SHA256, self.RELEASE_SIZE = sha256, size
        self.RELEASE_URL = f'https://github.com/lonewolf0622/HelixSR/releases/download/v{version}/HelixSR-{version}.zip'
        self.RELEASE_PAGE = f'https://github.com/lonewolf0622/HelixSR/releases/tag/v{version}'
        self.SOURCE_LICENSE_URL = f'https://github.com/lonewolf0622/HelixSR/blob/v{version}/THIRD_PARTY_NOTICES.md'
        self.PINS = dict(pins)
        self.OUTPUT_SHA256 = self.PINS[OUTPUT_DLL][1]
        self.FULL = full
        self.FG = fg
        self.RECIPE_SHA256 = _recipe(self.PINS)
        # Earlier builds of this same version that upstream replaced in place. Recognized for
        # installed games only: downloads, caches and repairs always use the current PINS.
        self.REPLACED_RECIPES = frozenset(_recipe(old) for old in replaced)
        self.REPLACED_OUTPUTS = frozenset(old[OUTPUT_DLL][1] for old in replaced)

    def __repr__(self):
        return f'<HLX FSR release {self.MODERN_VERSION}>'

    def modern(self, record):
        return isinstance(record, Mapping) and record.get('version') == self.MODERN_VERSION

    def release(self):
        return dict(version=self.MODERN_VERSION, sha256=self.RELEASE_SHA256, size=self.RELEASE_SIZE,
                    url=self.RELEASE_URL, page=self.RELEASE_PAGE, metadata_source='reviewed-release',
                    license_url=f'https://github.com/lonewolf0622/HelixSR/blob/v{self.MODERN_VERSION}/LICENSE')

    def validate_release(self, value):
        expected = self.release()
        if (not isinstance(value, Mapping) or type(value.get('size')) is not int or
                any(value.get(k) != expected[k] for k in ('version', 'sha256', 'size', 'url', 'page'))):
            raise ValueError(f'Official HelixSR {self.MODERN_VERSION} release identity changed '
                             '(upstream may have replaced the archive); an app update is required')
        return value

    def verify_outputs(self, package):
        for name, (expected_size, expected_digest) in self.PINS.items():
            digest, size = _hash(package, name, expected_size)
            if size != expected_size or digest != expected_digest:
                raise ValueError('Reviewed HLX FSR 4 payload or notice changed: ' + name)

    def verify_recipe(self, package):
        self.verify_outputs(package)
        return dict(id=VARIANT_ID, adapter=ADAPTER, recipe_sha256=self.RECIPE_SHA256)

    def payload_files(self):
        return tuple(self.PINS)

    def mutable_configs(self):
        return (SCALER_INI,)

    def direct_pairs(self):
        return ((OUTPUT_DLL, '{dll}'),)

    def scaler_pairs(self):
        return tuple((name, 'dxgi.dll' if name == SCALER_DIR + 'OptiScaler.dll'
                      else name.removeprefix(SCALER_DIR)) for name in self.PINS
                     if name.startswith(SCALER_DIR) and name != SCALER_INI)

    def read_settings(self, source):
        p = parse_config(source)
        state = helix_settings.read_settings(source)
        backend = p.get('Upscalers', 'Dx12Upscaler', fallback='auto').strip().lower()
        index = p.get('FSR', 'UpscalerIndex', fallback='auto').strip()
        if _custom_library(p):
            state['upscaler'] = 'unsupported'
        elif self.FULL and backend == FULL_NAME.lower():
            state['upscaler'] = 'hlx-fsr-full'
        else:
            state['upscaler'] = {'0': 'hlx-fsr', '1': 'fsr'}.get(index, 'unsupported') if backend == 'ffx' else 'unsupported'
        if state['provider'] == 'helixsr':
            # HelixSR 2.0's own FG files are not part of any HLX release.
            state['provider'] = 'unsupported'
        if self.FG and _helixsr_fg(p):
            state.update(provider='helixsr', multiplier=_fg_multiplier(p), multiplier_choices=list(FG_MULTIPLIERS))
        state.update(family='hlx-fsr', release=self.MODERN_VERSION, full_available=self.FULL, fg_available=self.FG,
                     notes='AMD FSR uses the best version offered by the GPU. FSR and XeSS frame generation '
                           'require game support. ' + (
                               'HelixSR FG needs a DirectX 12 game with DLSS Frame Generation switched on in the game.'
                               if self.FG else f'HelixSR {self.MODERN_VERSION} has no HelixSR FG.'))
        return state

    def validate_scaler_source(self, source):
        parsed = parse_config(source)
        override = _custom_library(parsed)
        if override:
            raise ValueError('Set ' + override + ' to auto before selecting HLX FSR 4; it overrides the reviewed DLLs')
        # Retained 2.0 users must choose a compatible FG provider before upgrading.
        # An unused old replacement setting is harmless to an upscaler FG input.
        if (parsed.get('FrameGen', 'FGNvngxReplacement', fallback='auto').strip().lower() == 'helixsr'
                and helix_settings.read_settings(source)['provider'] == 'helixsr'):
            raise ValueError(f'HelixSR 2.0 frame generation does not carry over to HelixSR {self.MODERN_VERSION}. '
                             'Select Off, FSR or XeSS FG before upgrading.' +
                             (' HelixSR FG can be selected again afterwards.' if self.FG else ''))
        if not self.FG and _helixsr_fg(parsed):
            raise ValueError(f'HelixSR {self.MODERN_VERSION} has no HelixSR frame generation. '
                             'Select Off, FSR or XeSS FG first.')

    def configuration(self, source, template, previous_version=None):
        self.validate_scaler_source(source)
        if source != template and previous_version == self.MODERN_VERSION:
            return source
        # Another reviewed HLX release keeps the user's Scaler settings, including the upscaler.
        # A Full selection cannot carry over to a release without HLX FSR 4 Full.
        if source != template and previous_version in RELEASES and (self.FULL or parse_config(source).get(
                'Upscalers', 'Dx12Upscaler', fallback='auto').strip().lower() != FULL_NAME.lower()):
            return source
        # The user selected HLX; Scaler's auto can choose XeSS or DLSS. An explicit
        # D3D12 FFX output and version index select HLX through any supported input.
        return pin_config(source, template, [('Dx12Upscaler', 'ffx'), ('UpscalerIndex', '0')])

    def update_settings(self, source, changes):
        if not isinstance(changes, dict) or set(changes) - {'provider', 'upscaler', 'multiplier', 'overlay'}:
            raise ValueError('Unsupported HLX FSR setting')
        providers = ('off', 'fsr', 'xess') + (('helixsr',) if self.FG else ())
        if 'provider' in changes and changes['provider'] not in providers:
            raise ValueError(f'HelixSR {self.MODERN_VERSION} supports Off, ' +
                             ('HelixSR FG, FSR FG or XeSS FG' if self.FG else 'FSR FG or XeSS FG'))
        fg = {k: v for k, v in changes.items() if k != 'upscaler'}
        current = self.read_settings(source) if fg else None
        if fg and changes.get('provider', current['provider']) == 'helixsr':
            source = self._helixsr_fg_settings(source, fg, current)
        elif fg:
            source = helix_settings.update_settings(source, fg)
            if current['provider'] == 'helixsr' and _fg_multiplier(parse_config(source)):
                # Leaving HelixSR FG: its multiplier override must not linger for the game's DLSS FG.
                source = helix_settings.apply_edits(source, [('DLSSG', 'OverrideInterpolationCount', 'auto')])
        if 'upscaler' not in changes:
            return source
        allowed = ('hlx-fsr', 'fsr') + (('hlx-fsr-full',) if self.FULL else ())
        if changes['upscaler'] not in allowed:
            raise ValueError('Unsupported HLX FSR upscaler')
        if _custom_library(parse_config(source)):
            raise ValueError('Remove custom FFX library overrides before switching upscalers')
        template = '[Upscalers]\nDx12Upscaler=ffx\n[FSR]\nUpscalerIndex=0\n'
        if changes['upscaler'] == 'hlx-fsr-full':
            # Scaler selects a custom upscaler by its folder name; it uses AMD's provider from OptiScaler/.
            return pin_config(source, template, [('Dx12Upscaler', FULL_NAME)])
        return pin_config(source, template, [('Dx12Upscaler', 'ffx'),
                          ('UpscalerIndex', '0' if changes['upscaler'] == 'hlx-fsr' else '1')])

    def _helixsr_fg_settings(self, source, changes, current):
        multiplier = changes.get('multiplier', current['multiplier'] if current['provider'] == 'helixsr' else 0)
        if type(multiplier) is not int or multiplier not in FG_MULTIPLIERS:
            raise ValueError('HelixSR FG multipliers are 2× to 6×, or the game setting')
        if 'overlay' in changes:
            source = helix_settings.update_settings(source, {'overlay': changes['overlay']})
        edits = []
        if 'provider' in changes:
            # Scaler's documented route: the game's DLSS FG through Scaler's HelixSR-FG replacement.
            edits += [('FrameGen', 'Enabled', 'true'), ('FrameGen', 'FGInput', 'nvngxfg'),
                      ('FrameGen', 'FGOutput', 'auto'), ('FrameGen', 'FGNvngxReplacement', FG_NAME)]
        if 'provider' in changes or 'multiplier' in changes:
            edits.append(('DLSSG', 'OverrideInterpolationCount', str(multiplier - 1) if multiplier else 'auto'))
        return helix_settings.apply_edits(source, edits) if edits else source


V320 = Release('3.2.0', 'a4e83da8b4335a886197aef10e8f8a8947a2e32e5e1eebfdf060ff00724c17c7', 217396302,
               _PINS_320, full=False)
V330 = Release('3.3.0', '7d6c0a4adeb5237004fc6fbe211d39705d62d49f23c51cc8f4ea987281d0a56b', 279492763,
               _PINS_330, full=True, replaced=(_PINS_330_20261111,))
V341 = Release('3.4.1', '31ab3fcee0aa385712c123c6717dc579c60aeaeff40f705dbe91753f96ac46da', 294792182,
               _PINS_341, full=True, fg=True)
RELEASES = {r.MODERN_VERSION: r for r in (V341, V330, V320)}
LATEST = V341


def output_sha256s():
    """Digests of every reviewed HLX output DLL, including replaced builds; never a game's original provider."""
    return {r.OUTPUT_SHA256 for r in RELEASES.values()} | {d for r in RELEASES.values() for d in r.REPLACED_OUTPUTS}


def installed_recipes():
    """Recipe digests an installed game may carry: current builds and builds upstream replaced in place."""
    return {r.RECIPE_SHA256 for r in RELEASES.values()} | {d for r in RELEASES.values() for d in r.REPLACED_RECIPES}
SOURCE_LICENSE_URL = LATEST.SOURCE_LICENSE_URL


def modern(record):
    """Any reviewed HLX FSR 4 release."""
    return isinstance(record, Mapping) and record.get('version') in RELEASES


def for_record(record):
    if not modern(record):
        raise ValueError('Not a reviewed HLX FSR 4 release')
    return RELEASES[record['version']]


def for_package(package):
    """Identify an unpacked reviewed release by its pinned files."""
    errors = []
    for release in RELEASES.values():
        try:
            return release, release.verify_recipe(package)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    raise ValueError(f'HLX FSR 4 needs the reviewed HelixSR {LATEST.MODERN_VERSION} release: ' + '; '.join(errors))
