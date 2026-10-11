"""Frozen executable entry point; the UI stays usable from source as a module."""
import sys

if __name__ == '__main__':
    if '--probe' in sys.argv:
        from desktop.probe import main
        raise SystemExit(main(sys.argv[1:]))
    else:
        from desktop.app import main
        raise SystemExit(main())
