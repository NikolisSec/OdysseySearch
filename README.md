<h1 align="center">OdysseySearch</h1>

<p align="center">
  <b>Search 10 torrent trackers at once. Dedupe the noise. Download through Real-Debrid.</b><br/>
  All from one terminal screen — no browser tabs, no copy-pasting magnets, no touching the swarm.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-2ea043?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/TUI-Textual-6c5ce7?style=flat-square" alt="TUI app"/>
  <img src="https://img.shields.io/badge/Search-10%20trackers-58A6FF?style=flat-square" alt="10 trackers"/>
  <img src="https://img.shields.io/badge/Real--Debrid-integrated-fa1e1e?style=flat-square" alt="Real-Debrid"/>
</p>

![Interface screenshot](docs/screenshot.svg)

---

## Quick navigation

- [What is this?](#what-is-this)
- [How it works](#how-it-works)
- [Why bother?](#why-bother)
- [Features](#features)
- [Install](#install)
- [Quick start](#quick-start)
- [Using the interface](#using-the-interface)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Search tips](#search-tips)
- [CLI (scripting)](#cli-scripting)
- [Files & privacy](#files--privacy)
- [Known quirks](#known-quirks)
- [Roadmap](#roadmap)
- [Disclaimer](#disclaimer)

---

## What is this?

OdysseySearch is a **command-line torrent search engine and downloader**.

You type a search once, and it:

1. queries **10 public trackers at the same time**,
2. merges the same release found on multiple sites into a single entry,
3. filters out the spam and SEO bait,
4. and hands you a clean, ranked list — then downloads whatever you pick through Real-Debrid.

This started as a *"fine, I'll write my own"* project after opening five tracker
tabs by hand and copy-pasting magnets. It's served ~dozens of downloads since.
Runs fully locally, uses public tracker search APIs, and `pip install` + one token
is all it needs.

> No browser. No torrent client. No VPN. Your internet provider sees a single
> HTTP connection to Real-Debrid — that's the whole point.

## How it works

<table align="center">
<tr><th align="center">1. Search</th><th align="center">2. Pick</th><th align="center">3. Download</th></tr>
<tr><td align="center">Type a query, hit a keyboard shortcut.<br/>10 trackers respond in parallel.</td><td align="center">Results are deduped, ranked by relevance + seeders,<br/>spam filtered, marked if already cached on RD.</td><td align="center">Press <code>Enter</code> — magnet → RD cache →<br/>unrestricted links → progress bar → file.</td></tr>
</table>

The heavy lifting happens on **Real-Debrid's** servers, not yours. Debris are
downloaded from RD's CDN, and your machine never talks to the swarm.

## Why bother?

- **One search, ten trackers.** No tab roulette.
- **Instant results.** If a release is already in RD's cache, it gets a **⚡ instant** badge — playback/download starts in seconds, not hours.
- **Safe.** Your IP never touches the P2P swarm. Downloads come over HTTPS from a debrid CDN.
- **Honest results.** Dedup keeps the same torrent on three sites as one row, and smart sorting puts the *right* result first — not the one with the fake 9999-seeder count.

If that sounds useful, jump to [Quick start](#quick-start).

---

## Features

- **10 engines in parallel** — SolidTorrents, The Pirate Bay (the real API, not a scraper), 1337x, TorrentsCSV, Nyaa, BitSearch, BitMusic (music-only), Torlock, LimeTorrents, and Archive.org (the legal one). The status bar shows live per-engine counts.
- **Infohash dedup** — the same release on three sites shows up once, labeled `TPB + 1337x`, keeping the highest-seeded copy.
- **Smart ranking** — relevance first. `ubuntu 24.04` returns actual ISOs, not "unrelated spam • 9999 seeders" (those counts are lies, by the way).
- **Bait filter** — `[REAL]`, `Full Version`, `Direct Download!!1` and friends are dropped before you see them. Yes, it's personal.
- **Category badges** — 🌐 📦 🎵 🎬 guessed from the filename. Wrong sometimes. That's fine.
- **⚡ Instant badge + cached-only mode** — results already waiting in RD's cache are flagged up front; press `c` to see only those. The feature used the most.
- **Multi-select queue** — mark a handful with `Space`, press `d`, walk away.
- **Real-Debrid pipeline** — magnet → RD cache → unrestricted links → download, with a progress bar. Your ISP sees exactly one HTTPS connection to debrid.
- **Hidden local database** — encrypted RD token, search history, download log, blacklist, and preferences in one SQLite file at `~/.odyssey` (outside the repo, so nothing leaks to GitHub).
- **`x` hides results forever** — the blacklist. Torlock's "verified 6000 seeders" uploads go straight to hell where they belong.

---

## Install

Requires **Python 3.10+**. Clone the repo and install dependencies:

```bash
git clone https://github.com/NikolisSec/OdysseySearch.git
cd OdysseySearch
pip install -r requirements.txt
```

That's it — `requests`, `cryptography`, `textual`, and `beautifulsoup4`.

### One thing you need: a Real-Debrid account

Real-Debrid is a paid service (a few euros a month) and the entire point of this
tool. Grab a free API token at <https://real-debrid.com/apitoken>, then:

```bash
python odyssey.py token <your-token>
```

The token is stored **encrypted** (PBKDF2 + Fernet) in your local database. You can
also paste it inside the interface by pressing `t`.

## Quick start

```bash
python odyssey.py            # launches the interface (TUI)
```

Type a search, press `/`, browse the results, hit `Enter` to download. For the
fastest possible experience:

1. press `t` → paste your RD token,
2. search something like `linux-mint-22`,
3. hit `c` to show only **⚡ instant** results,
4. `Space` a few, then `d`.

![Help screen](docs/help.svg)

---

## Using the interface

| Key | Action |
|---|---|
| `/` | focus the search box (arrow keys browse history) |
| `Enter` | download this torrent |
| `Space` | mark / unmark for the queue (`Esc` clears marks) |
| `d` | start downloading the marked queue |
| `o` | cycle sort: smart → seeds → size → name |
| `f` | filter by source tracker |
| `c` | toggle ⚡ cached-only mode |
| `C` | clear all filters |
| `x` | hide this result (add to blacklist) |
| `m` | copy the magnet link to clipboard |
| `t` | set / replace the RD API token |
| `r` | refresh results |
| `s` | show RD cloud / account status |
| `?` | show the help overlay |
| `q` | quit |

## Search tips

- Plain words work: `Mr. Robot 1080p`
- Add a minimum seed count with **`min:N`** as part of the query:

```text
Mr. Robot 1080p min:20
```

  → only non-spam Mr. Robot results at 1080p with 20+ seeders.

- Combine with source filter (`f`) and cached-only (`c`) to narrow fast.

## CLI (scripting)

The same search-and-download engine is scriptable from the command line —
handy for cron jobs, funnels, and letting a script grab things overnight.

```bash
# Search
python odyssey.py search "ubuntu 24.04" --sort smart --min-seeds 5 -n 10

# Search and only show cached (instant) results
python odyssey.py search "frieren" --cached

# Search and immediately download the top result through RD
python odyssey.py search "frieren" --download 0

# Download a specific magnet directly
python odyssey.py download "magnet:?xt=urn:btih:..."

# Account & traffic status
python odyssey.py status

# Manage the Real-Debrid cloud
python odyssey.py rd --delete 2

# Local database views
python odyssey.py history            # search history (--clear to wipe)
python odyssey.py downloads          # recently downloaded files
python odyssey.py blacklist --wipe   # let the spammers back in. your call.

# Persistent preferences
python odyssey.py prefs --sort smart --dl-dir "D:\videos"

# Launch the interface (same as plain `python odyssey.py`)
python odyssey.py ui
```

---

## Files & privacy

- Everything lives in **`~/.odyssey/settings.db`** — encrypted token, search
  history, download log, blacklist, cache, and preferences. It sits *outside*
  the repo on purpose, so your token never ends up on GitHub.
- Downloads default to **`~/Downloads/Odyssey/`** (change with `prefs --dl-dir`).
- Your IP talks to the trackers when searching, and to Real-Debrid for everything
  heavy. The actual file data comes from RD's CDN — **not** from the swarm.

## Known quirks

- **1337x, Torlock and LimeTorrents don't put magnets in search results.**
  OdysseySearch fetches them from each torrent's details page, which makes those
  three engines ~half a second slower. Nothing to be done about it.
- **Torlock seed counts are optimistic.** Part of why smart ranking exists.
- **RD links expire.** If a download dies mid-flight with a 403, run it again.
  The tool now refuses to save the 403 error page as your movie (that used to be a bug).
- **Archive.org reports 0 seeders.** It's a library, not a swarm. Those results
  surface under smart sort by relevance, and get filtered out if you use `min:N`.

### How this compares to the usual options

- **Stremio + Torrentio + RD** — great for *watching*, but it's a TV-style app
  that doesn't really search; you browse whatever the addon serves.
- **jDownloader / Plowshare** — they don't search at all; you feed them links.
- **qBittorrent + VPN** — you'd be seeding to strangers and your IP joins the
  swarm. OdysseySearch approaches none of that.

OdysseySearch = **search + debrid in one terminal screen.**

---

## Roadmap

- [x] ⚡ Instant badge + cached-only mode
- [x] Hidden local DB (history, blacklist, prefs, download log)
- [ ] `v` — stream straight into VLC instead of downloading
- [ ] Saved searches that auto-grab new releases into RD
- [ ] AllDebrid / other providers
- [ ] Actually render the demo GIF for this README

---

## Disclaimer

Built for educational purposes — and because searching ten trackers by hand is
silly. What you download is on you. It works on my machine, which is the
important part. 👍 If it works on yours, drop a star and say hi.

<p align="center">
  <sub>OdysseySearch — search, dedupe, debrid. Not affiliated with Real-Debrid or any tracker.</sub>
</p>