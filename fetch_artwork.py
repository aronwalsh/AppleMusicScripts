#!/usr/bin/env python3
"""
Fetch missing album artwork from Apple Music/iTunes and apply to library.
"""

import subprocess
import sys
import urllib.request
import urllib.parse
import json
import tempfile
import os
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

MAX_ARTWORK_SIZE = 20 * 1024 * 1024  # 20MB


def escape_for_applescript(s: str) -> str:
    """Escape string for use in AppleScript double-quoted strings."""
    if not s:
        return ""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def is_close_match(query: str, result: str) -> bool:
    """Check if two strings are a close match, not just substring containment."""
    if query == result:
        return True
    if query in result or result in query:
        longer = max(len(query), len(result))
        shorter = min(len(query), len(result))
        return shorter / longer >= 0.5 if longer > 0 else False
    return False


def get_tracks_without_artwork():
    """Get all tracks that have no artwork."""
    print("Scanning library for missing artwork...")

    script = '''
    tell application "Music"
        set output to ""
        set trackList to tracks of library playlist 1
        repeat with t in trackList
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


def search_itunes_artwork(album: str, artist: str) -> str:
    """Search iTunes for album artwork. Returns URL or None."""
    query = f"{artist} {album}"
    params = urllib.parse.urlencode({
        'term': query,
        'entity': 'album',
        'limit': 5
    })
    url = f"https://itunes.apple.com/search?{params}"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        if data['resultCount'] > 0:
            # Try to find exact match first
            album_lower = album.lower()
            artist_lower = artist.lower()

            for result in data['results']:
                result_album = result.get('collectionName', '').lower()
                result_artist = result.get('artistName', '').lower()

                # Check for close match
                if is_close_match(album_lower, result_album) and \
                   is_close_match(artist_lower, result_artist):
                    # Get high-res artwork (replace 100x100 with 600x600)
                    artwork_url = result.get('artworkUrl100', '')
                    if artwork_url:
                        return artwork_url.replace('100x100', '600x600')

            # Fall back to first result if no exact match
            artwork_url = data['results'][0].get('artworkUrl100', '')
            if artwork_url:
                return artwork_url.replace('100x100', '600x600')

    except Exception as e:
        print(f"  Warning: iTunes API error for '{album}': {e}")

    return None


def download_artwork(url: str) -> bytes:
    """Download artwork from URL."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            if len(data) > MAX_ARTWORK_SIZE:
                print(f"  Warning: Artwork too large ({len(data)} bytes), skipping")
                return None
            # Verify it's actually an image (JPEG starts with FFD8)
            if len(data) > 100 and (data[:2] == b'\xff\xd8' or data[:8] == b'\x89PNG\r\n\x1a\n'):
                return data
            return None
    except Exception as e:
        print(f"  Warning: Failed to download artwork: {e}")
        return None


def apply_artwork_to_album(artist: str, album: str, artwork_data: bytes) -> int:
    """Apply artwork to all tracks in an album. Returns count of updated tracks."""
    # Save artwork to temp file
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
        f.write(artwork_data)
        temp_path = f.name

    try:
        artist_esc = escape_for_applescript(artist)
        album_esc = escape_for_applescript(album)

        # AppleScript - set artworks property directly
        script = f'''
        set artFile to (POSIX file "{temp_path}") as alias
        set artData to read artFile as data

        tell application "Music"
            set matchedTracks to (every track of library playlist 1 whose album is "{album_esc}" and artist is "{artist_esc}")
            set updateCount to 0
            repeat with t in matchedTracks
                if (count of artworks of t) is 0 then
                    try
                        set artworks of t to {{{{data:artData}}}}
                        set updateCount to updateCount + 1
                    end try
                end if
            end repeat
            return updateCount
        end tell
        '''

        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=120)

        if result.returncode == 0:
            try:
                return int(result.stdout.strip())
            except ValueError:
                return 0
        return 0
    finally:
        os.unlink(temp_path)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Fetch and apply missing album artwork')
    parser.add_argument('--apply', action='store_true', help='Apply artwork (default is dry-run)')

    args = parser.parse_args()
    dry_run = not args.apply

    print("=" * 50)
    print("Fetch Missing Album Artwork")
    print("=" * 50)
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")

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

    print(f"\nFound {len(tracks)} tracks without artwork across {len(albums)} albums")
    print("\nSearching Apple Music for artwork...\n")

    found = []
    not_found = []

    for (album, artist), data in albums.items():
        if not album:
            not_found.append((album, artist, "No album name"))
            continue

        artwork_url = search_itunes_artwork(album, artist)

        if artwork_url:
            found.append((album, artist, artwork_url, len(data['tracks'])))
            print(f"  Found: {artist} - {album}")
        else:
            not_found.append((album, artist, "Not found in Apple Music"))
            print(f"  Not found: {artist} - {album}")

    print(f"\n{'=' * 50}")
    print(f"Found artwork for {len(found)}/{len(albums)} albums")

    if not found:
        print("\nNo artwork found to apply.")
        return

    if dry_run:
        print(f"\n[DRY RUN] Would apply artwork to {len(found)} albums:")
        for album, artist, url, track_count in found:
            print(f"  - {artist} - {album} ({track_count} tracks)")
        print(f"\nRun with --apply to download and apply artwork")
    else:
        print(f"\nDownloading and applying artwork...")
        total_updated = 0

        for album, artist, url, track_count in found:
            print(f"\n  Processing: {artist} - {album}")
            artwork_data = download_artwork(url)

            if artwork_data:
                updated = apply_artwork_to_album(artist, album, artwork_data)
                total_updated += updated
                print(f"    Applied to {updated} tracks")
            else:
                print(f"    Failed to download artwork")

        print(f"\n{'=' * 50}")
        print(f"Done! Updated {total_updated} tracks")

    if not_found:
        print(f"\nCould not find artwork for {len(not_found)} albums:")
        for album, artist, reason in not_found:
            album_display = album if album else "(No Album)"
            print(f"  - {artist} - {album_display}: {reason}")


if __name__ == '__main__':
    main()
