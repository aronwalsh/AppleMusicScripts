#!/usr/bin/env python3
"""
Find albums in Apple Music library that have no artwork.
"""

import subprocess
import sys
from collections import defaultdict

sys.stdout.reconfigure(line_buffering=True)


def get_tracks_without_artwork():
    """Get all tracks that have no artwork."""
    print("Scanning library for missing artwork...")

    script = '''
    tell application "Music"
        set output to ""
        set trackList to tracks of library playlist 1
        set totalCount to count of trackList
        repeat with i from 1 to totalCount
            set t to item i of trackList
            if (count of artworks of t) is 0 then
                set output to output & (name of t) & "|||" & (artist of t) & "|||" & (album of t) & linefeed
            end if
        end repeat
        return output
    end tell
    '''

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return []

    tracks = []
    for line in result.stdout.strip().split('\n'):
        if '|||' in line:
            parts = line.split('|||')
            if len(parts) >= 3:
                tracks.append({
                    'name': parts[0],
                    'artist': parts[1],
                    'album': parts[2]
                })

    return tracks


def main():
    print("=" * 50)
    print("Find Albums Missing Artwork")
    print("=" * 50)

    tracks = get_tracks_without_artwork()

    if not tracks:
        print("\nNo tracks found without artwork!")
        return

    # Group by album
    albums = defaultdict(lambda: {'artist': '', 'tracks': []})
    for t in tracks:
        key = (t['album'], t['artist'])
        albums[key]['artist'] = t['artist']
        albums[key]['tracks'].append(t['name'])

    print(f"\nFound {len(tracks)} tracks without artwork across {len(albums)} albums:\n")

    # Sort by number of tracks (descending)
    sorted_albums = sorted(albums.items(), key=lambda x: len(x[1]['tracks']), reverse=True)

    for (album, artist), data in sorted_albums:
        track_count = len(data['tracks'])
        album_display = album if album else "(No Album)"
        artist_display = artist if artist else "(Unknown Artist)"
        print(f"  {artist_display} - {album_display} ({track_count} tracks)")

    print(f"\n{'=' * 50}")
    print(f"Total: {len(albums)} albums, {len(tracks)} tracks without artwork")


if __name__ == '__main__':
    main()
