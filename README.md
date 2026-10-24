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
| `clearlogo` | Transparent logo with rating badges | Switch on in Dashboard → Logos |

Badge style, language and order come from your dashboard at top-posters.com. Kodi is recognised
as its own device there, so you can give it settings of its own.

## Install

Requires Kodi 19 (Matrix) or later and a TOP Posters API key.

1. Download `service.topposters-<version>.zip` from the [releases](https://github.com/TOP-Posters/Kodi.Addon.TopPosters/releases).
2. In Kodi: *Settings → Add-ons → Install from zip file* (allow *Unknown sources* if Kodi asks).
3. Open the add-on settings, enter your API key and press **Check API key**.

The artwork is applied a few seconds later, and again after every library scan.

## How it works

- **Your original artwork is kept.** The add-on remembers what your scraper found.
  **Restore original artwork** puts it back and switches the add-on off until you turn it on again.
- **Nothing breaks if the API cannot answer.** Every URL carries your original image as a fallback,
  so an unknown title, an expired key or a reached monthly limit shows the original artwork.
- **Ratings stay fresh.** Kodi caches images for good. Every *n* days (7 by default) the add-on drops
  its cached images, and Kodi downloads each one again the next time it is shown. Images nobody
  looks at use no requests.
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
JSON-RPC calls the add-on makes.
