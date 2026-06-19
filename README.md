# Stream media to your TV

Command-line tool that streams local video and audio files to an Apple TV or Roku over your home network, with automatic format detection, optional ffmpeg transcoding, and a simple device-pairing workflow.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md) - setup on macOS (Homebrew) and Debian/Ubuntu
- [docs/USAGE.md](docs/USAGE.md) - full CLI reference and examples
- [docs/CODE_ARCHITECTURE.md](docs/CODE_ARCHITECTURE.md) - system design and component overview

## Quick start

```bash
# Install dependencies (macOS with Homebrew)
brew install ffmpeg python@3.12
pip3 install -r pip_requirements.txt

# Stream a file
source source_me.sh && python3 -m airplay2tv -i movie.mp4
```

See [docs/INSTALL.md](docs/INSTALL.md) for full setup steps and [docs/USAGE.md](docs/USAGE.md) for all options.

## License

Source code: GPL-3.0-or-later. See [LICENSE](LICENSE).
