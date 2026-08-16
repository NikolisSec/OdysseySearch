<h1 align="center">OdysseySearch</h1>

<p align="center">
  <b>Search 11 trackers. Dedupe the noise. Download through Real-Debrid.</b><br/>
  All from one terminal — no browser tabs, no copy-pasted magnets, no touching the swarm.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-2ea043?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/TUI-Textual-6c5ce7?style=flat-square" alt="TUI app"/>
  <img src="https://img.shields.io/badge/Search-11%20trackers-58A6FF?style=flat-square" alt="11 trackers"/>
<img src="https://img.shields.io/badge/Real--Debrid-integrated-fa1e1e?style=flat-square" alt="Real-Debrid"/>
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/NikolisSec/OdysseySearch?style=flat-square&logo=github&label=Stars" alt="GitHub stars"/>
  <img src="https://img.shields.io/github/v/release/NikolisSec/OdysseySearch?style=flat-square&label=Latest%20Release" alt="Latest release"/>
  <img src="https://img.shields.io/github/downloads/NikolisSec/OdysseySearch/total?style=flat-square&label=Downloads" alt="Total downloads"/>
</p>

![Interface screenshot](docs/screenshot.svg)

---

**Jump to:** [Features](#features) · [Install](#install) · [Usage](#usage) · [Roadmap](#roadmap) · [Wiki](https://github.com/NikolisSec/OdysseySearch/wiki) · [Disclaimer](#disclaimer)

---

## What it does

A command-line torrent search engine + downloader:

- queries **10 public trackers** in parallel,
- merges duplicate releases into one row,
- filters spam, ranks by relevance + seeders,
- marks what's already **⚡ instant** on Real-Debrid,
- and downloads what you pick straight through RD.

## Features

- **11 engines** — SolidTorrents, TPB (real API), 1337x, TorrentsCSV, Nyaa, BitSearch, BitMusic, Torlock, LimeTorrents, FitGirl Repacks, Archive.org — live per-engine counts in the status bar
- **Infohash dedup** — same release on three sites → one row (`TPB + 1337x`), highest-seeded copy wins
- **Smart ranking** — relevance first, so `ubuntu 24.04` gives ISOs, not "unrelated spam • 9999 seeders"
- **Structured query parser** — `s02e05`, `season 2`, `1080p`, `h265`, `dv atmos`, `lang:el`, `min:20`, `size:2gb`, recorded for smart ranking
- **Release forensics** — each result's episode/series/quality/codec/HDR/audio tagged automatically; raw queries filter on what the trackers themselves understand
- **Live search** — the TUI streams results while you type (0.7 s debounce, `/`/`Enter` to lock in)
- **Quick filters** — `Shift+F` modal cycles quality/codec/HDR/language/min-size without re-searching
- **IMDb/TMDB id search** — `tt1234567` / `tmdb:12345` resolve to real titles automatically
- **Gaming built in** — 🎮-flagged game releases (FitGirl/DODI/repacks + GOG, `t:game`/`pc` type filters); Archive.org covers legal abandonware, software, and games
- **Bait filter** — `[REAL]`, `Full Version`, `Direct Download!!1` and friends, dropped on sight
- **⚡ Instant badge + cached-only mode** — results already in RD's cache flagged up front; `c` shows only those
- **Multi-select queue** — mark a few with `Space`, press `d`, walk away
- **Real-Debrid pipeline** — magnet → RD cache → unrestricted links → download with progress bar; your ISP sees exactly one HTTPS connection
- **Hidden local DB** — encrypted token, history, download log, blacklist, prefs in `~/.odyssey` (kept out of the repo on purpose)
- **`x` hides results forever** — the blacklist

## Install

```bash
git clone https://github.com/NikolisSec/OdysseySearch.git
cd OdysseySearch
pip install -r requirements.txt
```

Requires **Python 3.10+** (`requests`, `cryptography`, `textual`, `beautifulsoup4`).

You'll also need a **Real-Debrid** account — it's the whole point. Get an API
token at <https://real-debrid.com/apitoken> and run:

```bash
python odyssey.py token <your-token>     # or press t inside the app
```


## Release binaries

Prefer a ready-made binary? Grab the latest release from the [Releases](https://github.com/NikolisSec/OdysseySearch/releases) page:

- **Windows** - `odyssey.exe` (a single-file executable; no Python install needed)
- **Debian/Ubuntu** - `odyssey_1.0.4_all.deb` (install with `sudo dpkg -i odyssey_1.0.4_all.deb`)

Both are built straight from `main` on every tagged release.

## Usage

```bash
python odyssey.py       # launch the interface
```

### Keyboard shortcuts

| Key | Action |
|---|---|
| `/` | focus the search box (↑/↓ browse history) |
| `Enter` | download this torrent |
| `Space` | mark / unmark for the queue |
| `Esc` | clear all marks |
| `d` | start downloading the marked queue |
| `o` | cycle sort: smart → seeds → size → name |
| `f` | filter by source tracker |
| `Shift+F` | quick filter modal (quality / codec / HDR / language / min size) |
| `c` | toggle ⚡ cached-only mode |
| `C` | clear all filters (incl. quick filters) |
| `x` | hide this result forever (blacklist) |
| `m` | copy the magnet link to clipboard |
| `t` | set / replace the RD API token |
| `r` | refresh results |
| `s` | show RD cloud / account status |
| `?` | show the help overlay |
| `q` | quit |

Search with intent — the parser understands season/episode, releases, and filters,
and the results stream in live as you type:

```text
breaking bad s02 1080p          # season-only tokens, quality
archer s05e01 t:tv              # exact episode, type filter
dune 2021 dv atmos              # Dolby Vision + Atmos specifically
avatar 2009 tt0499549 1080p     # bare IMDb id, full metadata resolved automatically
tmdb:1396 s01e01                # bare TMDB id (resolves via TMDb) + season/episode
some movie 2160p h265 no-hdr    # no HDR copies
show lang:el audio:dts min:10   # Greek subs matter, DTS audio, 10+ seeders
big release size:20gb max:40gb  # size windows
```

Quick filters (`Shift+F`) narrow the current result set instantly the same way —
no re-search needed.

### Scriptable (CLI)

```bash
python odyssey.py search "ubuntu 24.04" --sort smart --min-seeds 5 -n 10
python odyssey.py search "frieren" --cached                    # instant only
python odyssey.py search "frieren" --download 0                # grab top hit
python odyssey.py download "magnet:?xt=urn:btih:..."           # direct magnet
python odyssey.py status                                       # account/traffic
python odyssey.py rd --delete 2                                # RD cloud mgmt
python odyssey.py history                                      # search history
python odyssey.py downloads                                    # grabbed files
python odyssey.py blacklist --wipe                             # let spammers back in?
python odyssey.py prefs --sort smart --dl-dir "D:\videos"      # defaults
```

Full key map, CLI flags, and privacy details live in the **[Wiki](https://github.com/NikolisSec/OdysseySearch/wiki)**.

## Roadmap

- [x] ⚡ Instant badge + cached-only mode
- [x] Hidden local DB
- [x] Structured search queries + release forensics (v1.0.4)
- [x] Live search + quick filters (v1.0.4)
- [x] IMDb / TMDB id search (v1.0.4)
- [ ] `v` — stream straight into VLC
- [ ] Saved searches that auto-grab into RD
- [ ] AllDebrid / other providers
- [ ] Download Manager

## Disclaimer

Built for educational purposes — and because searching ten trackers by hand is
silly. What you download is on you. It works on my machine, which is the
important part. 👍 If it works on yours, drop a star and say hi.

<p align="center">
  <sub>OdysseySearch — search, dedupe, debrid. Not affiliated with Real-Debrid or any tracker.</sub>
</p>
## License
