# TOP Posters for Kodi

Kodi add-on that puts [TOP Posters](https://top-posters.com) artwork in your library: posters with
rating badges from IMDb, Rotten Tomatoes, Metacritic, Trakt, TMDb and more, kept up to date.

It works with whatever scraper you already use. The add-on writes TOP Posters image URLs into
your library's artwork, and Kodi shows them like any other artwork.

## What you get

| Kodi artwork | TOP Posters image | Plan |
| --- | --- | --- |
| Movie and TV show `poster` | Poster with rating badges | All |
| Season `poster` | Season poster | All |
| Episode `thumb` | Episode still with the episode rating | Premium |
| `landscape` | 16:9 banner with title logo and ratings | Pro, Premium (switch on in Dashboard → Banners) |
| `fanart` | Cinematic background | Premium (switch on in Dashboard → Backgrounds) |
| `clearlogo` | Transparent logo with rating badges | Premium (switch on in Dashboard → Logos) |

Badge style, language and order come from your dashboard at top-posters.com. Each Kodi
installation appears there as its own device, named after its platform, so two boxes
can have different settings. The add-on creates the installation ID on first run and adds it to
every artwork URL. If you copy Kodi's data folder to another box, use **Advanced → Use a new
installation ID** on the copy.

## Install

Requires Kodi 19 (Matrix) or later and a TOP Posters API key.

1. Download `service.topposters-<version>.zip` from the [releases](https://github.com/TOP-Posters/Kodi.Addon.TopPosters/releases).
2. In Kodi: *Settings → Add-ons → Install from zip file* (allow *Unknown sources* if Kodi asks).
3. Open the add-on settings, enter your API key and press **Check API key**.

The artwork is applied a few seconds later, and again after every library scan.

## How it works

- **Your original artwork is kept.** The add-on remembers what your scraper found.
  **Restore original artwork** puts it back and switches the add-on off until you turn it on again.
- **Online originals are passed as fallback URLs.** When the API responds with a fallback redirect,
  Kodi can display the original image instead.
- **Local originals stay available (1.1.0+).** For file paths, SMB shares and other device-local
  artwork, the add-on downloads the TOP Posters replacement before applying it. If the download
  fails, the original stays in place, or the last good downloaded replacement is kept. Original
  paths are never sent to the API. These downloads happen during application and refresh and
  count against the API quota.
- **Ratings stay fresh.** Every *n* days (7 by default), online images are removed from Kodi's
  texture cache and fetched again when shown. Downloaded local replacements are updated in the
  background; changed images get a new filename so Kodi displays the update. **Refresh ratings
  now** also updates local replacements. Set the interval to 0 to disable scheduled refresh.
- **Failures do not trigger repeated downloads.** Connection failures, invalid keys, rate limits
  and server errors temporarily pause further local image requests. A manual refresh can retry
  immediately. Unused generated files older than 30 days are cleaned up after complete library
  passes; files still referenced by the library are retained.
- **Refreshed items stay covered.** When you refresh an item or rescan, the add-on picks up
  the new original and puts the TOP Posters URL back on top.

Titles are matched by TMDB ID first, then IMDb, then TVDB (TV shows only). Items without any of
these IDs, and season 0 (specials), are left alone.

## Development

```bash
python3 -m pytest tests
python3 build.py
```

The tests run the add-on against an in-memory Kodi (`tests/fakekodi.py`) that answers the
JSON-RPC calls the add-on makes, with simulated image downloads for local-artwork fallback,
conditional requests, scheduled refresh and restoration. Installation and artwork rendering
should also be checked on a real Kodi device before publishing a release.
