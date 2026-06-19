#!/usr/bin/env python3
"""Package entry point so `python3 airplay2tv` runs the CLI.

Python executes this module when the package directory is run as a script
(`python3 airplay2tv ...`). It is the thin shebang entry the plan calls the
"root entry script": it imports the CLI and calls main(). The package directory
already owns the name `airplay2tv`, so a same-named root file cannot exist;
this `__main__.py` is the runnable entry instead.

When run as `python3 airplay2tv`, Python puts this package directory on
sys.path rather than the repo root, so the absolute import `airplay2tv.cli`
cannot resolve yet. Prepend the repo root (this file's grandparent) so the
package is importable. Running `python3 -m airplay2tv` from the repo root puts
the root on the path already, making this prepend a harmless no-op.
"""

# Standard Library
import os
import sys

# Repo root is the parent of this package directory.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# local repo modules
import airplay2tv.cli


#============================================
if __name__ == "__main__":
	airplay2tv.cli.main()
