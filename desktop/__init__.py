"""HelixSR's standalone Linux desktop application."""
from pathlib import Path
import sys

# The shared engine also runs as Decky's flat py_modules layout.
_modules = str(Path(__file__).resolve().parents[1] / 'py_modules')
if _modules not in sys.path:
    sys.path.insert(0, _modules)
