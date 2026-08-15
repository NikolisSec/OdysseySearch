<h1 align="center">OdysseySearch</h1>

<p align="center">
  <b>Search 10 trackers. Dedupe the noise. Download through Real-Debrid.</b><br/>
  All from one terminal — no browser tabs, no copy-pasted magnets, no touching the swarm.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-2ea043?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/TUI-Textual-6c5ce7?style=flat-square" alt="TUI app"/>
  <img src="https://img.shields.io/badge/Search-10%20trackers-58A6FF?style=flat-square" alt="10 trackers"/>
  <img src="https://img.shields.io/badge/Real--Debrid-integrated-fa1e1e?style=flat-square" alt="Real-Debrid"/>
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

- **10 engines** — SolidTorrents, TPB (real API), 1337x, TorrentsCSV, Nyaa, BitSearch, BitMusic, Torlock, LimeTorrents, Archive.org — live per-engine counts in the status bar
- **Infohash dedup** — same release on three sites → one row (`TPB + 1337x`), highest-seeded copy wins
- **Smart ranking** — relevance first, so `ubuntu 24.04` gives ISOs, not "unrelated spam • 9999 seeders"
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

## Usage

## Release binaries

Prefer a ready-made binary? Grab the latest **v1.0.3** release:

- **Windows** — `odyssey.exe` (a single-file executable; needs no Python install)
- **Debian/Ubuntu** — `odyssey_1.0.3_all.deb` (install with `sudo dpkg -i odyssey_1.0.3_all.deb`)

Both are built straight from `main` on every tagged release.
