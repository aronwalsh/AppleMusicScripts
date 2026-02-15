#!/usr/bin/env python3
"""
Fix missing artwork by embedding in files and re-importing to Music.
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
except ImportError:
    print("Error: mutagen not installed. Run: pip3 install mutagen")
    sys.exit(1)

sys.stdout.reconfigure(line_buffering=True)


def get_tracks_without_artwork():
    """Get tracks without artwork with their file paths."""
    print("Scanning library for missing artwork...")

    script = '''
    tell application "Music"
        set output to ""
        repeat with t in tracks of library playlist 1
            if (count of artworks of t) is 0 then
                try
                    set loc to location of t
                    set output to output & (id of t) & "|||" & (name of t) & "|||" & (artist of t) & "|||" & (album of t) & "|||" & (POSIX path of loc) & linefeed
                end try
            end if
        end repeat
        return output
    end tell
    '''

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=600)

    tracks = []
    for line in result.stdout.strip().split('\n'):
        if '|||' in line:
            parts = line.split('|||')
            if len(parts) >= 5:
                tracks.append({
                    'id': parts[0],
                    'name': parts[1],
                    'artist': parts[2],
                    'album': parts[3],
                    'path': parts[4]
                })

    print(f"Found {len(tracks)} tracks without artwork")
    return tracks


def search_itunes_artwork(album: str, artist: str) -> str:
    """Search iTunes for album artwork."""
    query = f"{artist} {album}"
    params = urllib.parse.urlencode({'term': query, 'entity': 'album', 'limit': 5})
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

                if (album_lower in result_album or result_album in album_lower) and \
                   (artist_lower in result_artist or result_artist in artist_lower):
                    artwork_url = result.get('artworkUrl100', '')
                    if artwork_url:
                        return artwork_url.replace('100x100', '600x600')

            artwork_url = data['results'][0].get('artworkUrl100', '')
            if artwork_url:
                return artwork_url.replace('100x100', '600x600')
    except:
        pass
    return None


def download_artwork(url: str) -> bytes:
    """Download artwork from URL."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            if len(data) > 100 and (data[:2] == b'\xff\xd8' or data[:8] == b'\x89PNG\r\n\x1a\n'):
                return data
    except:
        pass
    return None


def embed_artwork(filepath: str, artwork_data: bytes) -> bool:
    """Embed artwork in audio file."""
    try:
        ext = Path(filepath).suffix.lower()

        if ext == '.mp3':
            try:
                audio = MP3(filepath, ID3=ID3)
            except ID3NoHeaderError:
                audio = MP3(filepath)
                audio.add_tags()
            audio.tags.delall('APIC')
            audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=artwork_data))
            audio.save()
            return True

        elif ext in ['.m4a', '.mp4', '.aac']:
            audio = MP4(filepath)
            audio['covr'] = [MP4Cover(artwork_data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
            return True

        elif ext == '.flac':
            from mutagen.flac import Picture
            audio = FLAC(filepath)
            pic = Picture()
            pic.type = 3
            pic.mime = 'image/jpeg'
            pic.desc = 'Cover'
            pic.data = artwork_data
            audio.clear_pictures()
            audio.add_picture(pic)
            audio.save()
            return True
    except Exception as e:
        pass
    return False


def remove_track(track_id: str) -> bool:
    """Remove track from Music library."""
    script = f'''
    tell application "Music"
        try
            delete (first track of library playlist 1 whose id is {track_id})
            return "ok"
        on error
            return "error"
        end try
    end tell
    '''
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
    return result.stdout.strip() == "ok"


def add_track(filepath: str) -> bool:
    """Add track to Music library."""
    escaped = filepath.replace('\\', '\\\\').replace('"', '\\"')
    script = f'tell application "Music" to add POSIX file "{escaped}" to library playlist 1'
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
    return result.returncode == 0


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Fix missing artwork by embedding and re-importing')
    parser.add_argument('--apply', action='store_true', help='Apply changes (default is dry-run)')

    args = parser.parse_args()
    dry_run = not args.apply

    print("=" * 50)
    print("Fix Missing Artwork")
    print("=" * 50)
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")

    tracks = get_tracks_without_artwork()
    if not tracks:
        print("\nNo tracks found without artwork!")
        return

    # Group by album
    albums = defaultdict(list)
    for t in tracks:
        albums[(t['album'], t['artist'])].append(t)

    print(f"Grouped into {len(albums)} albums")
    print("\nSearching Apple Music for artwork...\n")

    # Find artwork for each album
    to_fix = []
    not_found = []

    for (album, artist), album_tracks in albums.items():
        if not album:
            not_found.append((album, artist, album_tracks))
            continue

        artwork_url = search_itunes_artwork(album, artist)
        if artwork_url:
            to_fix.append((album, artist, artwork_url, album_tracks))
            print(f"  Found: {artist} - {album} ({len(album_tracks)} tracks)")
        else:
            not_found.append((album, artist, album_tracks))
            print(f"  Not found: {artist} - {album}")

    total_tracks = sum(len(t) for _, _, _, t in to_fix)
    print(f"\n{'=' * 50}")
    print(f"Can fix {total_tracks} tracks across {len(to_fix)} albums")

    if not to_fix:
        print("\nNo artwork available to fix.")
        return

    if dry_run:
        print(f"\n[DRY RUN] Would fix {total_tracks} tracks")
        print("Run with --apply to embed artwork and re-import")
        return

    print(f"\nProcessing {total_tracks} tracks...")
    total_fixed = 0
    total_failed = 0

    for album, artist, artwork_url, album_tracks in to_fix:
        print(f"\n  {artist} - {album}")

        # Download artwork
        artwork_data = download_artwork(artwork_url)
        if not artwork_data:
            print(f"    Failed to download artwork")
            total_failed += len(album_tracks)
            continue

        fixed = 0
        for t in album_tracks:
            # 1. Embed artwork in file
            if not embed_artwork(t['path'], artwork_data):
                total_failed += 1
                continue

            # 2. Remove from library
            if not remove_track(t['id']):
                total_failed += 1
                continue

            # 3. Re-add to library
            if add_track(t['path']):
                fixed += 1
            else:
                total_failed += 1

        total_fixed += fixed
        print(f"    Fixed {fixed}/{len(album_tracks)} tracks")

    print(f"\n{'=' * 50}")
    print(f"Done! Fixed {total_fixed} tracks")
    if total_failed:
        print(f"Failed: {total_failed} tracks")

    if not_found:
        print(f"\nNo artwork available for {len(not_found)} albums:")
        for album, artist, _ in not_found[:10]:
            print(f"  - {artist} - {album if album else '(No Album)'}")
        if len(not_found) > 10:
            print(f"  ... and {len(not_found) - 10} more")


if __name__ == '__main__':
    main()
