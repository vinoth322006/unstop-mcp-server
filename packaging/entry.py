"""Entry point for standalone (PyInstaller) builds."""

import sys

from unstop_mcp.cli import main

if __name__ == "__main__":
    sys.exit(main())
