#!/usr/bin/env python3
"""Repo-root launcher for airplay2tv.

Thin shim: prepends the repo root to sys.path when absent, then delegates
to airplay2tv.cli.main(). No argparse or dispatch logic lives here.
"""

# Standard Library
import os
import sys

# Repo root is the directory containing this file (the parent of airplay2tv/).
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# local repo modules
import airplay2tv.cli


#============================================
if __name__ == "__main__":
	airplay2tv.cli.main()
