# ⚡ Torrent Tool

Search **8 public trackers** at once, dedupe by infohash, rank by relevance — then one-key
download through **Real-Debrid**, all inside a fast terminal UI.

![screenshot](docs/screenshot.svg)

## Features

- **8 engines in parallel** — SolidTorrents · ThePirateBay (official API) · 1337x ·
  TorrentsCSV · Nyaa · BitSearch · Torlock · LimeTorrents
- **Smart ranking** — relevance-weighted results, so `ubuntu 24.04` shows Ubuntu ISOs,
  not whatever spam has the most seeds
- **Infohash dedup** — the same torrent found on 3 trackers is one row (`TPB+1337x`)
- **Bait filter** — `[REAL]` / `Full Version` / `Direct Download` SEO traps are dropped automatically (yes, it's personal)
- **Category badges** — 📺 TV · 🎬 movies · 🎮 games · 🎵 music · 📚 books · 💾 software · 🌸 anime
- **Real-Debrid pipeline** — magnet → cloud cache → unrestricted links → download with progress
- **⚡ Instant badge** — results already sitting in RD's cache are flagged before you click; `c` flips to *cached-only*
- **Multi-select queue** — mark with `Space`, press `d`, walk away
- **Search history**, live sort/filter, keybinding help — and a full **CLI** for scripting
- **Encrypted config** — your RD token is stored Fernet-encrypted, keyed to your machine

## Install

```bash
pip install -r requirements.txt
```

Get a Real-Debrid API token at <https://real-debrid.com/apitoken>, then either press
`t` inside the TUI or run `python torrent_tool.py token <token>`.

## Usage

```bash
python torrent_tool.py        # launches the TUI
python torrent_tool.py ui     # same, explicitly
```

### Keys

| Key | Action |
|---|---|
| `/` | focus search (`↑`/`↓` = history) |
| `Enter` | download this torrent |
| `Space` | mark / unmark (multi-download) · `Esc` clears |
| `o` | sort: smart → seeds → size → name |
| `f` | filter by source |
| `c` | toggle ⚡ cached-only (instant on RD) |
| `C` | clear all filters |
| `m` | copy magnet |
| `t` / `r` / `s` | RD token / cloud manager / refresh |
| `?` | help · `q` quit |

Search supports `min:N` — e.g. `frieren 1080p min:20` hides anything under 20 seeders.

### CLI (same engine, scriptable)

```bash
python torrent_tool.py search "ubuntu 24.04" --sort smart --min-seeds 5 -n 10
python torrent_tool.py search "frieren" --cached --sort smart     # only ⚡ instant results
python torrent_tool.py search "frieren" --download 0      # send result #0 to RD
python torrent_tool.py download "magnet:?xt=..."          # direct magnet
python torrent_tool.py status                             # account/traffic info
python torrent_tool.py rd --delete 2                      # manage RD cloud
```

## Demo GIF

`docs/screenshot.svg` and `docs/help.svg` are real captures. To record an animated
demo of the actual app, install [vhs](https://github.com/charmbracelet/vhs) and run:

```bash
vhs demo.tape     # writes docs/demo.gif
```

## Files & privacy

- Settings + token: `~/.torrent_tool/settings.db` (token is encrypted at rest)
- Downloads: `~/Downloads/TorrentTool/`

## Disclaimer

For educational purposes. Downloading copyrighted material may be illegal in your
country — you are responsible for what you do with this tool. It works on my machine,
which is the important part.
