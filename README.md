# Apple Music Scripts

A collection of Python scripts for automating Apple Music tasks on macOS.

## Requirements

- macOS with the Music app
- Python 3.8+
- No external dependencies (uses only standard library)

## Scripts

### import_music.py

Import music from a folder into your Apple Music library, automatically skipping duplicates.

**Features:**
- Scans folders organized as `Artist/Album/Track.ext`
- Detects duplicates by matching track name + artist + album (case-insensitive)
- Batch processing for fast imports (50 files per batch by default)
- Resume capability for interrupted imports
- Dry-run mode to preview before importing
- Supports MP3, M4A, AAC, WAV, FLAC, AIFF, and ALAC formats

**Usage:**

```bash
# Preview what would be imported (dry run)
python3 import_music.py /path/to/music/folder

# Actually import the music
python3 import_music.py /path/to/music/folder --import

# Resume an interrupted import
python3 import_music.py /path/to/music/folder --import --resume
```

### find_missing_artwork.py

Scan your library for albums that have no artwork.

**Usage:**

```bash
python3 find_missing_artwork.py
```

Shows all albums without artwork, grouped by artist/album with track counts.

### fetch_artwork.py

Fetch missing album artwork from Apple Music and apply it to your library.

**Features:**
- Searches iTunes API for matching albums
- Downloads high-resolution artwork (600x600)
- Applies artwork to all tracks in matching albums
- Dry-run mode to preview before applying

**Usage:**

```bash
# Preview what artwork would be fetched (dry run)
python3 fetch_artwork.py

# Actually download and apply artwork
python3 fetch_artwork.py --apply
```

### restore_direct.py

Restore loved songs and playlists from a JSON export file.

**Features:**
- Marks songs as "favorited" in Music app
- Creates playlists and adds matched tracks
- Supports restoring only loved songs or only playlists
- Dry-run mode to preview before applying

**Usage:**

```bash
# Preview what would be restored (dry run)
python3 restore_direct.py export.json

# Actually apply changes
python3 restore_direct.py export.json --apply

# Restore only loved songs
python3 restore_direct.py export.json --apply --loved-only

# Restore only playlists
python3 restore_direct.py export.json --apply --playlists-only

# Restore a specific playlist
python3 restore_direct.py export.json --apply --playlist "My Playlist"
```

**JSON Export Format:**

```json
{
  "loved_songs": [
    {"name": "Song Title", "artist": "Artist Name", "album": "Album Name"}
  ],
  "playlists": [
    {
      "name": "Playlist Name",
      "tracks": [
        {"name": "Song Title", "artist": "Artist Name", "album": "Album Name"}
      ]
    }
  ]
}
```

## Additional Scripts

- `restore_from_export.py` - Alternative restore that pre-fetches library for matching
- `restore_loved.py` - Restore loved songs from a simple text file
- `restore_library.py` - Restore from iPhone backup (requires `pymobiledevice3`)

## How It Works

The scripts use AppleScript (via `osascript`) to communicate with the Music app. This is the same automation interface that Shortcuts and Automator use, ensuring compatibility and reliability.

## License

MIT
