# changelog

newest first. if it's not here, it never happened.

## v1.0 Beta — "odyssey"

first public release. it's a beta and it says so out loud, so you can't
complain that it eats a rare edge case. mostly it doesn't.

- renamed from "torrent tool" — because one thing, one download isn't a
  journey. the name finally fits.
- search 8 trackers in parallel: SolidTorrents, TPB, 1337x, TorrentsCSV, Nyaa,
  BitSearch, Torlock, LimeTorrents. duplicates merged by infohash, SEO bait
  filtered, smart ranking on by default.
- ⚡ instant badge — results already cached on Real-Debrid get flagged, `c`
  toggles cached-only. the feature everyone will actually use.
- Real-Debrid pipeline: magnet → cache → unrestricted links → download. your
  ISP sees one https connection and nothing else.
- hidden local db (`~/.odyssey/settings.db`): encrypted token, search history,
  download log, blacklist, prefs. a `x` press sends a spam upload straight to
  the void.
- downloads are atomic (.part → rename), long names get trimmed, duplicates
  get a " (2)", and error pages never pretend to be your movie again.
- full CLI: search, download, status, rd cloud, history, blacklist, prefs.
  scriptable, because why not.

**known beta squabbles:** torlock seed counts are optimistic (they always
were), 1337x/Torlock/Lime need a slow magnet fetch from the details page, and
expired RD links need a re-run. nothing that'll lose your data.
