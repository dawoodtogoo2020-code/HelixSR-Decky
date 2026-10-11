"""Read-only Linux capabilities, with explicit evidence limits."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def system_environment(source=None):
    env = dict(os.environ if source is None else source)
    if not (env.get('APPIMAGE') or env.get('APPDIR') or getattr(sys, 'frozen', False)):
        return env
    from host_environment import host_environment
    return host_environment(env)


def system_status():
    env = system_environment()
    tools = {name: shutil.which(name, path=env.get('PATH')) for name in
             ('bash', 'python3', 'curl', 'unzip', 'vulkaninfo')}
    architecture = platform.machine().lower()
    vulkan = {'available': None, 'evidence': '', 'error': ''}
    if tools['vulkaninfo']:
        try:
            probe = subprocess.run([tools['vulkaninfo'], '--summary'], env=env,
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
            vulkan.update(available=probe.returncode == 0,
                          evidence=probe.stdout[:16384], error=probe.stderr[:4096])
        except (OSError, subprocess.TimeoutExpired) as exc:
            vulkan['error'] = str(exc)
    else:
        vulkan['error'] = 'vulkaninfo is unavailable; Vulkan support has not been checked'
    gpu = []
    for device in sorted(Path('/sys/class/drm').glob('card[0-9]*/device')):
        try:
            vendor = (device / 'vendor').read_text().strip().lower()
            pci_id = (device / 'device').read_text().strip().lower()
            gpu.append({'vendor_id': vendor, 'device_id': pci_id,
                        'amd': vendor == '0x1002', 'source': str(device)})
        except OSError:
            continue
    return dict(platform=platform.system(), architecture=architecture,
        supported_architecture=platform.system() == 'Linux' and architecture in ('x86_64', 'amd64'),
        root=hasattr(os, 'geteuid') and os.geteuid() == 0, tools=tools, vulkan=vulkan, gpu=gpu,
        notes=['PCI vendor IDs identify the vendor, not RDNA generation or HelixSR compatibility.',
               'Game compatibility requires the per-game scan and DirectX 12 confirmation.',
               'This capability check does not establish game runtime or physical Steam Machine testing.'])
