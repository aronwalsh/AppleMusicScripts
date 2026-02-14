#!/usr/bin/env python3
"""
Import music from a folder into Apple Music library, skipping duplicates.

This script scans a source folder (organized as Artist/Album/Track) and imports
all tracks that don't already exist in your Apple Music library. Duplicates are
detected by matching track name + artist + album (case-insensitive).

Requires: macOS with Music app, Python 3.8+

Usage:
    python import_music.py /path/to/music          # Dry run (preview)
    python import_music.py /path/to/music --import # Actually import
    python import_music.py /path/to/music --import --resume  # Resume interrupted import
"""

import os
import subprocess
import sys
import unicodedata
import re
import json
from pathlib import Path
from typing import Set, Tuple, List

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.aac', '.wav', '.flac', '.aiff', '.alac'}
PROGRESS_FILE = ".import_progress.json"  # Stored in current working directory
BATCH_SIZE = 50  # Number of files to add per AppleScript call


def normalize_string(s: str) -> str:
    """Normalize string for comparison: lowercase, Unicode normalized, stripped."""
    if not s:
        return ""
    s = unicodedata.normalize('NFC', s)
    s = s.lower()
    s = s.strip()
    return s


def clean_track_name(filename: str) -> str:
    """Extract clean track name from filename, removing track numbers and extension."""
    name = Path(filename).stem
    name = re.sub(r'^[\d\-]+[\s\.\-]+', '', name)
    return name


def get_current_library() -> Set[Tuple[str, str, str]]:
    """Get all tracks from current Apple Music library as (track, artist, album) tuples."""
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

    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"Error fetching library: {result.stderr}")
        sys.exit(1)

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


def scan_backup_folder(backup_path: str) -> list:
    """Scan backup folder and return list of (filepath, track, artist, album) tuples."""
    print(f"\nScanning backup folder: {backup_path}")

    tracks = []

    for root, dirs, files in os.walk(backup_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        for filename in files:
            if filename.startswith('.'):
                continue

            ext = Path(filename).suffix.lower()
            if ext not in AUDIO_EXTENSIONS:
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, backup_path)
            parts = rel_path.split(os.sep)

            if len(parts) >= 3:
                artist = parts[0]
                album = parts[1]
                track_name = clean_track_name(filename)
            elif len(parts) == 2:
                artist = parts[0]
                album = ""
                track_name = clean_track_name(filename)
            else:
                artist = ""
                album = ""
                track_name = clean_track_name(filename)

            tracks.append((filepath, track_name, artist, album))

    print(f"Found {len(tracks)} audio files in backup")
    return tracks


def find_non_duplicates(backup_tracks: list, library: Set[Tuple[str, str, str]]) -> list:
    """Find tracks in backup that don't exist in current library."""
    non_duplicates = []
    duplicates = 0

    for filepath, track, artist, album in backup_tracks:
        norm_track = normalize_string(track)
        norm_artist = normalize_string(artist)
        norm_album = normalize_string(album)

        key = (norm_track, norm_artist, norm_album)

        if key in library:
            duplicates += 1
        else:
            non_duplicates.append((filepath, track, artist, album))

    print(f"\nDuplicate analysis:")
    print(f"  - Duplicates (will skip): {duplicates}")
    print(f"  - Non-duplicates (will import): {len(non_duplicates)}")

    return non_duplicates


def add_tracks_batch(filepaths: List[str]) -> Tuple[int, int, List[str]]:
    """Add a batch of tracks to Apple Music library. Returns (success_count, fail_count, failed_files)."""
    if not filepaths:
        return 0, 0, []

    # Build AppleScript that adds multiple files
    file_list_parts = []
    for fp in filepaths:
        escaped = fp.replace('\\', '\\\\').replace('"', '\\"')
        file_list_parts.append(f'POSIX file "{escaped}"')

    file_list = ', '.join(file_list_parts)

    script = f'''
    tell application "Music"
        set fileList to {{{file_list}}}
        set successCount to 0
        repeat with f in fileList
            try
                add f to library playlist 1
                set successCount to successCount + 1
            end try
        end repeat
        return successCount
    end tell
    '''

    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True,
        text=True,
        timeout=120
    )

    if result.returncode == 0:
        try:
            success_count = int(result.stdout.strip())
            fail_count = len(filepaths) - success_count
            return success_count, fail_count, []
        except ValueError:
            pass

    # If batch failed, fall back to individual adds to identify failures
    success = 0
    failed = 0
    failed_files = []

    for fp in filepaths:
        escaped = fp.replace('\\', '\\\\').replace('"', '\\"')
        single_script = f'tell application "Music" to add POSIX file "{escaped}" to library playlist 1'
        r = subprocess.run(['osascript', '-e', single_script], capture_output=True, text=True)
        if r.returncode == 0:
            success += 1
        else:
            failed += 1
            failed_files.append(fp)

    return success, failed, failed_files


