# INSTALL.md

Setup instructions for airplay2tv on macOS and Debian/Ubuntu.

## Requirements

- Python 3.12
- ffmpeg (provides `ffmpeg` and `ffprobe` on PATH)
- pip packages: pyatv, rokuecp, pyyaml, defusedxml (see [pip_requirements.txt](../pip_requirements.txt))

## Clone and run (recommended)

The recommended path for a source checkout. Dependencies land directly in the
system Python 3.12 site-packages without a virtualenv.

### macOS (Homebrew)

```bash
# 1. Install system dependencies
brew install ffmpeg python@3.12

# 2. Clone the repo
git clone https://github.com/vosslab/airplay2tv
cd airplay2tv

# 3. Install Python dependencies into the Homebrew python@3.12 site-packages
/opt/homebrew/bin/python3.12 -m pip install -r pip_requirements.txt
```

Python modules are installed to `/opt/homebrew/lib/python3.12/site-packages/`
(the Homebrew default for python@3.12).

### Debian/Ubuntu

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install ffmpeg python3 python3-pip

# 2. Clone the repo
git clone https://github.com/vosslab/airplay2tv
cd airplay2tv

# 3. Install Python dependencies
pip3 install -r pip_requirements.txt
```

## Homebrew formula (packaged install)

A formula is provided at [HomebrewFormula/airplay2tv.rb](../HomebrewFormula/airplay2tv.rb).
This installs ffmpeg, Python 3.12, all pip dependencies, and the `airplay2tv`
console script into Homebrew's bin directory.

```bash
brew install --formula HomebrewFormula/airplay2tv.rb
airplay2tv --help
```

Note: the formula's `url` and `sha256` fields must point to a real release
archive before this works. The clone-and-run path above works without a release.

## Verify install

```bash
source source_me.sh && python3 stream.py --help
```

Expected: usage text and flag list printed to stdout, exit 0.

## Dependencies

| Dependency | Why |
| --- | --- |
| ffmpeg | media inspection (ffprobe) and transcoding |
| python@3.12 | runtime |
| pyatv | Apple TV AirPlay and MRP control |
| rokuecp | Roku External Control Protocol client |
| pyyaml | YAML config and credentials storage |
| defusedxml | safe XML parsing in doctor (guards XXE) |

See [pip_requirements.txt](../pip_requirements.txt) for the full list.
