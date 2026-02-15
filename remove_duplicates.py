#!/usr/bin/env python3
"""
Find and remove duplicate tracks in Apple Music library.
Duplicates are identified by matching name + artist + album.
"""

import subprocess
import sys
from collections import defaultdict

sys.stdout.reconfigure(line_buffering=True)


def get_track_count():
    """Get total track count."""
    script = 'tell application "Music" to return count of tracks of library playlist 1'
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
    return int(result.stdout.strip()) if result.returncode == 0 else 0


def get_tracks_batch(start, batch_size):
    """Get a batch of tracks."""
    script = f'''
    tell application "Music"
        set output to ""
        set trackList to tracks of library playlist 1
        set endIdx to {start} + {batch_size} - 1
        if endIdx > (count of trackList) then set endIdx to count of trackList
        repeat with i from {start} to endIdx
            set t to item i of trackList
            set output to output & (id of t) & "|||" & (name of t) & "|||" & (artist of t) & "|||" & (album of t) & linefeed
        end repeat
        return output
    end tell
    '''
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=120)

    tracks = []
    if result.returncode == 0:
        for line in result.stdout.strip().split('\n'):
            if '|||' in line:
                parts = line.split('|||')
                if len(parts) >= 4:
                    tracks.append({
                        'id': parts[0],
                        'name': parts[1],
                        'artist': parts[2],
                        'album': parts[3]
                    })
    return tracks


def get_all_tracks():
    """Get all tracks with their IDs in batches."""
    print("Fetching library tracks...")

    total = get_track_count()
    print(f"Library has {total} tracks")

    tracks = []
    batch_size = 500

    for start in range(1, total + 1, batch_size):
        batch = get_tracks_batch(start, batch_size)
        tracks.extend(batch)
        print(f"  Progress: {len(tracks)}/{total}")

    print(f"Found {len(tracks)} total tracks")
    return tracks


def find_duplicates(tracks):
    """Find duplicate tracks (same name + artist + album)."""
    # Group by (name, artist, album)
    groups = defaultdict(list)

    for t in tracks:
        key = (t['name'].lower().strip(), t['artist'].lower().strip(), t['album'].lower().strip())
        groups[key].append(t)

    # Find groups with more than one track
    duplicates = {k: v for k, v in groups.items() if len(v) > 1}

    return duplicates


def delete_tracks(track_ids):
    """Delete tracks by ID."""
    deleted = 0

    for i, track_id in enumerate(track_ids):
        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(track_ids)}")

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
        if result.stdout.strip() == "ok":
            deleted += 1

    return deleted


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Find and remove duplicate tracks')
    parser.add_argument('--apply', action='store_true', help='Actually delete duplicates (default is dry-run)')
    parser.add_argument('--album', type=str, help='Only check specific album')
    parser.add_argument('--artist', type=str, help='Only check specific artist')

    args = parser.parse_args()
    dry_run = not args.apply

    print("=" * 50)
    print("Remove Duplicate Tracks")
    print("=" * 50)
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")

    tracks = get_all_tracks()

    if not tracks:
        print("No tracks found.")
        return

    # Filter if requested
    if args.album:
        tracks = [t for t in tracks if args.album.lower() in t['album'].lower()]
        print(f"Filtered to {len(tracks)} tracks in albums matching '{args.album}'")

    if args.artist:
        tracks = [t for t in tracks if args.artist.lower() in t['artist'].lower()]
        print(f"Filtered to {len(tracks)} tracks by artists matching '{args.artist}'")

    duplicates = find_duplicates(tracks)

    if not duplicates:
        print("\nNo duplicates found!")
        return

    # Calculate totals
    total_dupes = sum(len(v) - 1 for v in duplicates.values())

    print(f"\nFound {len(duplicates)} tracks with duplicates ({total_dupes} extra copies)")

    # Group by album for display
    albums_with_dupes = defaultdict(list)
    for (name, artist, album), tracks_list in duplicates.items():
        albums_with_dupes[(artist, album)].append((name, len(tracks_list)))

    print(f"\nAlbums with duplicates ({len(albums_with_dupes)}):\n")

    for (artist, album), track_list in sorted(albums_with_dupes.items()):
        dupe_count = sum(count - 1 for _, count in track_list)
        print(f"  {artist} - {album}: {len(track_list)} tracks x2 ({dupe_count} to remove)")

    if dry_run:
        print(f"\n[DRY RUN] Would remove {total_dupes} duplicate tracks")
        print("Run with --apply to delete duplicates")
    else:
        print(f"\nRemoving {total_dupes} duplicate tracks...")

        # Collect IDs to delete (keep first, delete rest)
        to_delete = []
        for tracks_list in duplicates.values():
            # Sort by ID to keep consistent ordering, delete all but first
            sorted_tracks = sorted(tracks_list, key=lambda x: int(x['id']))
            for t in sorted_tracks[1:]:
                to_delete.append(t['id'])

        deleted = delete_tracks(to_delete)

        print(f"\n{'=' * 50}")
        print(f"Done! Deleted {deleted} duplicate tracks")


if __name__ == '__main__':
    main()
