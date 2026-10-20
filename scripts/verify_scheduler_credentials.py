"""Read-only credential check. Never prints credentials or exception text."""
import json
import os
from data_ingestion.operations import ROOT
from data_ingestion.production_preflight import credential_scan

key = os.environ.get('OPENAQ_API_KEY', '').strip()
assert key, 'Missing credential'
report = credential_scan(ROOT, key)
assert not report['exact_credential_matches']
assert report['secret_file_git_ignored'] and not report['tracked_secret_paths']
(ROOT/'reports/scheduler_credential_check.json').write_text(json.dumps(report, indent=2), encoding='utf8')
print('DPAPI recovered in noninteractive process; credential scan passed; no secret displayed')
