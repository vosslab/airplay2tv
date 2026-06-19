# Stream media to your TV

Command-line tool that streams local video and audio files to an Apple TV or Roku over your home network, with automatic format detection, optional ffmpeg transcoding, and a simple device-pairing workflow.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md) - setup on macOS (Homebrew) and Debian/Ubuntu
- [docs/USAGE.md](docs/USAGE.md) - full CLI reference and examples
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) - known issues and fixes
- [docs/CODE_ARCHITECTURE.md](docs/CODE_ARCHITECTURE.md) - system design and component overview
- [docs/FILE_STRUCTURE.md](docs/FILE_STRUCTURE.md) - directory layout and file purposes

## Quick start

```bash
# Clone and run (macOS with Homebrew)
brew install ffmpeg python@3.12
pip3 install -r pip_requirements.txt
source source_me.sh && python3 stream.py -i movie.mp4
```

Alternatively, install via the packaged Homebrew formula:

```bash
brew install --formula HomebrewFormula/airplay2tv.rb
```

See [docs/INSTALL.md](docs/INSTALL.md) for full setup steps and [docs/USAGE.md](docs/USAGE.md) for all options.

## License

Source code: MIT. See [LICENSE](LICENSE).
