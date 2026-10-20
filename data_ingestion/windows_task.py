"""Generate a disabled Task Scheduler XML; never register or start tasks."""
import argparse
import csv
import io
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from .operations import ROOT

NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
ET.register_namespace('', NS)


def definition(root, user, now):
    root = Path(root).resolve()
    start = now.replace(minute=5, second=0, microsecond=0)
    if start <= now:
        start += timedelta(hours=1)
    task = ET.Element('{'+NS+'}Task', version='1.2')
    def node(parent, tag, value=None, **attrs):
        child = ET.SubElement(parent, '{'+NS+'}'+tag, attrs)
        if value is not None: child.text = value
        return child
    registration = node(task, 'RegistrationInfo')
    node(registration, 'Description', 'AERIS controlled hourly OpenAQ collection; no predictions')
    triggers = node(task, 'Triggers'); trigger = node(triggers, 'TimeTrigger')
    repetition = node(trigger, 'Repetition'); node(repetition, 'Interval', 'PT1H')
    node(trigger, 'StartBoundary', start.isoformat(timespec='seconds'))
    node(trigger, 'Enabled', 'true')
    principals = node(task, 'Principals'); principal = node(principals, 'Principal', id='Author')
    node(principal, 'UserId', user); node(principal, 'LogonType', 'InteractiveToken')
    node(principal, 'RunLevel', 'LeastPrivilege')
    settings = node(task, 'Settings')
    for name, value in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),
                        ('StopIfGoingOnBatteries','false'),('StartWhenAvailable','true'),
                        ('Enabled','false'),('ExecutionTimeLimit','PT20M')]:
        node(settings, name, value)
    actions = node(task, 'Actions', Context='Author'); action = node(actions, 'Exec')
    node(action, 'Command', str(root/'.venv/Scripts/python.exe'))
    node(action, 'Arguments', '-B -m data_ingestion.scheduled_sync --db "'+str(root/'data/aeris_air_quality.db')+
         '" --key-file "'+str(root/'.secrets/openaq_api_key.clixml')+'"')
    node(action, 'WorkingDirectory', str(root))
    return ET.tostring(task, encoding='utf-16', xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'reports/AERIS-OpenAQ-Hourly.xml')
    args = parser.parse_args()
    # Reject preparing a task under an identity that cannot read the production key.
    from .windows_credentials import load_key
    load_key(ROOT/'.secrets/openaq_api_key.clixml')
    identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], check=True,
                              capture_output=True, text=True)
    user = next(csv.reader(io.StringIO(identity.stdout.strip())))[1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(definition(ROOT, user, datetime.now()))
    print('Disabled task XML prepared; no task registered: '+str(args.output))


if __name__ == '__main__': main()
