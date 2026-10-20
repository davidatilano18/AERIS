"""Retention policy for routine pre-sync SQLite backups.

Only `*_before_sync_*.db` files are candidates; milestone backups (archive,
controlled or first-scheduler copies) are never removed. Keeps the most recent
copies plus the latest copy of each day inside the retention window.
"""
from datetime import datetime, timedelta
from pathlib import Path

PATTERN = '*_before_sync_*.db'
KEEP_RECENT = 5
KEEP_DAYS = 14


def plan(folder, keep_recent=KEEP_RECENT, keep_days=KEEP_DAYS, now=None, protect=()):
    now = now or datetime.now()
    protected = {Path(p).resolve() for p in protect}
    files = sorted(Path(folder).glob(PATTERN), key=lambda p: p.stat().st_mtime, reverse=True)
    keep, seen_days = set(files[:keep_recent]), set()
    for path in files:
        stamp = datetime.fromtimestamp(path.stat().st_mtime)
        day = stamp.date()
        if (now - stamp <= timedelta(days=keep_days) and day not in seen_days) or path.resolve() in protected:
            keep.add(path)
        seen_days.add(day)
    return [p for p in files if p in keep], [p for p in files if p not in keep]


def prune(folder, apply=False, **options):
    kept, removed = plan(folder, **options)
    size = sum(p.stat().st_size for p in removed)
    if apply:
        for path in removed:
            path.unlink()
    return {'applied': apply, 'kept': [p.name for p in kept],
            'removed': [p.name for p in removed], 'removed_bytes': size}
