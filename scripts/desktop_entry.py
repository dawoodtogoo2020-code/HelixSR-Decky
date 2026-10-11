"""Frozen executable entry point; the UI stays usable from source as a module."""
from desktop.app import main

if __name__ == '__main__':
    raise SystemExit(main())
