import asyncio,copy,types,unittest
from datetime import datetime
from unittest.mock import patch
from test_guard import Harness,g
from guard_under_test.confirmation import summary_advanced
from guard_under_test.policy import decide
from guard_under_test.evening import refresh_block
from guard_under_test.evidence import classify

class ConfirmationTest(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.g=Harness();await self.g.load();self.now=datetime(2026,10,14,5,tzinfo=g.ZONE).timestamp();self.start=self.now
  self.current={'available':True,'charging_status':'not_plugged','charging_mode':'CYCLIC_DEPARTURE','direct_switch':'off','soc':80,'measurement_timestamps':{'CHARGING_SUMMARY':self.now-10}}
  self.before=copy.deepcopy(self.current);self.g.snapshot=lambda:copy.deepcopy(self.current)
  self.reads=0;self.advance=True;self.error=None;self.tasks=[];self.messages=[]
  async def read(job):
   self.reads+=1;self.assertEqual(self.g.store.data['confirmation']['state'],'reading')
   if self.error:raise self.error
   if self.advance:self.current['measurement_timestamps']['CHARGING_SUMMARY']=self.now-1
  self.g.confirmation_cached_read=read
  def background(coro,name):
   t=asyncio.create_task(coro);self.tasks.append(t);return t
  self.g.hass.async_create_background_task=background
  self.g.notify=lambda *a:self.messages.append(a)
 async def asyncTearDown(self):
  await asyncio.gather(*self.tasks);self.g.tmp.cleanup()
 async def defer(self,purpose='night',exc=None):
  self.g.ledger.update(pending=True,count=1,last_attempt=self.start)
  with patch.object(g.time,'time',side_effect=lambda:self.now):
   return await self.g.defer_request_failure(exc or RuntimeError('private'),purpose,self.before,self.start,'2026-10-14|05:00')
 async def check(self):
  with patch.object(g.time,'time',side_effect=lambda:self.now):await self.g.perform_confirmation()
  await asyncio.gather(*self.tasks)
 async def test_wait_then_success_no_cooldown_no_wake(self):
  await self.defer();await self.check();self.assertEqual(self.reads,0);self.assertFalse(self.messages)
  self.now+=300;await self.check();await self.check()
  self.assertEqual(self.reads,1);self.assertEqual(self.g.ledger['blocked_until'],0)
  self.assertEqual(self.g.ledger['count'],1);self.assertFalse(self.g.calls)
  self.assertEqual(self.g.ledger['last_confirmation']['state'],'success');self.assertFalse(self.g.ledger.get('observation'))
 async def test_no_new_data_final_failure_only_once(self):
  self.advance=False;await self.defer();self.now+=300;await self.check();await self.check()
  self.assertEqual(self.reads,1);self.assertEqual(len(self.messages),1)
  self.assertGreater(self.g.ledger['blocked_until'],self.now)
 async def test_auth_and_rate_never_deferred(self):
  for code in (401,403,429):self.assertFalse(await self.defer(exc=g.ObservedFailure(code)))
  self.assertFalse(self.g.ledger.get('confirmation'));self.assertEqual(self.reads,0)
 async def test_read_failure_classes(self):
  for exc in (TimeoutError(),g.ObservedFailure(401),g.ObservedFailure(429,'172800')):
   self.g.ledger.update(blocked_until=0,auth_block=False);await self.defer();self.now+=300;self.error=exc
   await self.check();self.assertEqual(self.g.ledger['last_confirmation']['state'],'failed')
   self.assertNotIn('confirmation',self.g.ledger)
 async def test_restart_waiting_and_reading(self):
  await self.defer();await self.g.load();self.now+=300;await self.check();self.assertEqual(self.reads,1)
  await self.defer();self.g.ledger['confirmation']['state']='reading';await self.g.save();await self.g.load()
  await self.check();self.assertEqual(self.reads,1);self.assertEqual(self.g.ledger['last_confirmation']['reason'],'interrupted_request_unknown')
 async def test_late_recovery_only_existing_cache(self):
  await self.defer();self.now+=601;self.current['measurement_timestamps']['CHARGING_SUMMARY']=self.now-1
  await self.check();self.assertEqual(self.reads,0);self.assertEqual(self.g.ledger['last_confirmation']['state'],'success')
 async def test_late_old_cache_fails(self):
  await self.defer();self.now+=601;await self.check();self.assertEqual(self.reads,0);self.assertEqual(self.g.ledger['last_confirmation']['state'],'failed')
 async def test_existing_protection_preserved(self):
  await self.defer();self.g.ledger['blocked_until']=self.now+172800;self.now+=300;await self.check()
  self.assertEqual(self.reads,0);self.assertEqual(self.g.ledger['blocked_until'],self.start+172800)
 async def test_wait_blocks_all_query_and_control_paths(self):
  await self.defer()
  self.assertEqual(decide(self.now,'x',self.g.ledger,self.current,100,120,4),'confirmation_pending')
  self.assertEqual(refresh_block(self.g.ledger,self.current,self.now),'confirmation_pending')
  self.assertEqual(self.g.control_block(self.current,self.now,self.now+600),'busy')
 async def test_validation_finishes_outside_original_window_no_control(self):
  self.g.ledger['validation']={'id':'test','date':'2026-10-14','due':self.now,'end':self.now+60,'status':'running','used_refresh':True,'request_started':self.now,'before':self.before}
  notices=[]
  async def notice(job):notices.append(job)
  self.g.validation_notice=notice
  await self.defer('validation');self.now+=300;await self.check()
  self.assertEqual(self.g.ledger['validation']['status'],'unplugged');self.assertEqual(len(notices),1);self.assertFalse(self.g.calls)
 async def test_evening_finished_no_control_after_window(self):
  self.g.ledger['evening_job']={'date':'2026-10-14','due':self.now,'window_end':self.now+60,'used_refresh':True,'before':self.before}
  async def notice(*a):pass
  self.g.send_evening_notice=notice
  await self.defer('evening');self.now+=300;await self.check()
  self.assertEqual(self.g.ledger['evening_result']['query_result'],'延迟确认成功');self.assertFalse(self.g.calls)
 def test_timestamp_requirements(self):
  for stamp in (None,self.start-1,self.start,self.start+301,float('nan')):
   self.assertFalse(summary_advanced(self.before,{'measurement_timestamps':{'CHARGING_SUMMARY':stamp}},self.start,self.start+300))
  self.assertTrue(summary_advanced(self.before,{'measurement_timestamps':{'CHARGING_SUMMARY':self.start+1},'soc':None,'power_kw':None},self.start,self.start+300))
 def test_report_keeps_error_and_response_separate(self):
  rows=[{'utc':'2026-10-14T04:00:00+00:00','result':'request_started','before':self.before},
        {'utc':'2026-10-14T04:00:01+00:00','result':'request_confirmation_pending'},
        {'utc':'2026-10-14T04:05:02+00:00','result':'request_delayed_confirmed','after':self.current}]
  report=classify(rows);self.assertEqual(report['request'],'延迟确认成功');self.assertEqual(report['response'],'取得车辆新数据');self.assertFalse(report['observations_complete'])

 async def test_replay_0500_failure_with_simulated_followup(self):
  # Real sanitized 2026-10-14 failure timestamps; the later response is simulated.
  started=1791950400.483596;failed=1791950401.028862
  self.start=started;self.now=failed
  self.before={'soc':80,'charging_status':'charging_paused','measurement_timestamps':{'CHARGING_SUMMARY':1791946930.0}}
  await self.defer();self.assertEqual(self.g.ledger['confirmation']['due'],failed+300)
  self.now=failed+300;await self.check()
  self.assertEqual(self.g.ledger['last_confirmation']['state'],'success')
 async def test_new_auth_and_mapping_change_block_read(self):
  await self.defer();self.g.ledger['auth_block']=True;self.now+=300;await self.check();self.assertEqual(self.reads,0)
  self.g.ledger['auth_block']=False;await self.defer();self.g.ledger['confirmation']['button']='different';self.now+=300
  await self.check();self.assertEqual(self.reads,0)
 async def test_ready_after_crash_finishes_without_read(self):
  await self.defer();self.now+=300;job=self.g.ledger['confirmation']
  job.update(state='ready',after=self.current,confirmed=True,reason=None)
  await self.check();self.assertEqual(self.reads,0);self.assertEqual(self.g.ledger['last_confirmation']['state'],'success')

 async def test_manual_cached_test_preserves_cooldown_and_counts(self):
  self.g.vehicle=types.SimpleNamespace(vin='test')
  self.g.ledger.update(blocked_until=self.now+86400,count=2,validation_count=1)
  with patch.object(g.time,'time',side_effect=lambda:self.now):
   async def cached(job):self.reads+=1
   self.g.confirmation_cached_read=cached
   await self.g.test_confirmation_cache(types.SimpleNamespace(data={'ignore_cooldown':True}))
  self.assertEqual(self.reads,1);self.assertFalse(self.g.calls)
  self.assertEqual(self.g.ledger['blocked_until'],self.now+86400);self.assertEqual(self.g.ledger['count'],2)
  self.assertEqual(self.g.ledger['confirmation_test']['status'],'success')

 async def test_paired_read_success_schedules_five_minutes_even_on_success(self):
  self.g.vehicle=types.SimpleNamespace(vin='test');self.g.ledger['blocked_until']=self.now+86400
  async def press():self.now+=30
  self.g.press_current=press
  with patch.object(g.time,'time',side_effect=lambda:self.now):await self.g.test_realtime_then_cache(types.SimpleNamespace(data={'override_limits':True}))
  self.assertEqual(self.g.ledger['confirmation']['due'],self.start+300)
  self.now=self.start+300;await self.check()
  self.assertEqual(self.reads,1);self.assertEqual(self.g.ledger['blocked_until'],self.start+86400)
