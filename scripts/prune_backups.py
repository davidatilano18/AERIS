"""Apply the retention policy to routine pre-sync SQLite backups.

Only `*_before_sync_*.db` files are candidates; milestone backups (archive,
controlled or first-scheduler copies) are never removed. Keeps the most recent
copies plus the latest copy of each day inside the retention window.
Dry-run by default; `--apply` is required to delete.
"""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from data_ingestion.operations import ROOT

PATTERN = '*_before_sync_*.db'


def plan(folder, keep_recent=5, keep_days=14, now=None):
    now = now or datetime.now()
    files = sorted(Path(folder).glob(PATTERN), key=lambda p: p.stat().st_mtime, reverse=True)
    keep, seen_days = set(files[:keep_recent]), set()
    for path in files:
        stamp = datetime.fromtimestamp(path.stat().st_mtime)
        day = stamp.date()
        if now - stamp <= timedelta(days=keep_days) and day not in seen_days:
            keep.add(path)
        seen_days.add(day)
    return [p for p in files if p in keep], [p for p in files if p not in keep]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=ROOT / 'data' / 'backups')
    parser.add_argument('--keep-recent', type=int, default=5)
    parser.add_argument('--keep-days', type=int, default=14)
    parser.add_argument('--apply', action='store_true', help='delete instead of only listing')
    args = parser.parse_args(argv)
    if args.keep_recent < 1 or args.keep_days < 1:
        parser.error('--keep-recent and --keep-days must be at least 1')
    kept, removed = plan(args.folder, args.keep_recent, args.keep_days)
    size = sum(p.stat().st_size for p in removed)
    if args.apply:
        for path in removed:
            path.unlink()
    print(json.dumps({'applied': args.apply, 'kept': [p.name for p in kept],
                      'removed': [p.name for p in removed], 'removed_bytes': size}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
