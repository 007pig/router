import asyncio
import unittest
from test_guard import Harness,Store
from guard_under_test.evening_notifications import unplugged_message

class Notifications(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.g=Harness();await self.g.load()
        self.g.meta={'notices':{},'evening_channel_cutover':0};self.g.meta_lock=asyncio.Lock();self.g.meta_store=Store()
        self.g.value=lambda key: {'input_text.porsche_wake_whatsapp_target':'+10000000000','input_text.porsche_wake_whatsapp_account':'test-entry','input_text.porsche_wake_notify_service':'mobile_app_test'}.get(key,'')
        self.g.hass.services.has_service=lambda *a:True
        self.calls=[];self.failure=None
        async def call(domain,service,data,**kw):
            self.calls.append((domain,service,data))
            if self.failure==domain:raise TimeoutError()
            return {'success':True,'message_id':'test'}
        self.g.hass.services.async_call=call
        self.r={'date':'2026-10-13','checked_at':'2026-10-13T20:00:00+01:00','plugged':False,'measurement_timestamps':{}}
    async def asyncTearDown(self):self.g.tmp.cleanup()
    async def test_both_channels_and_dedup(self):
        await self.g.send_evening_notice(self.r);await self.g.send_evening_notice(self.r)
        self.assertEqual([c[0] for c in self.calls],['notify','whatsapp'])
        self.assertEqual(self.calls[0][2]['data']['push']['interruption-level'],'time-sensitive')
    async def test_failure_isolation_and_no_retry(self):
        for channel in ('notify','whatsapp'):
            self.g.meta['notices']={};self.calls=[];self.failure=channel
            await self.g.send_evening_notice(self.r);await self.g.send_evening_notice(self.r)
            self.assertEqual(len(self.calls),2)
    async def test_unknown_or_direct_failure_silent(self):
        for plugged in (None,True):
            await self.g.send_evening_notice(dict(self.r,plugged=plugged,control_state='failed'))
        self.assertEqual(self.calls,[])
    async def test_old_results_never_replayed(self):
        self.g.meta['evening_channel_cutover']=2000000000
        self.g.meta['notices']['2026-10-13|evening']='接口已接受'
        await self.g.send_evening_notice(self.r);self.assertEqual(self.calls,[])
    async def test_reserved_after_restart_not_resent(self):
        self.g.meta['notices']={'2026-10-13|evening':'reserved','2026-10-13|evening|whatsapp':'reserved'}
        await self.g.send_evening_notice(self.r);self.assertEqual(self.calls,[])
    async def test_missing_service(self):
        self.g.hass.services.has_service=lambda d,s:d=='notify'
        await self.g.send_evening_notice(self.r)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.g.meta['whatsapp_delivery'],'WhatsApp 服务不可用')
    async def test_rejected_or_empty_response(self):
        for response in ({'success':False},{'success':True},None):
            self.g.meta['notices']={}
            async def call(*a,**kw):return response
            self.g.hass.services.async_call=call
            await self.g.send_evening_notice(self.r)
            self.assertIn('无法确认',self.g.meta['whatsapp_delivery'])
    async def test_storage_failure_blocks_delivery(self):
        async def fail(*a):raise OSError()
        self.g.meta_store.async_save=fail
        await self.g.send_evening_notice(self.r);self.assertEqual(self.calls,[])
    async def test_summary_never_whatsapp(self):
        await self.g.send_notice('摘要','summary','2026-10-13')
        self.assertEqual([c[0] for c in self.calls],['notify'])
    def test_message_excludes_control_failures(self):
        message=unplugged_message(dict(self.r,message='Direct 关闭失败',control_state='failed'))
        self.assertIn('尚未插入充电枪',message);self.assertNotIn('Direct',message)
