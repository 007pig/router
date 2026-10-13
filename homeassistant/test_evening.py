"""Evening checks use mock services only; no vehicle or notification traffic."""
import asyncio
import copy
from datetime import datetime
import unittest
from unittest.mock import patch
from test_guard import g,Harness,Store
from guard_under_test.evening import evaluate,refresh_block,check_window
from guard_under_test.policy import daily_counts,decide
from guard_under_test.evidence import night_report


class EveningTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guard=Harness();await self.guard.load()
        self.now=datetime(2026,10,13,20,tzinfo=g.ZONE).timestamp()
        self.date='2026-10-13'
        self.sample={'available':True,'charging_status':'charging','power_kw':7,
                     'charging_mode':'PROFILE','direct_switch':'off',
                     'measurement_timestamps':{'CHARGING_SUMMARY':self.now-10,'CHARGING_RATE':self.now-10}}
        self.current=copy.deepcopy(self.sample)
        self.guard.snapshot=lambda:copy.deepcopy(self.current)
        self.tasks=[];self.notices=[];self.calls=[]
        def background(coro,name):
            task=asyncio.create_task(coro);self.tasks.append(task);return task
        self.guard.hass.async_create_background_task=background
        async def notice(*a,**k):self.notices.append((a,k))
        self.guard.send_notice=notice
        self.after=None;self.error=None
        async def press(*args,**kwargs):
            self.calls.append(args)
            self.assertTrue(self.guard.store.data['pending'])
            self.assertEqual(self.guard.store.data['evening_count'],1)
            if self.error:raise self.error
            if self.after is not None:self.current=copy.deepcopy(self.after)
        self.guard.hass.services.async_call=press

    async def asyncTearDown(self):
        await asyncio.gather(*self.tasks)
        self.guard.tmp.cleanup()

    async def run_check(self):
        with patch.object(g.time,'time',return_value=self.now):
            await self.guard.perform_evening(self.date,self.now,self.now+3600)
        await asyncio.gather(*self.tasks)

    async def test_normal_silent_no_query(self):
        await self.run_check()
        self.assertEqual(self.calls,[]);self.assertEqual(self.notices,[])
        self.assertFalse(self.guard.ledger['evening_result']['notify'])

    async def test_unplugged_and_direct_combined_no_query(self):
        self.current.update(charging_status='not_plugged',power_kw=0,charging_mode='DIRECT',direct_switch='on')
        await self.run_check()
        self.assertEqual(self.calls,[]);self.assertEqual(len(self.notices),1)
        r=self.guard.ledger['evening_result']
        self.assertIs(r['plugged'],False);self.assertIs(r['direct'],True)

    async def test_unknown_queried_once_no_observation_no_night_budget(self):
        self.current.update(charging_status='charging_paused',power_kw=None,charging_mode=None)
        self.guard.ledger.update(date=self.date,count=4)
        await self.run_check();await self.run_check()
        self.assertEqual(len(self.calls),1);self.assertEqual(len(self.notices),0)
        self.assertEqual(daily_counts(self.guard.ledger,self.date),(4,1))
        self.assertNotIn('observation',self.guard.ledger)

    async def test_stale_becomes_normal_after_single_query(self):
        self.current['measurement_timestamps']={k:self.now-901 for k in self.sample['measurement_timestamps']}
        self.after=self.sample
        await self.run_check()
        self.assertEqual(len(self.calls),1);self.assertEqual(self.notices,[])

    async def test_missing_mode_with_off_is_unknown(self):
        self.sample['charging_mode']=None
        self.assertIsNone(evaluate(self.sample,self.now)['direct'])

    async def test_future_and_contradictory_fields_are_unknown(self):
        self.sample['measurement_timestamps']={k:self.now+30 for k in self.sample['measurement_timestamps']}
        self.assertTrue(evaluate(self.sample,self.now)['needs_refresh'])
        self.sample['measurement_timestamps']={k:self.now for k in self.sample['measurement_timestamps']}
        self.sample.update(charging_status='not_plugged',power_kw=7,charging_mode='DIRECT',direct_switch='off')
        r=evaluate(self.sample,self.now)
        self.assertIsNone(r['plugged']);self.assertIsNone(r['direct'])

    async def test_paused_completed_or_zero_do_not_prove_connected(self):
        for state in ('charging_paused','charging_completed','initialising'):
            self.sample.update(charging_status=state,power_kw=0)
            self.assertIsNone(evaluate(self.sample,self.now)['plugged'])

    async def test_protection_gates(self):
        for fields,reason in [({'auth_block':True},'authentication_required'),({'blocked_until':self.now+5},'failure_cooldown'),({'last_attempt':self.now-7199},'minimum_interval'),({'pending':True},'request_busy'),({'evening_date':self.date,'evening_count':1},'evening_limit'),({'date':self.date,'count':5},'total_daily_limit')]:
            self.assertEqual(refresh_block(fields,self.sample,self.now),reason)
        self.assertEqual(refresh_block({},self.sample,self.now,True),'storage_unavailable')

    async def test_unknown_blocked_check_is_silent_without_query(self):
        self.current['charging_mode']=None
        self.guard.ledger['auth_block']=True
        await self.run_check()
        self.assertEqual(self.calls,[]);self.assertEqual(len(self.notices),0)

    async def test_http_429_single_attempt_and_cooldown(self):
        self.current['charging_mode']=None
        self.error=g.ObservedFailure(429,'172800')
        await self.run_check()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.guard.ledger['blocked_until'],self.now+172800)
        self.assertEqual(self.guard.ledger['evening_result']['reason'],'rate_limited')

    async def test_restart_interrupted_query_never_replays(self):
        self.guard.store.data=dict(self.guard.ledger,pending=True,pending_purpose='evening',evening_date=self.date,evening_count=1,
            evening_job={'date':self.date,'due':self.now,'window_end':self.now+3600,'before':self.sample,'used_refresh':True})
        with patch.object(g.time,'time',return_value=self.now):
            await self.guard.load();await self.guard.recover_evening()
        self.assertEqual(self.calls,[])
        self.assertEqual(self.guard.ledger['evening_result']['reason'],'interrupted_request_unknown')
        self.assertFalse(self.guard.ledger['pending'])

    async def test_window_and_night_isolation(self):
        self.assertIsNone(check_window(self.now-1,'20:00'))
        self.assertIsNotNone(check_window(self.now+3599,'20:00'))
        self.assertIsNone(check_window(self.now+3600,'20:00'))
        report=night_report([{'utc':'2026-10-13T19:00:00Z','slot':self.date+'|20:00','purpose':'evening_check','result':'request_started'}],self.date)
        self.assertFalse(report['has_records']);self.assertEqual(report['requests'],0)

    async def test_daily_caps_and_reset(self):
        ledger={'date':self.date,'count':4,'evening_date':self.date,'evening_count':1,'seen':[]}
        self.assertEqual(decide(self.now,self.date+'|20:00',ledger,self.sample,100,120,5),'daily_limit')
        self.assertEqual(daily_counts(ledger,'2026-10-14'),(0,0))

    async def test_custom_late_check_window_and_actual_day_budget(self):
        now=datetime(2026,10,14,0,15,tzinfo=g.ZONE).timestamp()
        window=check_window(now,'23:30')
        self.assertEqual(window[0],'2026-10-13')
        self.current['charging_mode']=None
        with patch.object(g.time,'time',return_value=now):await self.guard.perform_evening(*window)
        self.assertEqual(self.guard.ledger['evening_date'],'2026-10-14')
        self.assertEqual(self.guard.ledger['evening_result']['date'],'2026-10-13')

    async def test_independent_of_night_master_switch(self):
        original=self.guard.value
        self.guard.value=lambda key:'off' if key=='input_boolean.porsche_wake_enabled' else original(key)
        self.current['charging_mode']=None
        await self.run_check()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.guard.ledger['count'],0)

    async def test_phone_failure_does_not_repeat_vehicle_query(self):
        self.current['charging_mode']=None
        self.after=dict(self.sample,charging_status='not_plugged',power_kw=0)
        self.guard.meta={'notices':{}};self.guard.meta_store=Store();self.guard.meta_lock=asyncio.Lock()
        original_value=self.guard.value
        self.guard.value=lambda key:'mobile_app_test' if key=='input_text.porsche_wake_notify_service' else original_value(key)
        self.guard.hass.services.has_service=lambda *a:True
        press=self.guard.hass.services.async_call
        mobile=[]
        async def call(*a,**kw):
            if a[0]=='notify':mobile.append(1);raise TimeoutError()
            return await press(*a,**kw)
        self.guard.hass.services.async_call=call
        del self.guard.send_notice
        await self.run_check();await self.run_check()
        self.assertEqual(len(self.calls),1);self.assertEqual(mobile,[1])
        self.assertEqual(self.guard.meta['delivery'],'手机推送失败')


if __name__=='__main__':unittest.main()
