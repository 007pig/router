"""All switch commands and cached reads are mocked. Never connects to a vehicle."""
import asyncio
import copy
from datetime import datetime
import types
import unittest
from unittest.mock import patch
from test_guard import g,Harness,module
from guard_under_test.direct_control import (CAYENNE_BUTTON,CAYENNE_DIRECT,COMMAND_RECEIPTS,
    capture_command_receipt,confirmed_off)
from guard_under_test.evening import should_notify


class DirectControlTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guard=Harness();await self.guard.load()
        self.clock=datetime(2026,10,13,20,tzinfo=g.ZONE).timestamp()
        self.start=self.clock;self.enabled=True;self.target=CAYENNE_DIRECT
        self.current={'available':True,'charging_status':'charging','power_kw':7,
            'charging_mode':'DIRECT','direct_switch':'on','measurement_timestamps':{
                'CHARGING_SUMMARY':self.clock-30,'CHARGING_RATE':self.clock-30}}
        self.guard.snapshot=lambda:copy.deepcopy(self.current)
        self.guard.value=lambda key:CAYENNE_BUTTON if key=='input_text.porsche_wake_button_entity' else ('on' if self.enabled else 'off')
        self.guard.direct_target=lambda:self.target
        self.guard.vehicle=types.SimpleNamespace(connection=types.SimpleNamespace(asyncClient=types.SimpleNamespace(event_hooks={'response':[]})))
        self.guard.coordinator=types.SimpleNamespace(async_update_listeners=lambda:None)
        self.commands=[];self.cached=0;self.notices=[];self.tasks=[]
        self.outcome='success';self.cache_confirms=False
        async def command(domain,service,data,**kwargs):
            self.commands.append((domain,service,data))
            self.assertEqual((domain,service),('switch','turn_off'))
            self.assertEqual(data,{'entity_id':CAYENNE_DIRECT})
            self.assertEqual(self.guard.store.data['direct_off_count'],1)
            self.assertEqual(self.guard.store.data['pending_purpose'],'direct_off')
            self.assertTrue(self.guard.store.data['pending'])
            receipts=COMMAND_RECEIPTS.get()
            self.assertIsNotNone(receipts)
            self.clock+=2
            if self.outcome=='timeout':raise TimeoutError()
            if self.outcome=='auth':raise g.ObservedFailure(401)
            if self.outcome=='limit':raise g.ObservedFailure(429,'172800')
            receipts.append('ERROR' if self.outcome=='rejected' else 'PERFORMED')
            if self.outcome=='success':self.make_off()
        self.guard.hass.services.async_call=command
        async def cached():
            self.cached+=1
            if self.cache_confirms:self.make_off()
        self.guard.vehicle.get_stored_overview=cached
        def background(coro,name):
            task=asyncio.create_task(coro);self.tasks.append(task);return task
        self.guard.hass.async_create_background_task=background
        async def notice(*a,**k):self.notices.append(a)
        self.guard.send_notice=notice

    def make_off(self):
        self.current.update(charging_mode='PROFILE',direct_switch='off',charging_status='charging_paused',power_kw=0)
        self.current['measurement_timestamps']={k:self.clock for k in ('CHARGING_SUMMARY','CHARGING_RATE')}

    async def asyncTearDown(self):
        await asyncio.gather(*self.tasks);self.guard.tmp.cleanup()

    async def run_check(self):
        async def sleep(seconds):self.clock+=seconds
        with patch.object(g.time,'time',side_effect=lambda:self.clock),patch.object(g.asyncio,'sleep',sleep):
            await self.guard.perform_evening('2026-10-13',self.start,self.start+3600)
        await asyncio.gather(*self.tasks)
        return self.guard.ledger['evening_result']

    async def test_confirmed_off_is_silent_and_quota_separate(self):
        r=await self.run_check()
        self.assertEqual(r['control_state'],'confirmed');self.assertFalse(r['notify'])
        self.assertEqual(len(self.commands),1);self.assertEqual(self.cached,0)
        self.assertEqual(self.guard.ledger['count'],0);self.assertFalse(self.guard.ledger.get('evening_count'))
        self.assertEqual(self.guard.ledger['direct_off_count'],1)
        self.assertEqual(self.notices,[])
        await self.run_check();self.assertEqual(len(self.commands),1)

    async def test_cached_verification_confirms_without_another_command(self):
        self.outcome='unchanged';self.cache_confirms=True
        r=await self.run_check()
        self.assertEqual(r['control_state'],'confirmed');self.assertEqual(self.cached,1)
        self.assertEqual(len(self.commands),1)

    async def test_refresh_then_stop_does_not_wait_two_hours(self):
        self.current['measurement_timestamps']={k:self.start-901 for k in self.current['measurement_timestamps']}
        command=self.guard.hass.services.async_call
        async def combined(domain,service,data,**kw):
            if domain=='button':
                self.commands.append((domain,service,data))
                self.assertEqual(service,'press')
                self.assertEqual(self.guard.store.data['evening_count'],1)
                self.clock+=2
                self.current['measurement_timestamps']={k:self.clock for k in ('CHARGING_SUMMARY','CHARGING_RATE')}
                return
            await command(domain,service,data,**kw)
        self.guard.hass.services.async_call=combined
        r=await self.run_check()
        self.assertEqual(r['control_state'],'confirmed')
        self.assertEqual([x[:2] for x in self.commands],[('button','press'),('switch','turn_off')])
        self.assertEqual(self.guard.ledger['evening_count'],1)
        self.assertEqual(self.guard.ledger['direct_off_count'],1)
        self.assertEqual(self.guard.ledger['count'],0)

    async def test_returned_but_unchanged_is_unknown_with_one_notification(self):
        self.outcome='unchanged'
        r=await self.run_check()
        self.assertEqual(r['control_state'],'unknown');self.assertEqual(self.cached,2)
        self.assertEqual(len(self.notices),1);self.assertEqual(len(self.commands),1)

    async def test_explicit_rejection_is_failure(self):
        self.outcome='rejected'
        r=await self.run_check()
        self.assertEqual(r['control_state'],'failed');self.assertEqual(self.cached,0)
        self.assertEqual(len(self.notices),1)

    async def test_timeout_auth_and_rate_limit_do_not_retry(self):
        for outcome in ('timeout','auth','limit'):
            with self.subTest(outcome=outcome):
                self.guard.ledger={'seen':[],'count':0,'date':'','pending':False}
                self.outcome=outcome;self.commands.clear();self.notices.clear();self.tasks.clear()
                r=await self.run_check()
                self.assertEqual(r['control_state'],'unknown');self.assertEqual(len(self.commands),1)
                self.assertEqual(len(self.notices),1)
                if outcome=='auth':self.assertTrue(self.guard.ledger['auth_block'])
                if outcome=='limit':self.assertGreaterEqual(self.guard.ledger['blocked_until'],self.clock+172800)

    async def test_unplugged_only_reminds_without_control(self):
        self.current.update(charging_status='not_plugged',power_kw=0)
        r=await self.run_check()
        self.assertTrue(r['notify']);self.assertEqual(r['control_state'],'not_executed')
        self.assertEqual(self.commands,[])
        self.assertNotIn('状态无法确认',r['message'])

    async def test_known_non_direct_is_silent(self):
        self.current.update(charging_mode='PROFILE',direct_switch='off')
        r=await self.run_check();self.assertFalse(r['notify']);self.assertEqual(self.commands,[])

    async def test_controls_blocked_when_auth_target_or_quota_invalid(self):
        for why in ('auth','target','limit'):
            self.guard.ledger={'seen':[],'count':0,'date':'','pending':False}
            self.target=None if why=='target' else CAYENNE_DIRECT
            if why=='auth':self.guard.ledger['auth_block']=True
            if why=='limit':self.guard.ledger.update(direct_off_date='2026-10-13',direct_off_count=1)
            r=await self.run_check()
            self.assertEqual(r['control_state'],'failed');self.assertFalse(r['control']['command_sent'])
            self.assertEqual(r['control']['reason'],why)
        self.assertEqual(self.commands,[])

    async def test_preconditions_rechecked_after_persistent_reservation(self):
        save=self.guard.save
        async def changed():
            await save()
            if self.guard.ledger.get('direct_off_count'):self.enabled=False
        self.guard.save=changed
        r=await self.run_check()
        self.assertFalse(r['control']['command_sent']);self.assertEqual(self.commands,[])

    async def test_crash_during_command_never_replays(self):
        job={'date':'2026-10-13','due':self.start,'window_end':self.start+3600,'before':self.current,'used_refresh':False,
             'direct_control':{'state':'closing','command_sent':True,'before':self.current}}
        self.guard.store.data=dict(self.guard.ledger,pending=True,pending_purpose='direct_off',direct_off_date='2026-10-13',direct_off_count=1,evening_job=job)
        with patch.object(g.time,'time',side_effect=lambda:self.clock):
            await self.guard.load();await self.guard.recover_evening()
        self.assertEqual(self.commands,[]);self.assertEqual(self.guard.ledger['evening_result']['control_state'],'unknown')
        self.assertTrue(self.guard.ledger['evening_result']['notify'])

    async def test_restart_during_verification_is_unknown_without_new_reads(self):
        self.guard.ledger['evening_job']={'date':'2026-10-13','due':self.start,'window_end':self.start+3600,
            'before':self.current,'used_refresh':False,'direct_control':{'state':'verifying','command_sent':True}}
        with patch.object(g.time,'time',side_effect=lambda:self.clock):await self.guard.recover_evening()
        self.assertEqual(self.guard.ledger['evening_result']['control_state'],'unknown')
        self.assertEqual(self.commands,[]);self.assertEqual(self.cached,0)

    async def test_restart_before_required_control_reports_not_sent(self):
        self.guard.ledger['evening_job']={'date':'2026-10-13','due':self.start,'window_end':self.start+3600,
            'started':self.start,'before':self.current,'used_refresh':False}
        with patch.object(g.time,'time',side_effect=lambda:self.clock):await self.guard.recover_evening()
        result=self.guard.ledger['evening_result']
        self.assertEqual(result['control_state'],'failed');self.assertTrue(result['notify'])
        self.assertFalse(result['control']['command_sent']);self.assertEqual(self.commands,[])

    async def test_old_unknown_notification_is_not_replayed(self):
        self.assertFalse(should_notify({'notify':True,'plugged':None}))
        self.assertTrue(should_notify({'notify':True,'plugged':False}))

    async def test_confirmation_requires_new_mode_measurement(self):
        before=copy.deepcopy(self.current);self.make_off();after=copy.deepcopy(self.current)
        self.assertTrue(confirmed_off(before,after,self.start,self.start))
        after['measurement_timestamps']['CHARGING_SUMMARY']=self.start-1
        self.assertFalse(confirmed_off(before,after,self.start,self.start))
        after['measurement_timestamps']['CHARGING_SUMMARY']=self.start+1
        self.assertFalse(confirmed_off(before,after,self.start,self.start))
        after['charging_mode']=None;after['measurement_timestamps']['CHARGING_SUMMARY']=self.start
        self.assertFalse(confirmed_off(before,after,self.start,self.start))

    async def test_target_requires_both_exact_entities_on_same_device(self):
        fields=dict(platform='porscheconnect',disabled_by=None,device_id='cayenne')
        entries={CAYENNE_BUTTON:types.SimpleNamespace(**fields,unique_id='fake-get_current_overview'),
                 CAYENNE_DIRECT:types.SimpleNamespace(**fields,unique_id='fake-direct_charging')}
        module('homeassistant.helpers.entity_registry',async_get=lambda h:types.SimpleNamespace(async_get=lambda e:entries.get(e)))
        self.assertEqual(g.Guard.direct_target(self.guard),CAYENNE_DIRECT)
        entries[CAYENNE_DIRECT].device_id='other_vehicle'
        self.assertIsNone(g.Guard.direct_target(self.guard))
        entries[CAYENNE_DIRECT].device_id='cayenne';entries[CAYENNE_DIRECT].disabled_by='user'
        self.assertIsNone(g.Guard.direct_target(self.guard))

    async def test_receipt_hook_drops_sensitive_fields(self):
        async def read():pass
        response=types.SimpleNamespace(status_code=200,request=types.SimpleNamespace(url=types.SimpleNamespace(path='/vehicles/fake/commands')),
            aread=read,json=lambda:{'status':{'result':'PERFORMED','id':'secret'},'private':'secret'})
        receipts=[];token=COMMAND_RECEIPTS.set(receipts)
        try:await capture_command_receipt(response)
        finally:COMMAND_RECEIPTS.reset(token)
        self.assertEqual(receipts,['PERFORMED'])
        response.json=lambda:{'status':{'result':'ERROR','details':'secret'}}
        token=COMMAND_RECEIPTS.set(receipts)
        try:
            with self.assertRaises(g.HomeAssistantError) as caught:await capture_command_receipt(response)
            self.assertNotIn('secret',str(caught.exception))
        finally:COMMAND_RECEIPTS.reset(token)


if __name__=='__main__':unittest.main()
