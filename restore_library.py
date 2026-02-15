#!/usr/bin/env python3
"""
Restore loved songs and playlists from an iPhone backup to Apple Music.

This script parses an iPhone backup to extract:
- Loved/favorited songs
- Playlists and their contents

Then matches tracks to your current Apple Music library and:
- Marks matched loved songs as "loved"
- Recreates playlists with matched tracks

Usage:
    python restore_library.py                    # Auto-find latest backup, dry run
    python restore_library.py --apply            # Actually apply changes
    python restore_library.py --backup-path /path/to/backup  # Use specific backup
"""

import os
import sys
import sqlite3
import subprocess
import hashlib
import plistlib
import json
import unicodedata
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

BACKUP_ROOT = Path.home() / "Library" / "Application Support" / "MobileSync" / "Backup"


@dataclass
class Track:
    """Represents a track from the backup."""
    name: str
    artist: str
    album: str
    loved: bool = False


@dataclass
class Playlist:
    """Represents a playlist from the backup."""
    name: str
    tracks: List[Track]


def normalize_string(s: str) -> str:
    """Normalize string for comparison."""
    if not s:
        return ""
    s = unicodedata.normalize('NFC', s)
    s = s.lower().strip()
    return s


def find_latest_backup() -> Optional[Path]:
    """Find the most recent iPhone backup."""
    if not BACKUP_ROOT.exists():
        return None

    backups = []
    for item in BACKUP_ROOT.iterdir():
        if item.is_dir() and len(item.name) == 40:  # UDID length
            # Check modification time
            info_plist = item / "Info.plist"
            if info_plist.exists():
                backups.append((item, info_plist.stat().st_mtime))

    if not backups:
        return None

    # Return most recent
    backups.sort(key=lambda x: x[1], reverse=True)
    return backups[0][0]


def get_backup_info(backup_path: Path) -> dict:
    """Get info about the backup."""
    info_plist = backup_path / "Info.plist"
    if info_plist.exists():
        with open(info_plist, 'rb') as f:
            return plistlib.load(f)
    return {}


def get_file_hash(domain: str, relative_path: str) -> str:
    """Calculate the SHA1 hash used for backup file naming."""
    full_path = f"{domain}-{relative_path}"
    return hashlib.sha1(full_path.encode()).hexdigest()


