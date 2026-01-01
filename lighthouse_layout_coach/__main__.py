from __future__ import annotations

# This file is used both by `python -m lighthouse_layout_coach` (as a package)
# and by PyInstaller as an entry script. Use an absolute import so it works
# even when executed as a top-level script.
from lighthouse_layout_coach.launcher import cli_main

if __name__ == "__main__":
    raise SystemExit(cli_main())
