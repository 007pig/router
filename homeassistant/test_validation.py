import asyncio,copy,types
from datetime import datetime
from unittest.mock import patch
import unittest
from test_guard import Harness,g
from guard_under_test.evening import evaluate,refresh_block
from guard_under_test.policy import total_requests,decide

class ValidationTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.g=Harness();await self.g.load();self.now=datetime(2026,10,14,8,20,tzinfo=g.ZONE).timestamp()
  self.sample={'available':True,'soc':26,'charging_status':'not_plugged','direct_switch':'off','charging_mode':None,'measurement_timestamps':{'CHARGING_SUMMARY':self.now-20}}
  self.g.snapshot=lambda:copy.deepcopy(self.sample)
  self.tasks=[];self.notices=[];self.requests=[];self.error=None
  def task(coro,name):
   t=asyncio.create_task(coro);self.tasks.append(t);return t
  self.g.hass.async_create_background_task=task
  async def notice(job):self.notices.append(job)
  self.g.validation_notice=notice
  async def press():
   self.requests.append(1);self.assertTrue(self.g.store.data['pending']);self.assertEqual(self.g.store.data['validation_count'],1)
   if self.error:raise self.error
   self.sample['measurement_timestamps']['CHARGING_SUMMARY']=self.now+1
   self.now+=2
  self.g.press_current=press
  self.at='2026-10-14T08:20:00+01:00'
  with patch.object(g.time,'time',return_value=self.now-100):await self.g.schedule_validation(types.SimpleNamespace(data={'at':self.at}))
 async def asyncTearDown(self):
  await asyncio.gather(*self.tasks);self.g.tmp.cleanup()
 async def run_check(self):
  with patch.object(g.time,'time',side_effect=lambda:self.now):await self.g.perform_validation()
  await asyncio.gather(*self.tasks)
  return self.g.ledger['validation']
 async def test_cached_unplugged_all_modes_no_queries(self):
  for mode in (None,'DIRECT','CYCLIC_DEPARTURE'):
   self.g.ledger['validation']['status']='scheduled';self.sample['charging_mode']=mode
   self.assertFalse(evaluate(self.sample,self.now)['needs_refresh'])
   r=await self.run_check();self.assertEqual(r['status'],'unplugged');self.assertFalse(self.requests)
 async def test_query_success_new_data_and_dedup(self):
  self.sample['measurement_timestamps']['CHARGING_SUMMARY']=self.now-1000
  r=await self.run_check();await self.run_check()
  self.assertEqual(self.requests,[1]);self.assertEqual(len(self.notices),1)
  self.assertEqual(r['vehicle_response'],'取得请求后的新车辆测量')
  self.assertEqual(total_requests(self.g.ledger,'2026-10-14'),1)
 async def test_0700_blocks_query(self):
  self.sample['measurement_timestamps']['CHARGING_SUMMARY']=self.now-1000;self.g.ledger['last_attempt']=self.now-80*60
  r=await self.run_check();self.assertEqual(r['reason'],'minimum_interval');self.assertEqual(r['status'],'incomplete');self.assertFalse(self.requests)
 async def test_global_limit_and_other_entrypoints(self):
  self.sample['measurement_timestamps']['CHARGING_SUMMARY']=self.now-1000
  self.g.ledger.update(date='2026-10-14',count=4,evening_date='2026-10-14',evening_count=1)
  r=await self.run_check();self.assertEqual(r['reason'],'total_daily_limit');self.assertFalse(self.requests)
  self.g.ledger.update(count=3,validation_date='2026-10-14',validation_count=1)
  self.assertEqual(decide(self.now,'2026-10-14|09:00',self.g.ledger,self.sample,100,120,4),'total_daily_limit')
  self.g.ledger.update(count=4,evening_count=0)
  self.assertEqual(refresh_block(self.g.ledger,self.sample,self.now),'total_daily_limit')
 async def test_protection_auth_rate_and_timeout(self):
  for exc in (TimeoutError(),g.ObservedFailure(401),g.ObservedFailure(429,'172800')):
   self.g.ledger={'seen':[],'count':0,'date':'','validation':{'id':self.at,'date':'2026-10-14','due':self.now,'end':self.now+300,'status':'scheduled','used_refresh':False}}
   self.sample['measurement_timestamps']['CHARGING_SUMMARY']=self.now-1000;self.error=exc;self.requests=[]
   r=await self.run_check();self.assertEqual(r['status'],'waiting_confirmation' if isinstance(exc,TimeoutError) else 'incomplete');self.assertEqual(self.requests,[1]);self.assertFalse(r.get('notify'))
 async def test_direct_connected_never_control(self):
  self.sample.update(charging_status='charging',power_kw=7,charging_mode='DIRECT',direct_switch='on')
  self.sample['measurement_timestamps']['CHARGING_RATE']=self.now
  async def forbidden(*a):self.fail('Vehicle control called')
  self.g.disable_direct=forbidden;self.g.hass.services.async_call=forbidden
  r=await self.run_check();self.assertEqual(r['status'],'connected');self.assertFalse(self.requests);self.assertFalse(self.notices)
 async def test_restart_running_never_reissues(self):
  self.g.ledger['validation']['status']='running'
  await self.g.validation_maintenance(self.now)
  self.assertEqual(self.g.ledger['validation']['status'],'unknown');self.assertFalse(self.requests)
 async def test_missed_window_and_cancel(self):
  self.now+=300;r=await self.run_check();self.assertEqual(r['status'],'missed');self.assertFalse(self.requests)
  r['status']='scheduled';await self.g.cancel_validation(None);await self.run_check();self.assertEqual(r['status'],'cancelled')
 async def test_within_recovery_window(self):
  self.now+=299;r=await self.run_check();self.assertEqual(r['status'],'unplugged')
 async def test_invalid_schedule(self):
  with self.assertRaises(ValueError):await self.g.schedule_validation(types.SimpleNamespace(data={'at':'2026-10-14T08:20:00'}))
 def test_explicit_contradictions_unknown(self):
  self.sample.update(plugged=True,plugged_timestamp=self.now)
  self.assertIsNone(evaluate(self.sample,self.now)['plugged'])
 async def test_pending_validation_load_preserves_quota_no_replay(self):
  self.g.ledger.update(pending=True,pending_purpose='validation',validation_date='2026-10-14',validation_count=1)
  self.g.ledger['validation']['status']='running'
  await self.g.store.async_save(self.g.ledger)
  self.assertTrue(await self.g.load())
  self.assertEqual(self.g.ledger['validation']['status'],'unknown')
  self.assertEqual(self.g.ledger['validation_count'],1)
  self.assertFalse(self.g.ledger['pending']);self.assertFalse(self.requests)

 def test_scoped_override_preserves_real_ledger(self):
  from guard_under_test.validation import validation_policy_ledger
  ledger={'blocked_until':2000,'last_attempt':999,'count':4,'validation_count':1}
  policy=validation_policy_ledger(ledger,{'override_limits':True,'approved_unknown_cooldown_until':2000},[{'result':'request_failed_unknown'}])
  self.assertEqual(policy['blocked_until'],0);self.assertEqual(policy['count'],0)
  self.assertEqual(ledger['blocked_until'],2000);self.assertEqual(ledger['validation_count'],1)
 def test_override_cannot_clear_auth_rate_or_changed_deadline(self):
  from guard_under_test.validation import validation_policy_ledger
  for ledger,rows in (({'blocked_until':2000,'auth_block':True},[{'result':'request_failed_unknown'}]),({'blocked_until':2000},[{'result':'rate_limited'}]),({'blocked_until':2001},[{'result':'request_failed_unknown'}]),({'blocked_until':2000},[])):
   policy=validation_policy_ledger(ledger,{'override_limits':True,'approved_unknown_cooldown_until':2000},rows)
   self.assertEqual(policy['blocked_until'],ledger['blocked_until'])
