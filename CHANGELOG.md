# changelog

all notable changes, roughly in the order i remembered to write them down.

## 0.5.0 — odyssey

- renamed from "torrent tool". one thing, one download — that's not a journey.
  the name finally fits.
- local data moves from `~/.torrent_tool` to `~/.odyssey` on first run, on its
  own. history, blacklist, prefs all come along.
- file is `odyssey.py` now. update any shell scripts / muscle memory.

## 0.4.0 — the ⚡ era

- **⚡ instant badge** — results already in RD's cache get flagged; `c` toggles
  cached-only. CLI gets `--cached`. the feature i actually use the most.
- **hidden local db** — search history is now a real sqlite table (the old json
  blob auto-migrates), plus a downloads log, a "hide this result" blacklist, prefs
  (default sort, download dir), and a 12h ttl cache for the instant checks.
  plaintext tokens get re-encrypted on boot.
- downloads are atomic now (.part → rename). no more half a movie wearing a
  full movie's name.
- error pages (403, etc.) no longer get saved as your download.
- long filenames get trimmed; windows still thinks 260 chars is a lot. it isn't.
- duplicate filenames get a " (2)" instead of silently overwriting the old one.
- CLI no longer dies on the first bad link in a batch.

## 0.3.0 — the TUI era (notes lost to the void)

- multi-select queue, search history, keybinding help screen.
- 8-tracker parallel search with infohash dedup + bait filter.
- full CLI + vhs demo tape, svg captures.

## 0.1.0

- an idea, a pipe dream, one very ugly screen. we've come a long way.
