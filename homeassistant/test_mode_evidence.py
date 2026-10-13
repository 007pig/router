import unittest
from test_guard import g
from guard_under_test.mode_evidence import mode_evidence,describe
from guard_under_test.evening import evaluate,NON_DIRECT_MODES
class ModeEvidence(unittest.TestCase):
 def sample(self,**kw):
  return dict({'charging_status':'charging_paused','direct_switch':'off','measurement_timestamps':{'CHARGING_SUMMARY':1000},'power_kw':None},**kw)
 def test_raw_unknown_enum_preserved(self):
  r=mode_evidence({'mode':'NEW_MODE'},NON_DIRECT_MODES|{'DIRECT'})
  self.assertEqual(r['charging_mode_raw'],'NEW_MODE');self.assertTrue(r['charging_mode_filtered']);self.assertIsNone(r['charging_mode'])
 def test_missing_null_empty_distinguished(self):
  missing=mode_evidence({},set());null=mode_evidence({'mode':None},set());empty=mode_evidence({'mode':''},set())
  self.assertFalse(missing['charging_mode_present']);self.assertTrue(null['charging_mode_present']);self.assertEqual(empty['charging_mode_type'],'str')
 def test_private_or_oversize_mode_redacted(self):
  for raw in ('email@example.org','token/'+ 'x'*100,{},['secret']):
   r=mode_evidence({'mode':raw},set());self.assertTrue(r['charging_mode_redacted']);self.assertIsNone(r['charging_mode_raw'])
 def test_paused_inferred_not_confirmed(self):
  s=self.sample();c=evaluate(s,1007)
  self.assertTrue(c['plugged_inferred']);self.assertIsNone(c['plugged']);self.assertIsNone(c['direct'])
  self.assertEqual(describe(s,c)['plugged_label'],'推断已连接')
  self.assertEqual(describe(s,c)['charging_label'],'暂停等待')
 def test_stale_future_contradictory_no_inference(self):
  for s,now in ((self.sample(),1901),(self.sample(),999),(self.sample(contradictory=True),1007),(self.sample(power_kw=7),1007),(self.sample(plugged=False,plugged_timestamp=1000),1007)):
   self.assertFalse(evaluate(s,now)['plugged_inferred'])
 def test_off_never_direct_even_if_raw_direct(self):
  c=evaluate(self.sample(charging_mode='DIRECT'),1007);self.assertIsNone(c['direct'])
 def test_paused_does_not_override_direct(self):
  c=evaluate(self.sample(charging_mode='DIRECT',direct_switch='on'),1007)
  self.assertTrue(c['direct']);self.assertTrue(c['plugged_inferred']);self.assertIsNone(c['plugged'])

 def test_cyclic_departure_recognized_and_paused_needs_no_query(self):
  mode=mode_evidence({'mode':'CYCLIC_DEPARTURE'},NON_DIRECT_MODES|{'DIRECT'})
  self.assertFalse(mode['charging_mode_filtered']);s=self.sample(**mode);c=evaluate(s,1007)
  self.assertIs(c['direct'],False);self.assertTrue(c['plugged_inferred']);self.assertFalse(c['needs_refresh'])
  self.assertIn('周期出发',describe(s,c)['direct_label'])
 def test_old_mode_does_not_confirm_current_direct(self):
  s=self.sample(charging_mode='CYCLIC_DEPARTURE');c=evaluate(s,1901)
  self.assertIsNone(c['direct']);self.assertIn('陈旧',describe(s,c)['direct_label'])

 def test_unified_connected_states_do_not_grant_control(self):
  for state in ('charging','instant_charging','charging_paused','charging_completed'):
   s=self.sample(charging_status=state,charging_mode='DIRECT',direct_switch='on');c=evaluate(s,1007)
   self.assertIsNone(c['plugged']);self.assertTrue(c['plugged_inferred'])
   self.assertEqual(describe(s,c)['connection_state'],'推断已连接')
   self.assertFalse(describe(s,c)['control_connection_confirmed'])
 def test_unknown_is_not_connected_by_negation(self):
  for state in (None,'unknown','unavailable','other','future_new_state','initialising','charging_error','charging_stopped','not_charging'):
   s=self.sample(charging_status=state);c=evaluate(s,1007)
   self.assertFalse(c['plugged_inferred']);self.assertEqual(describe(s,c)['connection_state'],'未知')
 def test_fresh_disconnected_keeps_mode_independent(self):
  for mode in (None,'DIRECT','CYCLIC_DEPARTURE'):
   s=self.sample(charging_status='not_plugged',charging_mode=mode);c=evaluate(s,1007)
   self.assertEqual(describe(s,c)['connection_state'],'未连接');self.assertFalse(c['needs_refresh'])
 def test_explicit_unplugged_conflicts_with_any_connected_state(self):
  for state in ('charging','instant_charging','charging_paused','charging_completed'):
   c=evaluate(self.sample(charging_status=state,plugged=False,plugged_timestamp=1000),1007)
   self.assertIsNone(c['plugged']);self.assertFalse(c['plugged_inferred'])
