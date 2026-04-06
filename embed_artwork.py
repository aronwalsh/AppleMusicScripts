#!/usr/bin/env python3
"""
Embed artwork directly into audio files using mutagen.
More reliable than AppleScript for persistent artwork.
"""

import subprocess
import sys
import urllib.request
import urllib.parse
import json
import os
from collections import defaultdict
from pathlib import Path

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, APIC, ID3NoHeaderError
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.flac import FLAC
    from mutagen import File as MutagenFile
except ImportError:
    print("Error: mutagen not installed. Run: pip3 install mutagen")
    sys.exit(1)

sys.stdout.reconfigure(line_buffering=True)

MAX_ARTWORK_SIZE = 20 * 1024 * 1024  # 20MB


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
    """Get tracks without artwork, including file paths."""
    print("Scanning library for missing artwork...")

    script = '''
    tell application "Music"
        set output to ""
        set trackList to tracks of library playlist 1
        repeat with t in trackList
            if (count of artworks of t) is 0 then
                try
                    set loc to POSIX path of (location of t)
                    set output to output & (name of t) & "|||" & (artist of t) & "|||" & (album of t) & "|||" & loc & linefeed
                end try
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
            if len(parts) >= 4:
                tracks.append({
                    'name': parts[0],
                    'artist': parts[1],
                    'album': parts[2],
                    'path': parts[3]
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
            album_lower = album.lower()
            artist_lower = artist.lower()

            for result in data['results']:
                result_album = result.get('collectionName', '').lower()
                result_artist = result.get('artistName', '').lower()

                if is_close_match(album_lower, result_album) and \
                   is_close_match(artist_lower, result_artist):
                    artwork_url = result.get('artworkUrl100', '')
                    if artwork_url:
                        return artwork_url.replace('100x100', '600x600')

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
            if len(data) > 100 and (data[:2] == b'\xff\xd8' or data[:8] == b'\x89PNG\r\n\x1a\n'):
                return data
            return None
    except Exception as e:
        print(f"  Warning: Failed to download artwork: {e}")
        return None


def embed_artwork_in_file(filepath: str, artwork_data: bytes) -> bool:
    """Embed artwork directly into audio file."""
    try:
        ext = Path(filepath).suffix.lower()

        if ext == '.mp3':
            try:
                audio = MP3(filepath, ID3=ID3)
            except ID3NoHeaderError:
                audio = MP3(filepath)
                audio.add_tags()

            # Remove existing artwork
            audio.tags.delall('APIC')

            # Add new artwork
            audio.tags.add(
                APIC(
                    encoding=3,  # UTF-8
                    mime='image/jpeg',
                    type=3,  # Cover (front)
                    desc='Cover',
                    data=artwork_data
                )
            )
            audio.save()
            return True

        elif ext in ['.m4a', '.mp4', '.aac']:
            audio = MP4(filepath)
            # MP4Cover format: JPEG=13, PNG=14
            audio['covr'] = [MP4Cover(artwork_data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
            return True

        elif ext == '.flac':
            audio = FLAC(filepath)
            from mutagen.flac import Picture
            pic = Picture()
            pic.type = 3  # Cover (front)
            pic.mime = 'image/jpeg'
            pic.desc = 'Cover'
            pic.data = artwork_data
            audio.clear_pictures()
            audio.add_picture(pic)
            audio.save()
            return True

        else:
            # Try generic approach
            audio = MutagenFile(filepath)
            if audio is not None:
                # This may not work for all formats
                return False

    except Exception as e:
        print(f"    Error embedding in {filepath}: {e}")
        return False

    return False


def refresh_music_library():
    """Tell Music app to refresh."""
    script = '''
    tell application "Music"
        -- Force refresh by accessing library
        set trackCount to count of tracks of library playlist 1
    end tell
    '''
    subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Embed artwork directly into audio files')
    parser.add_argument('--apply', action='store_true', help='Apply changes (default is dry-run)')
    parser.add_argument('--album', type=str, help='Only process specific album')

    args = parser.parse_args()
    dry_run = not args.apply

    print("=" * 50)
    print("Embed Album Artwork")
    print("=" * 50)
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")

    tracks = get_tracks_without_artwork()

    if not tracks:
        print("\nNo tracks found without artwork!")
        return

    # Filter if requested
    if args.album:
        tracks = [t for t in tracks if args.album.lower() in t['album'].lower()]
        print(f"Filtered to albums matching '{args.album}'")

    # Group by album
    albums = defaultdict(lambda: {'artist': '', 'tracks': []})
    for t in tracks:
        key = (t['album'], t['artist'])
        albums[key]['artist'] = t['artist']
        albums[key]['tracks'].append(t)

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
            found.append((album, artist, artwork_url, data['tracks']))
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
        print(f"\n[DRY RUN] Would embed artwork in {sum(len(t) for _, _, _, t in found)} files:")
        for album, artist, url, tracks in found:
            print(f"  - {artist} - {album} ({len(tracks)} tracks)")
        print(f"\nRun with --apply to embed artwork")
    else:
        print(f"\nDownloading and embedding artwork...")
        total_updated = 0
        total_failed = 0

        for album, artist, url, tracks in found:
            print(f"\n  Processing: {artist} - {album}")
            artwork_data = download_artwork(url)

            if not artwork_data:
                print(f"    Failed to download artwork")
                total_failed += len(tracks)
                continue

            success = 0
            for t in tracks:
                if embed_artwork_in_file(t['path'], artwork_data):
                    success += 1
                else:
                    total_failed += 1

            total_updated += success
            print(f"    Embedded in {success}/{len(tracks)} files")

        # Refresh Music library
        print("\nRefreshing Music library...")
        refresh_music_library()

        print(f"\n{'=' * 50}")
        print(f"Done! Embedded artwork in {total_updated} files")
        if total_failed:
            print(f"Failed: {total_failed} files")

    if not_found:
        print(f"\nCould not find artwork for {len(not_found)} albums:")
        for album, artist, reason in not_found:
            album_display = album if album else "(No Album)"
            print(f"  - {artist} - {album_display}: {reason}")


if __name__ == '__main__':
    main()
