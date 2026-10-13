"""Unplugged-only notices. Persist reservations before independent channel calls."""
import asyncio
import re
import time
from datetime import datetime
from .policy import ZONE


def unplugged_message(result):
    stamp=result.get('measurement_timestamps',{}).get('CHARGING_SUMMARY')
    measured=datetime.fromtimestamp(stamp,ZONE).strftime('%m-%d %H:%M:%S') if stamp else '未知'
    return ('【Porsche 晚间充电提醒】\n根据今晚检查取得的车辆数据，Cayenne 尚未插入充电枪。'
            '请记得插枪，以便按计划充电。\n检查时间：'+result['checked_at']+'\n车辆数据时间：'+measured)


class EveningNotifications:
    async def send_evening_notice(self,result,test=False):
        if not test:
            if result.get('plugged') is not False:return
            # Cutover prevents replay of historical reminders into a newly added channel.
            if datetime.fromisoformat(result['checked_at']).timestamp()<self.meta.get('evening_channel_cutover',float('inf')):return
        kind='evening_test:'+str(time.time_ns()) if test else 'evening'
        message=('【通知测试，非车辆实际状态】\n未插枪时会同时向 WhatsApp 和 iPhone 发送中文提醒。'
                 '\n本测试没有查询或操作车辆。') if test else unplugged_message(result)
        await asyncio.gather(
            self.send_notice(message,kind,result['date'],'Porsche 晚间充电提醒'+(' · 测试' if test else '')),
            self.send_whatsapp(message,kind,result['date']))
        self.publish_evening()

    async def send_whatsapp(self,message,kind,date):
        key=date+'|'+kind+'|whatsapp'
        async with self.meta_lock:
            if key in self.meta['notices'] or getattr(self,'notification_disabled',False):return
            self.meta['notices'][key]='已预留，结果未知；不会重复提交'
            try:await self.meta_store.async_save(self.meta)
            except Exception:
                self.notification_disabled=True
                self.meta['notification_disabled']=True
                return
        target=self.value('input_text.porsche_wake_whatsapp_target')
        account=self.value('input_text.porsche_wake_whatsapp_account')
        status='待配置'
        if re.fullmatch(r'\+[1-9][0-9]{7,14}',target or '') and account not in ('','unknown','unavailable'):
            status='WhatsApp 服务不可用'
            if self.hass.services.has_service('whatsapp','send_message'):
                try:
                    async with asyncio.timeout(120):
                        response=await self.hass.services.async_call('whatsapp','send_message',
                            {'account':account,'target':target,'message':message},blocking=True,return_response=True)
                    status=('接口已接受，送达需收件人确认' if isinstance(response,dict) and response.get('success') is True and response.get('message_id')
                            else '返回结果无法确认，不重试')
                except TimeoutError:status='发送超时，送达未知，不重试'
                except Exception:status='发送失败，不重试'
        async with self.meta_lock:
            self.meta['notices'][key]=status
            self.meta['whatsapp_delivery']=status
            try:await self.meta_store.async_save(self.meta)
            except Exception:
                self.notification_disabled=True
                self.meta['notification_disabled']=True
        self.publish_whatsapp()

    def publish_whatsapp(self):
        self.hass.states.async_set('sensor.porsche_wake_whatsapp_notification',self.meta.get('whatsapp_delivery','尚未发送'),
            {'friendly_name':'Porsche WhatsApp 通知','note':'仅未插枪提醒；接口接受不等于送达。集成可能内部重试，外层不重试。'})
