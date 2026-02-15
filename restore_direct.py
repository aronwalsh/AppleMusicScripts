#!/usr/bin/env python3
"""
Directly restore loved songs and playlists without pre-fetching the entire library.
This is faster for large libraries.
"""

import sys
import subprocess
import json
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)


def escape_for_applescript(s: str) -> str:
    """Escape string for AppleScript."""
    if not s:
        return ""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def mark_loved(name: str, artist: str) -> bool:
    """Mark a track as favorited/loved. Returns True if found and marked."""
    name_esc = escape_for_applescript(name)
    artist_esc = escape_for_applescript(artist)

    script = f'''
    tell application "Music"
        try
            set foundTracks to (every track of library playlist 1 whose name is "{name_esc}" and artist is "{artist_esc}")
            if (count of foundTracks) > 0 then
                repeat with t in foundTracks
                    set favorited of t to true
                end repeat
                return count of foundTracks
            end if
            return 0
        on error
            return 0
        end try
    end tell
    '''

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
    try:
        return int(result.stdout.strip()) > 0
    except:
        return False


def create_playlist_and_add_tracks(name: str, tracks: list) -> tuple:
    """Create playlist and add tracks. Returns (added, failed)."""
    name_esc = escape_for_applescript(name)

    # Create playlist
    script = f'tell application "Music" to make new playlist with properties {{name:"{name_esc}"}}'
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    if result.returncode != 0:
        return 0, len(tracks)

    added = 0
    for track in tracks:
        track_esc = escape_for_applescript(track['name'])
        artist_esc = escape_for_applescript(track['artist'])

        script = f'''
        tell application "Music"
            try
                set foundTracks to (every track of library playlist 1 whose name is "{track_esc}" and artist is "{artist_esc}")
                if (count of foundTracks) > 0 then
                    duplicate (item 1 of foundTracks) to playlist "{name_esc}"
                    return 1
                end if
                return 0
            on error
                return 0
            end try
        end tell
        '''

        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        try:
            if int(result.stdout.strip()) > 0:
                added += 1
        except:
            pass

    return added, len(tracks) - added


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Directly restore loved songs and playlists')
    parser.add_argument('export_file', type=Path, help='JSON export file')
    parser.add_argument('--apply', action='store_true', help='Apply changes')
    parser.add_argument('--loved-only', action='store_true', help='Only restore loved songs')
    parser.add_argument('--playlists-only', action='store_true', help='Only restore playlists')
    parser.add_argument('--playlist', type=str, help='Restore only this playlist')

    args = parser.parse_args()
    dry_run = not args.apply

    print("="*50)
    print("Apple Music Direct Restore")
    print("="*50)
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")

    # Load data
    with open(args.export_file) as f:
        data = json.load(f)

    loved_songs = data.get('loved_songs', [])
    playlists = data.get('playlists', [])

    if args.playlist:
        playlists = [p for p in playlists if p['name'] == args.playlist]

    print(f"\nLoaded: {len(loved_songs)} loved songs, {len(playlists)} playlists")

    # Process loved songs
    if loved_songs and not args.playlists_only:
        if dry_run:
            print(f"\n[DRY RUN] Would mark {len(loved_songs)} songs as loved")
            print("Sample:")
            for s in loved_songs[:10]:
                print(f"  ♥ {s['artist']} - {s['name']}")
            if len(loved_songs) > 10:
                print(f"  ... and {len(loved_songs) - 10} more")
        else:
            print(f"\nMarking {len(loved_songs)} songs as loved...")
            success = 0
            not_found = []
            for i, s in enumerate(loved_songs):
                if (i + 1) % 50 == 0:
                    print(f"  Progress: {i+1}/{len(loved_songs)} ({success} found)")
                if mark_loved(s['name'], s['artist']):
                    success += 1
                else:
                    not_found.append(s)
            print(f"  Done: {success} marked, {len(not_found)} not found")

            if not_found and len(not_found) <= 20:
                print("\n  Not found in library:")
                for s in not_found:
                    print(f"    - {s['artist']} - {s['name']}")

    # Process playlists
    if playlists and not args.loved_only:
        if dry_run:
            print(f"\n[DRY RUN] Would create {len(playlists)} playlists:")
            for p in playlists:
                print(f"  - {p['name']}: {len(p['tracks'])} tracks")
        else:
            print(f"\nCreating {len(playlists)} playlists...")
            for p in playlists:
                print(f"\n  Creating '{p['name']}'...")
                added, failed = create_playlist_and_add_tracks(p['name'], p['tracks'])
                print(f"    Added {added}/{len(p['tracks'])} tracks")

    print("\n" + "="*50)
    if dry_run:
        print("Run with --apply to make changes")


if __name__ == '__main__':
    main()
