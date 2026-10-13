"""Exercise the real guard with fake HA services/storage, never a real car."""
import asyncio
import copy
import importlib.util
from pathlib import Path
import sys
import types
import tempfile
import logging
import unittest
from unittest.mock import patch


def module(name, **values):
    m=types.ModuleType(name)
    m.__dict__.update(values)
    sys.modules[name]=m
    return m


class Store:
    data=None
    def __init__(self,*a,**kw):pass
    async def async_load(self):return copy.deepcopy(self.data)
    async def async_save(self,value):self.data=copy.deepcopy(value)


module("voluptuous",Schema=lambda *a,**k:None,ALLOW_EXTRA=True,Optional=lambda *a,**k:a[0],Required=lambda *a,**k:a[0])
module("homeassistant")
module("homeassistant.helpers")
module("homeassistant.helpers.config_validation",boolean=bool)
module("homeassistant.helpers.storage",Store=Store)
module("homeassistant.components")
module("homeassistant.exceptions",HomeAssistantError=Exception)
module("homeassistant.components.persistent_notification",async_create=lambda *a,**k:None)
path=Path(__file__).parent/"custom_components/porsche_wake_guard"
spec=importlib.util.spec_from_file_location("guard_under_test",path/"__init__.py",submodule_search_locations=[str(path)])
g=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=g
spec.loader.exec_module(g)


class Harness(g.Guard):
    def __init__(self):
        self.calls=[]
        self.records=[]
        self.error=None
        self.saved_before_call=False
        async def call(*args,**kwargs):
            self.calls.append((args,kwargs))
            self.saved_before_call=self.store.data["pending"] and self.store.data["count"]==1
            if self.error:raise self.error
        self.tmp=tempfile.TemporaryDirectory()
        async def executor(fn,*args):return fn(*args)
        hass=types.SimpleNamespace(config=types.SimpleNamespace(path=lambda x:self.tmp.name+"/"+x,time_zone="Europe/Dublin"),
            services=types.SimpleNamespace(async_call=call),async_add_executor_job=executor,
            states=types.SimpleNamespace(async_set=lambda *a,**k:None))
        super().__init__(hass)
    def value(self,key):
        if key=="input_text.porsche_wake_button_entity":return "button.cayenne_get_current_overview"
        if key.startswith("input_boolean"):return "on"
        return "unavailable"
    def number(self,key,default):return default
    def snapshot(self):return dict(available=True,vehicle_timestamp=None)
    def publish(self,*a,**kw):pass
    def notify(self,*a):pass
    async def record(self,result,**attrs):self.records.append(result)


class GuardTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):self.guard.tmp.cleanup()
    async def asyncSetUp(self):
        self.guard=Harness()
        self.assertTrue(await self.guard.load())
        self.call=types.SimpleNamespace(data={"manual":True})

    async def test_success_reserved_before_press_and_no_repeat(self):
        async def no_sleep(*a):pass
        with patch.object(g.asyncio,"sleep",no_sleep):
            await self.guard.run(self.call)
            await self.guard.run(self.call)
        self.assertEqual(len(self.guard.calls),1)
        self.assertTrue(self.guard.saved_before_call)
        args,kw=self.guard.calls[0]
        self.assertEqual(args[:2],("button","press"))
        self.assertIn("service_returned_success",self.guard.records)
        self.assertEqual(self.guard.records.count("observation"),5)

    async def test_unknown_error_blocks_no_retry(self):
        self.guard.error=RuntimeError("SECRET MUST NOT BE LOGGED")
        await self.guard.run(self.call)
        self.assertEqual(self.guard.records[-1],"request_failed_unknown")
        self.assertGreater(self.guard.ledger["blocked_until"],g.time.time())
        self.assertEqual(len(self.guard.calls),1)

    async def test_rate_limit_retry_after(self):
        exc=RuntimeError()
        exc.response=types.SimpleNamespace(status_code=429,headers={"Retry-After":"172800"})
        self.guard.error=exc
        await self.guard.run(self.call)
        self.assertEqual(self.guard.records[-1],"rate_limited")
        self.assertGreater(self.guard.ledger["blocked_until"],g.time.time()+172790)

    async def test_auth_blocks(self):
        exc=RuntimeError();exc.status_code=401
        self.guard.error=exc
        await self.guard.run(self.call)
        self.assertTrue(self.guard.ledger["auth_block"])

    async def test_save_failure_prevents_network(self):
        async def fail(*a):raise OSError()
        self.guard.store.async_save=fail
        with self.assertRaises(OSError):await self.guard.run(self.call)
        self.assertEqual(self.guard.calls,[])
        self.assertTrue(self.guard.failed)

    async def test_restart_pending_becomes_24h_hold(self):
        self.guard.store.data=dict(self.guard.ledger,pending=True)
        self.assertTrue(await self.guard.load())
        self.assertFalse(self.guard.ledger["pending"])
        self.assertGreater(self.guard.ledger["blocked_until"],g.time.time()+86390)

    async def test_concurrent_invocation_does_not_send(self):
        async with self.guard.lock:await self.guard.run(self.call)
        self.assertEqual(self.guard.calls,[])

    async def test_lost_ledger_fails_closed(self):
        self.guard.store.data=None
        self.assertFalse(await self.guard.load())

    async def test_swallowed_library_error_is_detected_and_redacted(self):
        filt=g.PrivateFailureCapture()
        async def swallowed(*a,**kw):
            exc=RuntimeError('SECRET RESPONSE');exc.code=429
            record=logging.LogRecord('pyporscheconnectapi.vehicle',logging.ERROR,'',0,'SECRET URL',(),(type(exc),exc,None))
            self.assertFalse(filt.filter(record))
        self.guard.hass.services.async_call=swallowed
        await self.guard.run(self.call)
        self.assertEqual(self.guard.records[-1],'rate_limited')
        self.assertNotIn('service_returned_success',self.guard.records)

    async def test_actual_measurement_schema_and_future_timestamp(self):
        from datetime import datetime,timezone
        now=g.time.time()
        iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
        measurements=[{'key':k,'status':{'isEnabled':True},'value':{'lastModified':iso(now-30)}}
                      for k in ('BATTERY_LEVEL','CHARGING_SUMMARY','CHARGING_RATE')]
        vehicle=types.SimpleNamespace(vin='test',status={'measurements':measurements})
        self.guard.hass.data={'porscheconnect':{'account':types.SimpleNamespace(vehicles=[vehicle])}}
        entry=types.SimpleNamespace(platform='porscheconnect',unique_id='test-get_current_overview',disabled_by=None)
        module('homeassistant.helpers.entity_registry',async_get=lambda h:types.SimpleNamespace(async_get=lambda e:entry))
        values={'input_text.porsche_wake_button_entity':'button.test','button.test':'unknown',
                'input_text.porsche_wake_soc_entity':'sensor.soc','sensor.soc':'74',
                'input_text.porsche_wake_power_entity':'sensor.power','sensor.power':'0',
                'input_text.porsche_wake_charging_entity':'sensor.charging','sensor.charging':'charging_paused'}
        self.guard.value=lambda key:values.get(key,'unavailable')
        snapshot=g.Guard.snapshot(self.guard)
        self.assertTrue(snapshot['available']) # An unpressed button's state is unknown, not unavailable.
        self.assertEqual(snapshot['charging_status'],'charging_paused')
        self.assertAlmostEqual(snapshot['vehicle_timestamp'],now-30,places=4)
        measurements[2]['value']['chargingPowerkW']=7.2
        self.assertEqual(g.Guard.snapshot(self.guard)['power_kw'],7.2)
        self.assertEqual(g.Guard.snapshot(self.guard)['power_source'],'CHARGING_RATE.chargingPowerkW')
        measurements[0]['value']['lastModified']=iso(now+600)
        self.assertIsNone(g.Guard.snapshot(self.guard)['vehicle_timestamp'])

    async def test_cached_reads_never_send_another_wake(self):
        calls=[]
        async def cached():calls.append('cached')
        self.guard.vehicle=types.SimpleNamespace(get_stored_overview=cached,
            connection=types.SimpleNamespace(asyncClient=types.SimpleNamespace(event_hooks={'response':[]})))
        self.guard.coordinator=types.SimpleNamespace(async_update_listeners=lambda:None)
        async def no_sleep(*a):pass
        with patch.object(g.asyncio,'sleep',no_sleep):await self.guard.run(self.call)
        self.assertEqual(len(self.guard.calls),1)
        self.assertEqual(calls,['cached','cached'])

    async def test_http_error_hook_prevents_upstream_retries_only_in_guard(self):
        response=types.SimpleNamespace(status_code=429,headers={'Retry-After':'172800'})
        await g.stop_library_retry(response) # Outside a guarded request: no effect.
        token=g.REQUEST_FAILURES.set([])
        try:
            with self.assertRaises(g.ObservedFailure) as caught:await g.stop_library_retry(response)
            self.assertEqual(caught.exception.status_code,429)
            self.assertEqual(g.retry_deadline(caught.exception,100),172900)
        finally:g.REQUEST_FAILURES.reset(token)

    async def test_resume_observation_skips_past_nodes_without_wake(self):
        calls=[]
        async def cached():calls.append('cached')
        self.guard.vehicle=types.SimpleNamespace(get_stored_overview=cached,connection=types.SimpleNamespace(asyncClient=types.SimpleNamespace(event_hooks={'response':[]})))
        self.guard.coordinator=types.SimpleNamespace(async_update_listeners=lambda:None)
        self.guard.ledger['observation']={'slot':'2026-10-13|03:00','before':{},'started':g.time.time()-300,'cursor':0,'button':'button.cayenne_get_current_overview'}
        async def no_sleep(*a):pass
        with patch.object(g.asyncio,'sleep',no_sleep):await self.guard.resume_observation()
        self.assertEqual(self.guard.calls,[])
        self.assertEqual(calls,['cached'])
        self.assertEqual(self.guard.records.count('observation_node_missed'),2)
        self.assertNotIn('observation',self.guard.ledger)

    async def test_cancel_observation_sends_no_cached_request(self):
        self.guard.ledger['observation']={'slot':'2026-10-13|03:00','before':{},'started':g.time.time(),'cursor':0,'button':'button.cayenne_get_current_overview'}
        self.guard.value=lambda key:'off'
        async def no_sleep(*a):pass
        with patch.object(g.asyncio,'sleep',no_sleep):await self.guard.observe()
        self.assertIn('observation_cancelled',self.guard.records)
        self.assertNotIn('observation',self.guard.ledger)

    async def test_notifications_deduplicate_outside_vehicle_lock(self):
        self.guard.meta={'notices':{}}
        self.guard.meta_store=Store()
        self.guard.meta_lock=asyncio.Lock()
        self.guard.hass.services.has_service=lambda *a:True
        self.guard.value=lambda key:'mobile_app_test'
        self.guard.hass.services.async_call=None
        deliveries=[]
        async def deliver(*a,**kw):deliveries.append(a)
        self.guard.hass.services.async_call=deliver
        async with self.guard.lock:
            await self.guard.send_notice('test','fault:test','2026-10-13')
            await self.guard.send_notice('test','fault:test','2026-10-13')
        self.assertEqual(len(deliveries),1)
        self.assertIn('接口已接受',self.guard.meta['delivery'])

    async def test_notification_failure_is_recorded_and_not_retried(self):
        self.guard.meta={'notices':{}};self.guard.meta_store=Store();self.guard.meta_lock=asyncio.Lock()
        self.guard.hass.services.has_service=lambda *a:True
        self.guard.value=lambda key:'mobile_app_test'
        attempts=[]
        async def fail(*a,**kw):attempts.append(1);raise TimeoutError()
        self.guard.hass.services.async_call=fail
        await self.guard.send_notice('test','summary','2026-10-13')
        await self.guard.send_notice('test','summary','2026-10-13')
        self.assertEqual(attempts,[1])
        self.assertEqual(self.guard.meta['delivery'],'手机推送失败')

    async def test_summary_due_dedup_and_midday_cutoff(self):
        from datetime import datetime
        date='2026-10-13'
        now=datetime(2026,10,13,8,5,tzinfo=g.ZONE).timestamp()
        self.guard.meta={'notices':{},'armed':{},'nights':{},'pruned':date}
        self.guard.meta_store=Store();self.guard.meta_lock=asyncio.Lock();self.guard.maintenance_lock=asyncio.Lock()
        self.guard.last_recorded=None
        values={'input_boolean.porsche_wake_enabled':'on','automation.porsche_wake_scheduler':'on',
                'input_datetime.porsche_wake_departure_time':'08:00:00','input_datetime.porsche_wake_summary_time':'08:05:00',
                'input_text.porsche_wake_notify_service':'mobile_app_test'}
        self.guard.value=lambda key:values.get(key,'unavailable')
        self.guard.hass.states.get=lambda key:None
        self.guard.hass.services.has_service=lambda *a:True
        deliveries=[]
        async def deliver(*a,**kw):deliveries.append(a)
        self.guard.hass.services.async_call=deliver
        tasks=[]
        def background(coro,name):
            task=asyncio.create_task(coro);tasks.append(task);return task
        self.guard.hass.async_create_background_task=background
        self.guard.rows=[{'utc':'2026-10-13T06:00:00+00:00','slot':date+'|07:00','result':'target_reached','before':{'soc':100,'vehicle_timestamp':now-3900}}]
        with patch.object(g.time,'time',return_value=now):
            await self.guard.maintenance();await self.guard.maintenance()
            await asyncio.gather(*tasks)
        self.assertEqual(len(deliveries),1)
        self.assertEqual(self.guard.meta['summary']['date'],date)
        self.guard.meta.pop('summary')
        tasks.clear()
        with patch.object(g.time,'time',return_value=now+4*3600):await self.guard.maintenance()
        self.assertNotIn('summary',self.guard.meta)

    async def test_watchdog_missing_slot_once_and_day_count_reset(self):
        from datetime import datetime
        now=datetime(2026,10,13,2,tzinfo=g.ZONE).timestamp()
        self.guard.meta={'notices':{},'armed':{'2026-10-13|01:00':now-3600},'nights':{},'pruned':'2026-10-13'}
        self.guard.meta_store=Store();self.guard.meta_lock=asyncio.Lock();self.guard.maintenance_lock=asyncio.Lock()
        self.guard.rows=[];self.guard.last_recorded='2026-10-12T06:00:00Z'
        self.guard.ledger.update(date='2026-10-12',count=3)
        values={}
        self.guard.hass.states.get=lambda key:types.SimpleNamespace(state='old',attributes={})
        self.guard.hass.states.async_set=lambda key,state,attrs:values.update({key:(state,attrs)})
        notices=[];self.guard.notify=lambda *a:notices.append(a)
        with patch.object(g.time,'time',return_value=now):
            await self.guard.maintenance();await self.guard.maintenance()
        self.assertEqual(len(notices),1)
        self.assertIn('01:00',notices[0][0])
        self.assertEqual(values['sensor.porsche_wake_result'][1]['today_attempts'],0)
        self.assertEqual(self.guard.ledger['count'],3)


if __name__=="__main__":unittest.main()
