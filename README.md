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

# Customize batch size
python3 import_music.py /path/to/music/folder --import --batch-size 100
```

**Options:**
| Option | Description |
|--------|-------------|
| `SOURCE_FOLDER` | Path to folder containing music (required) |
| `--import` | Actually perform the import (default is dry-run) |
| `--resume` | Resume from a previous incomplete import |
| `--batch-size N` | Number of files to add per batch (default: 50) |

## How It Works

The scripts use AppleScript (via `osascript`) to communicate with the Music app. This is the same automation interface that Shortcuts and Automator use, ensuring compatibility and reliability.

## License

MIT
