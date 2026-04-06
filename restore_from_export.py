#!/usr/bin/env python3
"""
Restore loved songs and playlists from an exported JSON file.

This works with data exported from iPhone using the Shortcuts app.
See README for instructions on creating the export Shortcut.

Usage:
    python restore_from_export.py export.json           # Dry run
    python restore_from_export.py export.json --apply   # Apply changes
"""

import os
import sys
import subprocess
import json
import unicodedata
from pathlib import Path
from typing import Set, Tuple, List
from dataclasses import dataclass

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)


@dataclass
class Track:
    name: str
    artist: str
    album: str


def escape_for_applescript(s: str) -> str:
    """Escape string for use in AppleScript double-quoted strings."""
    if not s:
        return ""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def normalize_string(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize('NFC', s)
    return s.lower().strip()


def get_current_library() -> Set[Tuple[str, str, str]]:
    """Get all tracks from current Apple Music library."""
    print("Fetching current Music library...")

    script = '''
    tell application "Music"
        set output to ""
        set trackCount to count of tracks of library playlist 1
        repeat with i from 1 to trackCount
            set t to track i of library playlist 1
            set trackName to name of t
            set trackArtist to artist of t
            set trackAlbum to album of t
            set output to output & trackName & "|||" & trackArtist & "|||" & trackAlbum & linefeed
        end repeat
        return output
    end tell
    '''

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        print(f"Error fetching library: {result.stderr}")
        return set()

    library = set()
    for line in result.stdout.strip().split('\n'):
        if '|||' in line:
            parts = line.split('|||')
            if len(parts) >= 3:
                library.add((normalize_string(parts[0]), normalize_string(parts[1]), normalize_string(parts[2])))

    print(f"Found {len(library)} tracks in current library")
    return library


def match_track(track: Track, library: Set[Tuple[str, str, str]]) -> bool:
    """Check if track exists in library."""
    key = (normalize_string(track.name), normalize_string(track.artist), normalize_string(track.album))
    if key in library:
        return True
    # Try without album
    for lib_track in library:
        if lib_track[0] == key[0] and lib_track[1] == key[1]:
            return True
    return False


def set_loved_status(tracks: List[Track], dry_run: bool = True) -> int:
    """Mark tracks as loved in Apple Music."""
    if not tracks:
        return 0

    if dry_run:
        print(f"\n[DRY RUN] Would mark {len(tracks)} tracks as loved:")
        for track in tracks[:15]:
            print(f"  - {track.artist} - {track.name}")
        if len(tracks) > 15:
            print(f"  ... and {len(tracks) - 15} more")
        return len(tracks)

    print(f"\nMarking {len(tracks)} tracks as loved...")
    success = 0

    for i, track in enumerate(tracks):
        if (i + 1) % 25 == 0 or (i + 1) == len(tracks):
            print(f"  Progress: {i + 1}/{len(tracks)}")

        name_escaped = escape_for_applescript(track.name)
        artist_escaped = escape_for_applescript(track.artist)

        script = f'''
        tell application "Music"
            try
                set matchedTracks to (every track of library playlist 1 whose name is "{name_escaped}" and artist is "{artist_escaped}")
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
        if result.returncode == 0:
            try:
                if int(result.stdout.strip()) > 0:
                    success += 1
            except (ValueError, AttributeError):
                pass

    print(f"  Marked {success} tracks as loved")
    return success


def create_playlist(name: str, tracks: List[Track], library: Set[Tuple[str, str, str]], dry_run: bool = True) -> Tuple[int, int]:
    """Create a playlist in Apple Music."""
    matched = [t for t in tracks if match_track(t, library)]
    unmatched = len(tracks) - len(matched)

    if dry_run:
        print(f"\n[DRY RUN] Would create playlist '{name}' with {len(matched)}/{len(tracks)} tracks")
        return len(matched), unmatched

    if not matched:
        print(f"\nSkipping playlist '{name}' - no matching tracks")
        return 0, len(tracks)

    print(f"\nCreating playlist '{name}' with {len(matched)} tracks...")

    name_escaped = escape_for_applescript(name)
    script = f'tell application "Music" to make new playlist with properties {{name:"{name_escaped}"}}'

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Error creating playlist: {result.stderr}")
        return 0, len(tracks)

    added = 0
    for track in matched:
        track_escaped = escape_for_applescript(track.name)
        artist_escaped = escape_for_applescript(track.artist)

        script = f'''
        tell application "Music"
            try
                set matchedTracks to (every track of library playlist 1 whose name is "{track_escaped}" and artist is "{artist_escaped}")
                if (count of matchedTracks) > 0 then
                    duplicate (item 1 of matchedTracks) to playlist "{name_escaped}"
                    return 1
                end if
                return 0
            on error
                return 0
            end try
        end tell
        '''

        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        try:
            if int(result.stdout.strip()) > 0:
                added += 1
        except (ValueError, AttributeError):
            pass

    print(f"  Added {added}/{len(matched)} tracks")
    return added, unmatched


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Restore loved songs and playlists from exported JSON')
    parser.add_argument('export_file', type=Path, help='Path to exported JSON file')
    parser.add_argument('--apply', action='store_true', help='Actually apply changes (default is dry-run)')
    parser.add_argument('--loved-only', action='store_true', help='Only restore loved songs')
    parser.add_argument('--playlists-only', action='store_true', help='Only restore playlists')

    args = parser.parse_args()
    dry_run = not args.apply

    print("="*50)
    print("Apple Music Library Restore")
    print("="*50)
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY CHANGES'}")
    print(f"Export file: {args.export_file}")

    if not args.export_file.exists():
        print(f"Error: File not found: {args.export_file}")
        sys.exit(1)

    # Load export data
    with open(args.export_file, 'r') as f:
        data = json.load(f)

    loved_songs = []
    playlists = []

    # Parse loved songs
    if 'loved_songs' in data and not args.playlists_only:
        for item in data['loved_songs']:
            loved_songs.append(Track(
                name=item.get('name', item.get('title', '')),
                artist=item.get('artist', ''),
                album=item.get('album', '')
            ))
        print(f"\nLoaded {len(loved_songs)} loved songs from export")

    # Parse playlists
    if 'playlists' in data and not args.loved_only:
        for pl in data['playlists']:
            name = pl.get('name', '')
            tracks = []
            for item in pl.get('tracks', []):
                tracks.append(Track(
                    name=item.get('name', item.get('title', '')),
                    artist=item.get('artist', ''),
                    album=item.get('album', '')
                ))
            if name and tracks:
                playlists.append((name, tracks))
        print(f"Loaded {len(playlists)} playlists from export")

    if not loved_songs and not playlists:
        print("\nNo data to restore.")
        return

    # Get current library
    library = get_current_library()
    if not library:
        print("Error: Could not read current Music library.")
        sys.exit(1)

    # Process loved songs
    if loved_songs:
        matched = [t for t in loved_songs if match_track(t, library)]
        unmatched = len(loved_songs) - len(matched)
        print(f"\nLoved songs: {len(matched)} matched, {unmatched} not in library")
        if matched:
            set_loved_status(matched, dry_run=dry_run)

    # Process playlists
    for name, tracks in playlists:
        create_playlist(name, tracks, library, dry_run=dry_run)

    # Summary
    print("\n" + "="*50)
    print("COMPLETE")
    print("="*50)

    if dry_run:
        print("To apply changes, run with --apply flag")


if __name__ == '__main__':
    main()
