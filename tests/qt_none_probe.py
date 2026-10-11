"""Isolate binding return ownership with no threads, dialogs or game backend."""
import gc
import json
import sys

import PySide6
import shiboken6
from PySide6.QtWidgets import QApplication, QPushButton


app = QApplication([])
widget = QPushButton()
actions = {
    'setEnabled': lambda: widget.setEnabled(True),
    'setText': lambda: widget.setText('fixture'),
    'isEnabled': widget.isEnabled,
}
for action in actions.values():
    action()
samples = {}
for name, action in actions.items():
    gc.collect()
    before = sys.getrefcount(None)
    for _ in range(100):
        action()
    gc.collect()
    after = sys.getrefcount(None)
    samples[name] = {'before': before, 'after': after, 'delta': after - before}
print(json.dumps({'python': sys.version, 'qt': PySide6.__version__,
                  'shiboken': shiboken6.__version__, 'samples': samples}), flush=True)
if any(sample['delta'] < -5 for sample in samples.values()):
    raise RuntimeError('Qt methods released unowned None references')
