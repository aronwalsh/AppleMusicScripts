#!/usr/bin/env python3
"""
Restore loved songs from a simple text export.

Accepts multiple input formats:
- "Artist - Title"
- "Title - Artist"
- "Title - Artist - Album"
- Or just song titles (will search by title only)

Usage:
    python restore_loved.py loved_songs.txt           # Dry run
    python restore_loved.py loved_songs.txt --apply   # Apply changes
"""

import sys
import subprocess
import unicodedata
from pathlib import Path
from typing import Set, Tuple, List

sys.stdout.reconfigure(line_buffering=True)


def normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize('NFC', s).lower().strip()


def get_library() -> Set[Tuple[str, str, str]]:
    """Get current library tracks."""
    print("Fetching current Music library...")

    script = '''
    tell application "Music"
        set output to ""
        repeat with t in tracks of library playlist 1
            set output to output & (name of t) & "|||" & (artist of t) & "|||" & (album of t) & linefeed
        end repeat
        return output
    end tell
    '''

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=300)

    library = set()
    for line in result.stdout.strip().split('\n'):
        if '|||' in line:
            parts = line.split('|||')
            if len(parts) >= 3:
                library.add((normalize(parts[0]), normalize(parts[1]), normalize(parts[2])))

    print(f"Found {len(library)} tracks")
    return library


def parse_line(line: str) -> Tuple[str, str, str]:
    """Parse a line into (title, artist, album)."""
    line = line.strip()
    if not line or line.startswith('#'):
        return None

    # Try different separators
    for sep in [' - ', ' – ', ' — ', '\t', ' | ']:
        if sep in line:
            parts = [p.strip() for p in line.split(sep)]
            if len(parts) >= 3:
                # Assume: Title - Artist - Album
                return (parts[0], parts[1], parts[2])
            elif len(parts) == 2:
                # Could be "Artist - Title" or "Title - Artist"
                # We'll try both when matching
                return (parts[0], parts[1], '')

    # No separator - treat as title only
    return (line, '', '')


def find_in_library(title: str, artist: str, album: str, library: Set[Tuple[str, str, str]]) -> List[Tuple[str, str]]:
    """Find matching tracks in library. Returns list of (name, artist) for AppleScript."""
    matches = []
    t_norm = normalize(title)
    a_norm = normalize(artist)

    for lib_title, lib_artist, lib_album in library:
        # Exact title + artist match
        if t_norm == lib_title and a_norm == lib_artist:
            matches.append((title, artist))
            break
        # Try swapped (in case format was "Artist - Title")
        if a_norm == lib_title and t_norm == lib_artist:
            matches.append((artist, title))  # Swap back
            break
        # Title only match
        if not artist and t_norm == lib_title:
            matches.append((title, lib_artist))
            break
        # Partial title match (contains)
        if t_norm in lib_title or lib_title in t_norm:
            if not artist or a_norm == lib_artist or a_norm in lib_artist:
                matches.append((lib_title, lib_artist))

    return matches


def set_loved(name: str, artist: str) -> bool:
    """Mark a track as loved."""
    name_esc = name.replace('\\', '\\\\').replace('"', '\\"')
    artist_esc = artist.replace('\\', '\\\\').replace('"', '\\"')

    script = f'''
    tell application "Music"
        try
            set matchedTracks to (every track of library playlist 1 whose name is "{name_esc}" and artist is "{artist_esc}")
            repeat with t in matchedTracks
                set loved of t to true
            end repeat
            return count of matchedTracks
        on error
            return 0
        end try
    end tell
    '''

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    try:
        return int(result.stdout.strip()) > 0
    except:
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Restore loved songs from text file')
    parser.add_argument('input_file', type=Path, help='Text file with song list')
    parser.add_argument('--apply', action='store_true', help='Actually mark as loved')

    args = parser.parse_args()
    dry_run = not args.apply

    print("="*50)
    print("Restore Loved Songs")
    print("="*50)
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")

    # Read input
    if not args.input_file.exists():
        print(f"Error: File not found: {args.input_file}")
        sys.exit(1)

    lines = args.input_file.read_text().strip().split('\n')
    songs = [parse_line(l) for l in lines]
    songs = [s for s in songs if s]
    print(f"Loaded {len(songs)} songs from file")

    # Get library
    library = get_library()

    # Match songs
    matched = []
    unmatched = []

    for title, artist, album in songs:
        found = find_in_library(title, artist, album, library)
        if found:
            matched.append(found[0])  # Take first match
        else:
            unmatched.append((title, artist))

    print(f"\nMatched: {len(matched)}")
    print(f"Not found: {len(unmatched)}")

    if unmatched and len(unmatched) <= 20:
        print("\nCouldn't find:")
        for t, a in unmatched:
            print(f"  - {a} - {t}" if a else f"  - {t}")
    elif unmatched:
        print(f"\n(First 10 not found:)")
        for t, a in unmatched[:10]:
            print(f"  - {a} - {t}" if a else f"  - {t}")

    if not matched:
        print("\nNo songs to mark as loved.")
        return

    # Apply or preview
    if dry_run:
        print(f"\n[DRY RUN] Would mark {len(matched)} songs as loved:")
        for name, artist in matched[:15]:
            print(f"  ♥ {artist} - {name}")
        if len(matched) > 15:
            print(f"  ... and {len(matched) - 15} more")
        print(f"\nRun with --apply to mark these songs as loved")
    else:
        print(f"\nMarking {len(matched)} songs as loved...")
        success = 0
        for i, (name, artist) in enumerate(matched):
            if (i + 1) % 20 == 0:
                print(f"  Progress: {i+1}/{len(matched)}")
            if set_loved(name, artist):
                success += 1
        print(f"\nDone! Marked {success} songs as loved.")


if __name__ == '__main__':
    main()
