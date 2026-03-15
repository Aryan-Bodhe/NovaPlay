# NovaPlay

NovaPlay is a PyQt6 desktop media app with a built-in browser, downloads panel,
and VLC-backed playback UI.

## TO-DO
1. Add models to generate subtitles for any language.
2. Add models to enhance video resolution.
3. Add models to split vocal/background audio and add sliders to boost either.

## Install (Linux)

For end users installing from this GitHub repository:

```bash
git clone <your-repo-url> NovaPlay
cd NovaPlay
./packaging/linux/install.sh
```

After install, launch NovaPlay from your app menu or run:

```bash
novaplay
```

What the installer does:

- Copies app files to `~/.local/share/novaplay/app`
- Creates a virtual environment at `~/.local/share/novaplay/venv`
- Installs Python dependencies from `requirements.txt`
- Installs launcher script at `~/.local/bin/novaplay`
- Installs desktop entry at `~/.local/share/applications/novaplay.desktop`
- Installs icon at `~/.local/share/icons/hicolor/scalable/apps/novaplay.svg`

## Uninstall (Linux)

```bash
./packaging/linux/uninstall.sh
```

## Developer Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Optional Torrent Support

The torrent panel uses `libtorrent` if available. If libtorrent is not
installed, NovaPlay still runs but torrent downloads are disabled.

Depending on distro and Python version, install via system packages or pip
wheel (`python-libtorrent`) when available.