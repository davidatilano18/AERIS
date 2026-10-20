import copy
import unittest
from unittest.mock import patch
from data_ingestion.task_semantics import compare_semantic, compare_snapshot


def definition():
    return {'principal':{'sid':'S-1-5-21-test','group_id':None,'logon_type':3,'run_level':0,'id':'Author'},
        'actions_context':'Author','actions':[{'type':0,'id':None,'path':'C:/AERIS/python.exe',
            'arguments':'-B -m data_ingestion.scheduled_sync','working_directory':'C:/AERIS'}],
        'triggers':[{'type':1,'id':None,'enabled':True,'start_boundary':'2026-10-17T22:05:00',
            'end_boundary':None,'execution_time_limit':None,'random_delay':None,
            'repetition_interval':'PT1H','repetition_duration':None,'stop_at_duration_end':False}],
        'settings':{'Enabled':False,'AllowDemandStart':True,'AllowHardTerminate':True,'StartWhenAvailable':True,
            'RunOnlyIfNetworkAvailable':False,'RunOnlyIfIdle':False,'DisallowStartIfOnBatteries':False,
            'StopIfGoingOnBatteries':False,'WakeToRun':False,'Hidden':False,'MultipleInstances':2,
            'ExecutionTimeLimit':'PT20M','RestartInterval':None,'RestartCount':0,
            'DeleteExpiredTaskAfter':None,'Priority':7,'Compatibility':2},
        'idle_settings':{'IdleDuration':None,'WaitTimeout':None,'StopOnIdleEnd':True,'RestartOnIdle':False},
        'network_settings':{'id':None,'name':None}}


class TaskSemanticsTests(unittest.TestCase):
    def test_verify_only_never_enters_activation_or_run_path(self):
        from scripts import supervise_first_scheduled_run as supervisor
        with patch('scripts.verify_scheduled_configuration.main',return_value=0) as verify, \
                patch.object(supervisor,'registered',side_effect=AssertionError('Unsafe path')), \
                patch.object(supervisor,'disable',side_effect=AssertionError('Task mutation')):
            self.assertEqual(supervisor.main(['--verify-only']),0)
            verify.assert_called_once_with()

    def test_omitted_default_xml_is_not_an_input_to_functional_comparison(self):
        expected = definition()
        snapshot = {'planned_effective':expected,'registered_effective':copy.deepcopy(expected),
            'runtime':{'enabled':False,'state':1,'instances':0},
            'registered_xml':'<Task><Principal/><TimeTrigger/></Task>'}
        self.assertTrue(compare_snapshot(snapshot,expected_enabled=False)['matches'])

    def test_enabled_default_omission_no_longer_causes_final_false_failure(self):
        expected=definition(); actual=copy.deepcopy(expected); actual['settings']['Enabled']=True
        snapshot={'planned_effective':expected,'registered_effective':actual,
            'runtime':{'enabled':True,'state':3,'instances':0},'registered_xml':'<Task><Settings/></Task>'}
        result=compare_snapshot(snapshot,expected_enabled=True)
        self.assertTrue(result['matches']); self.assertEqual(result['compared_parameters'],46)
        self.assertFalse(expected['settings']['Enabled'])  # Never mutate the reference.

    def test_real_functional_changes_fail_for_every_effective_leaf(self):
        expected=definition()
        def paths(v,p=()):
            if isinstance(v,dict):
                for k,x in v.items(): yield from paths(x,p+(k,))
            elif isinstance(v,list):
                for k,x in enumerate(v): yield from paths(x,p+(k,))
            else: yield p,v
        for path,value in paths(expected):
            with self.subTest(property=path):
                actual=copy.deepcopy(expected); target=actual
                for component in path[:-1]: target=target[component]
                target[path[-1]]=not value if type(value) is bool else value+1 if type(value) is int else 'DIFFERENT'
                result=compare_semantic(expected,actual,expected_enabled=False)
                self.assertFalse(result['matches']); self.assertTrue(result['differences'])

    def test_extra_action_or_trigger_fails(self):
        for key in ('actions','triggers'):
            actual=definition(); actual[key].append(copy.deepcopy(actual[key][0]))
            self.assertFalse(compare_semantic(definition(),actual,expected_enabled=False)['matches'])

    def test_missing_or_unknown_effective_property_fails(self):
        actual=definition(); del actual['settings']['WakeToRun']
        self.assertFalse(compare_semantic(definition(),actual,expected_enabled=False)['matches'])
        actual=definition(); actual['settings']['UNKNOWN']=False
        self.assertFalse(compare_semantic(definition(),actual,expected_enabled=False)['matches'])

    def test_numeric_zero_is_not_accepted_as_boolean_false(self):
        actual=definition(); actual['settings']['Enabled']=0
        self.assertFalse(compare_semantic(definition(),actual,expected_enabled=False)['matches'])

    def test_runtime_state_or_instances_cannot_be_hidden_by_matching_xml(self):
        for change in ({'enabled':True},{'state':4},{'instances':1}):
            runtime={'enabled':False,'state':1,'instances':0}; runtime.update(change)
            result=compare_snapshot({'planned_effective':definition(),'registered_effective':definition(),
                'runtime':runtime},expected_enabled=False)
            self.assertFalse(result['matches'])

    def test_enabled_exception_is_only_global_not_trigger_or_other_setting(self):
        actual=definition(); actual['settings']['Enabled']=True; actual['triggers'][0]['enabled']=False
        self.assertFalse(compare_semantic(definition(),actual,expected_enabled=True)['matches'])

    def test_incomplete_expected_snapshot_is_rejected(self):
        with self.assertRaises(ValueError): compare_semantic({},definition(),expected_enabled=False)
        with self.assertRaises(ValueError): compare_semantic(definition(),definition(),expected_enabled=None)

    def test_time_zone_policy_and_user_context_changes_fail(self):
        snapshot={'planned_effective':definition(),'registered_effective':definition(),
            'runtime':{'enabled':False,'state':1,'instances':0},'current_user_sid':'S-1-5-21-test',
            'execution_policy':'Restricted','time_zone':{'id':'Central Standard Time (Mexico)','current_offset':'-06:00'}}
        for path in (('current_user_sid',),('execution_policy',),('time_zone','id'),('time_zone','current_offset')):
            changed=copy.deepcopy(snapshot); target=changed
            for key in path[:-1]: target=target[key]
            target[path[-1]]='DIFFERENT'
            with self.subTest(property=path):
                self.assertFalse(compare_snapshot(changed,expected_enabled=False,reference=snapshot)['matches'])
