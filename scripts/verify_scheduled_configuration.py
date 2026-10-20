"""Verify the installed task and production SQLite, strictly read-only except reports."""
import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from data_ingestion import operations as ops
from data_ingestion.production_preflight import sha, snapshot
from data_ingestion.task_semantics import capture, compare_snapshot, compare_semantic


def main():
    root=ops.ROOT; db=root/'data/aeris_air_quality.db'
    output=root/'reports/supervisor_semantic_fix.json'
    report={'status':'checking','task_mutations':0,'network_requests':0}
    try:
        previous=json.loads((root/'reports/first_scheduler_run_20261018T032923Z_9bcea90a.json').read_text())
        approved=json.loads((root/'reports/task_semantic_com_evidence.json').read_text(encoding='utf-8-sig'))
        installation=json.loads((root/'reports/disabled_task_installation.json').read_text())
        report['source_sha256']={name:sha(root/name) for name in (
            'data_ingestion/task_semantics.py','scripts/supervise_first_scheduled_run.py',
            'scripts/install_disabled_task.py','scripts/verify_scheduled_configuration.py','tests/test_task_semantics.py')}
        original_sha=sha(db)
        report['effective_snapshot']=capture(root/'reports/AERIS-OpenAQ-Hourly.xml')
        current=report['effective_snapshot']
        report['comparison']=compare_snapshot(current,expected_enabled=False,reference=approved)
        report['comparison_against_approved_audit']=compare_semantic(
            approved['registered_effective'],current['registered_effective'],expected_enabled=False)
        report['database']=snapshot(db)
        report['database_sha256_before']=original_sha
        report['database_sha256_after']=sha(db)
        report['checks']={
            'functional_parameters_match':report['comparison']['matches'],
            'historically_approved_parameters_match':report['comparison_against_approved_audit']['matches'],
            'xml_unchanged':sha(root/'reports/AERIS-OpenAQ-Hourly.xml')==installation['planned_xml_sha256'],
            'user_matches':current['current_user_sid']==current['registered_effective']['principal']['sid']==approved['current_user_sid'],
            'time_zone_unchanged':current['time_zone']['id']==approved['time_zone']['id'] and current['time_zone']['current_offset']==approved['time_zone']['current_offset'],
            'policy_unchanged':current['execution_policy']==approved['execution_policy']=='Restricted',
            'last_run_unchanged':current['runtime']['last_run_time']==previous['task_after_run']['last_run_time'] and current['runtime']['last_task_result']==0,
            'count_12479':report['database']['tables']['mediciones']['rows']==12479,
            'quality_count_12479':report['database']['tables']['calidad_mediciones']['rows']==12479,
            'integrity':report['database']['integrity_check']==['ok'] and not report['database']['foreign_key_violations'],
            'all_tables_unchanged':report['database']==previous['after'],
            'hash_unchanged':original_sha==sha(db)==previous['final_read_only_state']['database_sha256'],
            'protected_files_unchanged':all(sha(root/name)==digest for name,digest in previous['protected_files_after'].items())}
        stream=io.StringIO()
        with redirect_stdout(stream),redirect_stderr(stream):
            tests=unittest.TextTestRunner(stream=stream).run(unittest.defaultTestLoader.discover(str(root/'tests')))
        report['tests']={'run':tests.testsRun,'failures':len(tests.failures),'errors':len(tests.errors),'successful':tests.wasSuccessful()}
        report['checks']['suite_successful']=tests.wasSuccessful()
        report['checks']['hash_unchanged_after_tests']=sha(db)==original_sha
        # A second read proves tests did not start or mutate the installed task.
        report['after_tests_snapshot']=capture(root/'reports/AERIS-OpenAQ-Hourly.xml')
        later=report['after_tests_snapshot']
        report['checks']['task_still_disabled_unchanged']=compare_snapshot(later,expected_enabled=False,reference=current)['matches'] and later['registered_effective']==current['registered_effective'] and later['runtime']['last_run_time']==current['runtime']['last_run_time']
        report['status']='APTO' if all(report['checks'].values()) else 'NO APTO'
        return 0 if report['status']=='APTO' else 1
    except Exception as exc:
        report['status']='NO APTO';report['error_type']=type(exc).__name__
        return 1
    finally:
        report['finished_at_utc']=ops.iso(ops.utcnow())
        output.write_text(json.dumps(report,indent=2,ensure_ascii=True),encoding='utf8')
        print(json.dumps({'status':report['status'],'report':str(output),'tests':report.get('tests'),
                          'failed_checks':[k for k,v in report.get('checks',{}).items() if not v]}))


if __name__=='__main__':raise SystemExit(main())
