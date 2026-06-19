# INSTALL.md

Setup instructions for airplay2tv on macOS and Debian/Ubuntu.

## macOS (Homebrew, no virtualenv)

This is the recommended path on the developer's machine. Dependencies land
directly in the Homebrew python@3.12 site-packages tree without a virtualenv.

### Prerequisites

- macOS with [Homebrew](https://brew.sh) installed.

### Steps

```bash
# 1. Install system dependencies
brew install ffmpeg python@3.12

# 2. Clone the repo
git clone https://github.com/vosslab/airplay2tv
cd airplay2tv

# 3. Install Python dependencies into the Homebrew python@3.12 site-packages
/opt/homebrew/bin/python3.12 -m pip install -r pip_requirements.txt

# 4. Run directly from the repo
source source_me.sh && python3 -m airplay2tv --help
```

Python modules are installed to `/opt/homebrew/lib/python3.12/site-packages/`
(the Homebrew default for python@3.12).

### Optional: PATH-installed command via Homebrew formula

A formula is provided at [HomebrewFormula/airplay2tv.rb](../HomebrewFormula/airplay2tv.rb).
Update the `url` and `sha256` fields to point to a real release archive, then:

```bash
brew install --formula HomebrewFormula/airplay2tv.rb
airplay2tv --help
```

## Debian/Ubuntu (no virtualenv)

### Prerequisites

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-pip
```

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/vosslab/airplay2tv
cd airplay2tv

# 2. Install Python dependencies system-wide (or --user)
pip3 install -r pip_requirements.txt

# 3. Run directly from the repo
python3 -m airplay2tv --help
```

For a PATH-installed command on Debian, use `pip3 install .` after the
dependencies are in place, which writes the `airplay2tv` console script into
`~/.local/bin/` (add that to `PATH` if needed).

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