def find_media_library_db(backup_path: Path) -> Optional[Path]:
    """Find MediaLibrary.sqlitedb in the backup."""
    # The file is stored with a SHA1 hash of its domain-path
    # Domain: MediaDomain
    # Path: Library/Media/MediaLibrary.sqlitedb

    file_hash = get_file_hash("MediaDomain", "Library/Media/MediaLibrary.sqlitedb")

    # Check both old (flat) and new (subdirectory) backup formats
    possible_paths = [
        backup_path / file_hash,
        backup_path / file_hash[:2] / file_hash,
    ]

    for path in possible_paths:
        if path.exists():
            return path

    # Try to find via Manifest.db
    manifest_db = backup_path / "Manifest.db"
    if manifest_db.exists():
        try:
            conn = sqlite3.connect(manifest_db)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT fileID FROM Files
                WHERE relativePath LIKE '%MediaLibrary.sqlitedb'
                AND domain = 'MediaDomain'
            """)
            row = cursor.fetchone()
            conn.close()

            if row:
                file_id = row[0]
                possible_paths = [
                    backup_path / file_id,
                    backup_path / file_id[:2] / file_id,
                ]
                for path in possible_paths:
                    if path.exists():
                        return path
        except Exception as e:
            print(f"Warning: Could not read Manifest.db: {e}")

    return None


def extract_loved_songs(db_path: Path) -> List[Track]:
    """Extract loved/favorited songs from MediaLibrary.sqlitedb."""
    loved_tracks = []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get table info to understand schema
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        # Common table names in iOS Media Library
        # item - main track info
        # item_extra - extended info including loved status

        if 'item' in tables and 'item_extra' in tables:
            # Try to get loved songs
            cursor.execute("""
                SELECT i.title, i.artist, i.album, ie.loved_state
                FROM item i
                LEFT JOIN item_extra ie ON i.item_pid = ie.item_pid
                WHERE ie.loved_state = 1 OR ie.loved_state = 2
            """)

            for row in cursor.fetchall():
                track = Track(
                    name=row[0] or "",
                    artist=row[1] or "",
                    album=row[2] or "",
                    loved=True
                )
                if track.name:
                    loved_tracks.append(track)

        elif 'item' in tables:
            # Try alternative schema - some versions store loved in item table
            cursor.execute("PRAGMA table_info(item)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'loved' in columns or 'is_loved' in columns:
                loved_col = 'loved' if 'loved' in columns else 'is_loved'
                cursor.execute(f"""
                    SELECT title, artist, album
                    FROM item
                    WHERE {loved_col} = 1
                """)

                for row in cursor.fetchall():
                    track = Track(
                        name=row[0] or "",
                        artist=row[1] or "",
                        album=row[2] or "",
                        loved=True
                    )
                    if track.name:
                        loved_tracks.append(track)

        conn.close()

    except Exception as e:
        print(f"Error reading loved songs: {e}")

    return loved_tracks


def extract_playlists(db_path: Path) -> List[Playlist]:
    """Extract playlists from MediaLibrary.sqlitedb."""
    playlists = []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        # Skip system playlists
        system_playlists = {
            'library', 'music', 'podcasts', 'audiobooks', 'movies',
            'tv shows', 'downloaded', 'recently added', 'recently played',
            'top 25 most played', 'genius'
        }

        if 'container' in tables:
            # Get playlist names
            cursor.execute("""
                SELECT container_pid, name
                FROM container
                WHERE container_type = 1
            """)
            playlist_info = cursor.fetchall()

            for playlist_pid, playlist_name in playlist_info:
                if not playlist_name or normalize_string(playlist_name) in system_playlists:
                    continue

                # Get tracks in this playlist
                tracks = []

                # Try different join patterns for playlist items
                try:
                    cursor.execute("""
                        SELECT i.title, i.artist, i.album
                        FROM container_item ci
                        JOIN item i ON ci.item_pid = i.item_pid
                        WHERE ci.container_pid = ?
                        ORDER BY ci.position
                    """, (playlist_pid,))

                    for row in cursor.fetchall():
                        track = Track(
                            name=row[0] or "",
                            artist=row[1] or "",
                            album=row[2] or ""
                        )
                        if track.name:
                            tracks.append(track)
                except:
                    pass

                if tracks:
                    playlists.append(Playlist(name=playlist_name, tracks=tracks))

        conn.close()

    except Exception as e:
        print(f"Error reading playlists: {e}")

    return playlists


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

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error fetching library: {result.stderr}")
        return set()

    library = set()
    for line in result.stdout.strip().split('\n'):
        if '|||' in line:
            parts = line.split('|||')
            if len(parts) >= 3:
                track = normalize_string(parts[0])
                artist = normalize_string(parts[1])
                album = normalize_string(parts[2])
                library.add((track, artist, album))

    print(f"Found {len(library)} tracks in current library")
    return library


def match_tracks(backup_tracks: List[Track], library: Set[Tuple[str, str, str]]) -> Tuple[List[Track], List[Track]]:
    """Match backup tracks to library tracks."""
    matched = []
    unmatched = []

    for track in backup_tracks:
        key = (normalize_string(track.name), normalize_string(track.artist), normalize_string(track.album))
        if key in library:
            matched.append(track)
        else:
            # Try matching without album (some tracks have different album names)
            found = False
            for lib_track in library:
                if lib_track[0] == key[0] and lib_track[1] == key[1]:
                    track.album = ""  # Will match by name+artist only
                    matched.append(track)
                    found = True
                    break
            if not found:
                unmatched.append(track)

    return matched, unmatched


def set_loved_status(tracks: List[Track], dry_run: bool = True) -> int:
    """Mark tracks as loved in Apple Music."""
    if not tracks:
        return 0

    if dry_run:
        print(f"\n[DRY RUN] Would mark {len(tracks)} tracks as loved")
        for track in tracks[:10]:
            print(f"  - {track.artist} - {track.name}")
        if len(tracks) > 10:
            print(f"  ... and {len(tracks) - 10} more")
        return len(tracks)

    print(f"\nMarking {len(tracks)} tracks as loved...")
    success = 0

    for i, track in enumerate(tracks):
        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(tracks)}")

        # Build search criteria
        name_escaped = track.name.replace('"', '\\"').replace('\\', '\\\\')
        artist_escaped = track.artist.replace('"', '\\"').replace('\\', '\\\\')

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
                count = int(result.stdout.strip())
                if count > 0:
                    success += 1
            except:
                pass

    return success


def create_playlist(playlist: Playlist, library: Set[Tuple[str, str, str]], dry_run: bool = True) -> Tuple[int, int]:
    """Create a playlist in Apple Music."""
    # Match tracks first
    matched, unmatched = match_tracks(playlist.tracks, library)

    if dry_run:
        print(f"\n[DRY RUN] Would create playlist '{playlist.name}' with {len(matched)}/{len(playlist.tracks)} tracks")
        return len(matched), len(unmatched)

    if not matched:
        print(f"\nSkipping playlist '{playlist.name}' - no matching tracks")
        return 0, len(playlist.tracks)

    print(f"\nCreating playlist '{playlist.name}' with {len(matched)} tracks...")

    # Create the playlist
    name_escaped = playlist.name.replace('"', '\\"').replace('\\', '\\\\')
    script = f'''
    tell application "Music"
        try
            make new playlist with properties {{name:"{name_escaped}"}}
            return "ok"
        on error errMsg
            return errMsg
        end try
    end tell
    '''

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    if "ok" not in result.stdout:
        print(f"  Error creating playlist: {result.stdout}")
        return 0, len(playlist.tracks)

    # Add tracks to playlist
    added = 0
    for track in matched:
        track_escaped = track.name.replace('"', '\\"').replace('\\', '\\\\')
        artist_escaped = track.artist.replace('"', '\\"').replace('\\', '\\\\')

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
        except:
            pass

    print(f"  Added {added}/{len(matched)} tracks")
    return added, len(unmatched)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Restore loved songs and playlists from iPhone backup to Apple Music'
    )
    parser.add_argument('--backup-path', type=Path,
                        help='Path to specific iPhone backup folder')
    parser.add_argument('--apply', action='store_true',
                        help='Actually apply changes (default is dry-run)')
    parser.add_argument('--loved-only', action='store_true',
                        help='Only restore loved songs, skip playlists')
    parser.add_argument('--playlists-only', action='store_true',
                        help='Only restore playlists, skip loved songs')
    parser.add_argument('--export-json', type=Path,
                        help='Export backup data to JSON file for review')

    args = parser.parse_args()
    dry_run = not args.apply

    print("="*50)
    print("Apple Music Library Restore")
    print("="*50)
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY CHANGES'}")

    # Find backup
    if args.backup_path:
        backup_path = args.backup_path
    else:
        print("\nSearching for iPhone backups...")
        backup_path = find_latest_backup()

    if not backup_path or not backup_path.exists():
        print("Error: No iPhone backup found.")
        print(f"Expected location: {BACKUP_ROOT}")
        print("\nTo create a backup:")
        print("1. Connect iPhone to Mac")
        print("2. Open Finder and click your iPhone")
        print("3. Click 'Back Up Now'")
        sys.exit(1)

    # Get backup info
    info = get_backup_info(backup_path)
    device_name = info.get('Device Name', 'Unknown')
    last_backup = info.get('Last Backup Date', 'Unknown')
    print(f"\nUsing backup: {device_name}")
    print(f"Backup date: {last_backup}")
    print(f"Backup path: {backup_path}")

    # Find MediaLibrary database
    print("\nLocating media library database...")
    db_path = find_media_library_db(backup_path)

    if not db_path:
        print("Error: Could not find MediaLibrary.sqlitedb in backup.")
        print("The backup may be encrypted or incomplete.")
        sys.exit(1)

    print(f"Found: {db_path}")

    # Extract data
    loved_tracks = []
    playlists = []

    if not args.playlists_only:
        print("\nExtracting loved songs...")
        loved_tracks = extract_loved_songs(db_path)
        print(f"Found {len(loved_tracks)} loved songs")

    if not args.loved_only:
        print("\nExtracting playlists...")
        playlists = extract_playlists(db_path)
        print(f"Found {len(playlists)} playlists")
        for pl in playlists:
            print(f"  - {pl.name}: {len(pl.tracks)} tracks")

    # Export to JSON if requested
    if args.export_json:
        data = {
            'loved_songs': [{'name': t.name, 'artist': t.artist, 'album': t.album} for t in loved_tracks],
            'playlists': [{'name': p.name, 'tracks': [{'name': t.name, 'artist': t.artist, 'album': t.album} for t in p.tracks]} for p in playlists]
        }
        with open(args.export_json, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nExported data to {args.export_json}")

    if not loved_tracks and not playlists:
        print("\nNo data to restore.")
        return

    # Get current library
    library = get_current_library()

    if not library:
        print("Error: Could not read current Music library.")
        sys.exit(1)

    # Process loved songs
    if loved_tracks:
        matched_loved, unmatched_loved = match_tracks(loved_tracks, library)
        print(f"\nLoved songs: {len(matched_loved)} matched, {len(unmatched_loved)} not in library")

        if unmatched_loved and len(unmatched_loved) <= 20:
            print("Unmatched loved songs:")
            for track in unmatched_loved:
                print(f"  - {track.artist} - {track.name}")

        if matched_loved:
            set_loved_status(matched_loved, dry_run=dry_run)

    # Process playlists
    total_playlist_tracks = 0
    total_unmatched = 0

    for playlist in playlists:
        added, unmatched = create_playlist(playlist, library, dry_run=dry_run)
        total_playlist_tracks += added
        total_unmatched += unmatched

    # Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    if dry_run:
        print("Mode: DRY RUN (no changes made)")
    else:
        print("Mode: CHANGES APPLIED")

    if loved_tracks:
        print(f"Loved songs: {len(matched_loved)} would be marked" if dry_run else f"Loved songs: marked")

    if playlists:
        print(f"Playlists: {len(playlists)} with {total_playlist_tracks} total tracks")
        if total_unmatched > 0:
            print(f"  ({total_unmatched} tracks not found in library)")

    if dry_run:
        print("\nTo apply changes, run:")
        print("  python3 restore_library.py --apply")


if __name__ == '__main__':
    main()