def save_progress(completed: int, total: int, failed_files: List[str]):
    """Save progress to file for resume capability."""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({
            'completed': completed,
            'total': total,
            'failed_files': failed_files
        }, f)


def load_progress() -> dict:
    """Load progress from file."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return None


def import_tracks(tracks: list, dry_run: bool = True, resume: bool = False, batch_size: int = BATCH_SIZE) -> dict:
    """Import tracks into Apple Music library."""
    stats = {
        'total': len(tracks),
        'success': 0,
        'failed': 0,
        'failed_files': []
    }

    if dry_run:
        print(f"\n[DRY RUN] Would import {len(tracks)} tracks")
        print("\nSample of tracks that would be imported (first 20):")
        for filepath, track, artist, album in tracks[:20]:
            print(f"  - {artist} / {album} / {track}")
        if len(tracks) > 20:
            print(f"  ... and {len(tracks) - 20} more")
        return stats

    # Check for resume
    start_index = 0
    if resume:
        progress = load_progress()
        if progress:
            start_index = progress['completed']
            stats['failed_files'] = progress.get('failed_files', [])
            print(f"\nResuming from track {start_index + 1}...")

    print(f"\nImporting {len(tracks) - start_index} tracks (batch size: {batch_size})...")

    # Process in batches
    total_batches = (len(tracks) - start_index + batch_size - 1) // batch_size
    current_batch = 0

    for i in range(start_index, len(tracks), batch_size):
        current_batch += 1
        batch = tracks[i:i + batch_size]
        filepaths = [fp for fp, _, _, _ in batch]

        success, failed, failed_files = add_tracks_batch(filepaths)
        stats['success'] += success
        stats['failed'] += failed
        stats['failed_files'].extend(failed_files)

        completed = min(i + batch_size, len(tracks))
        pct = 100 * completed // len(tracks)
        print(f"  Batch {current_batch}/{total_batches}: +{success} tracks (Total: {stats['success']}, {pct}% complete)")

        # Save progress after each batch
        save_progress(completed, len(tracks), stats['failed_files'])

    # Clean up progress file on completion
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    return stats


def print_summary(stats: dict, dry_run: bool):
    """Print import summary."""
    print("\n" + "="*50)
    print("IMPORT SUMMARY")
    print("="*50)

    if dry_run:
        print(f"Mode: DRY RUN (no changes made)")
        print(f"Tracks that would be imported: {stats['total']}")
    else:
        print(f"Mode: LIVE IMPORT")
        print(f"Successfully imported: {stats['success']}")
        print(f"Failed: {stats['failed']}")

        if stats['failed_files']:
            print("\nFailed files:")
            for f in stats['failed_files'][:10]:
                print(f"  - {f}")
            if len(stats['failed_files']) > 10:
                print(f"  ... and {len(stats['failed_files']) - 10} more")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Import music from a folder into Apple Music, skipping duplicates.',
        epilog='Example: python import_music.py ~/Music/Backup --import'
    )
    parser.add_argument('source', metavar='SOURCE_FOLDER',
                        help='Path to folder containing music (organized as Artist/Album/Track)')
    parser.add_argument('--import', dest='do_import', action='store_true',
                        help='Actually perform the import (default is dry-run/preview)')
    parser.add_argument('--resume', action='store_true',
                        help='Resume from previous incomplete import')
    parser.add_argument('--batch-size', type=int, default=BATCH_SIZE,
                        help=f'Number of files to add per batch (default: {BATCH_SIZE})')

    args = parser.parse_args()

    # Validate source path
    if not os.path.isdir(args.source):
        print(f"Error: Source folder not found: {args.source}")
        sys.exit(1)

    dry_run = not args.do_import
    source_path = os.path.abspath(args.source)

    print("="*50)
    print("Apple Music Importer")
    print("="*50)
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE IMPORT'}")
    print(f"Source: {source_path}")

    # Step 1: Get current library
    library = get_current_library()

    # Step 2: Scan source folder
    backup_tracks = scan_backup_folder(source_path)

    # Step 3: Find non-duplicates
    to_import = find_non_duplicates(backup_tracks, library)

    if not to_import:
        print("\nNo new tracks to import - backup is fully synchronized!")
        return

    # Step 4: Import (or preview)
    stats = import_tracks(to_import, dry_run=dry_run, resume=args.resume, batch_size=args.batch_size)

    # Step 5: Summary
    print_summary(stats, dry_run)

    if dry_run:
        print("\nTo perform the actual import, run:")
        print(f"  python3 import_music.py \"{source_path}\" --import")


if __name__ == '__main__':
    main()
