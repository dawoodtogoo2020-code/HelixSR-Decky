"""Host subprocess environments must not inherit the frozen app's runtime."""
import os
import sys


def host_environment(source=None):
    env = dict(os.environ if source is None else source)
    bundled = bool(env.get('APPIMAGE') or env.get('APPDIR') or getattr(sys, 'frozen', False))
    original = env.pop('LD_LIBRARY_PATH_ORIG', '')
    if original:
        env['LD_LIBRARY_PATH'] = original
    elif bundled:
        env.pop('LD_LIBRARY_PATH', None)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'LD_PRELOAD'):
        env.pop(key, None)
    if bundled:
        for key in ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_FONTDIR'):
            env.pop(key, None)
        private = [env.get('APPDIR', ''), str(getattr(sys, '_MEIPASS', ''))]
        def host_path(value):
            return os.pathsep.join(p for p in value.split(os.pathsep)
                if p and not any(root and (p == root or p.startswith(root.rstrip('/') + '/')) for root in private)
                and '/.mount_' not in p and '/_MEI' not in p)
        for key in ('PATH', 'LD_LIBRARY_PATH', 'XDG_DATA_DIRS'):
            if key in env:
                value = host_path(env[key])
                if value:
                    env[key] = value
                else:
                    env.pop(key, None)
        env.setdefault('PATH', os.defpath)
        for key in ('SSL_CERT_FILE', 'SSL_CERT_DIR'):
            if key in env and host_path(env[key]) != env[key]:
                env.pop(key, None)
    return env
