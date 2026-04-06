# Apple Music Scripts

Python scripts for automating Apple Music on macOS.

## Requirements

- macOS with Music app, Python 3.8+
- Optional: `pip3 install mutagen` (for artwork embedding)

## Scripts

All destructive scripts default to **dry-run mode** — pass `--apply` to make changes.

### Importing & Cleanup

**import_music.py** — Import music from a folder, skipping duplicates.

```bash
python3 import_music.py /path/to/music              # dry run
python3 import_music.py /path/to/music --import      # import
python3 import_music.py /path/to/music --import --resume
```

**remove_duplicates.py** — Find and remove duplicate tracks (by name + artist + album).

```bash
python3 remove_duplicates.py                          # dry run
python3 remove_duplicates.py --apply
python3 remove_duplicates.py --artist "Xiu Xiu" --album "Hamilton"
```

### Artwork

**find_missing_artwork.py** — List albums with no artwork.

```bash
python3 find_missing_artwork.py
```

**fetch_artwork.py** — Fetch artwork from iTunes API and apply via AppleScript.

```bash
python3 fetch_artwork.py --apply
```

**embed_artwork.py** — Fetch and embed artwork directly into audio files. Requires `mutagen`.

```bash
python3 embed_artwork.py --apply
python3 embed_artwork.py --apply --album "Album Name"
```

**fix_artwork.py** — Embed artwork into files and re-import tracks. Most reliable option. Requires `mutagen`.

```bash
python3 fix_artwork.py --apply
```

### Restoring Loved Songs & Playlists

**restore_direct.py** — Restore from JSON export. Fast (no library pre-fetch).

```bash
python3 restore_direct.py export.json --apply
python3 restore_direct.py export.json --apply --loved-only
python3 restore_direct.py export.json --apply --playlists-only
python3 restore_direct.py export.json --apply --playlist "My Playlist"
```

**restore_from_export.py** — Restore from JSON with library pre-fetch for match validation.

```bash
python3 restore_from_export.py export.json --apply
```

**restore_loved.py** — Restore loved songs from a text file (`Artist - Title`, one per line).

```bash
python3 restore_loved.py songs.txt --apply
```

**restore_library.py** — Restore from an iPhone backup (parses MediaLibrary.sqlitedb).

```bash
python3 restore_library.py --apply
python3 restore_library.py --backup-path /path/to/backup --export-json data.json
```

### JSON Export Format

```json
{
  "loved_songs": [
    {"name": "Title", "artist": "Artist", "album": "Album"}
  ],
  "playlists": [
    {"name": "Playlist", "tracks": [{"name": "Title", "artist": "Artist", "album": "Album"}]}
  ]
}
```

## How It Works

Scripts use AppleScript (`osascript`) to communicate with the Music app.

## License

MIT
