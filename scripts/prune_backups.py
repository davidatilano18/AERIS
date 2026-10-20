"""Apply the backup retention policy manually. Dry-run unless `--apply` is given.

The scheduled synchronization applies the same policy after each success.
"""
import argparse
import json
from pathlib import Path

from data_ingestion.operations import ROOT
from data_ingestion.retention import KEEP_DAYS, KEEP_RECENT, prune


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=ROOT / 'data' / 'backups')
    parser.add_argument('--keep-recent', type=int, default=KEEP_RECENT)
    parser.add_argument('--keep-days', type=int, default=KEEP_DAYS)
    parser.add_argument('--apply', action='store_true', help='delete instead of only listing')
    args = parser.parse_args(argv)
    if args.keep_recent < 1 or args.keep_days < 1:
        parser.error('--keep-recent and --keep-days must be at least 1')
    result = prune(args.folder, apply=args.apply, keep_recent=args.keep_recent, keep_days=args.keep_days)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
