"""Entry point for the frozen engine (PyInstaller needs a plain script, not a package module)."""

from docsuite_engine.__main__ import main

if __name__ == "__main__":
    main()
