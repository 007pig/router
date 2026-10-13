"""Conservative, one-shot Direct stop. No start/toggle or timer-setting operations."""
import asyncio
from contextvars import ContextVar
from datetime import datetime
import time
from homeassistant.exceptions import HomeAssistantError
from .evening import evaluate,fresh_at
from .policy import ZONE

CAYENNE_BUTTON='button.cayenne_s_e_hybrid_my24_get_current_vehicle_information'
CAYENNE_DIRECT='switch.cayenne_s_e_hybrid_my24_direct_charging'
COMMAND_RECEIPTS=ContextVar('porsche_direct_receipts',default=None)


class DirectRejected(HomeAssistantError):
    """A sanitized explicit rejection; never contains the server body."""


async def capture_command_receipt(response):
    receipts=COMMAND_RECEIPTS.get()
    if receipts is None or '/commands' not in response.request.url.path:return
    if response.status_code>=400:return
    await response.aread()
    try:result=response.json().get('status',{}).get('result')
    except (ValueError,AttributeError,TypeError):result=None
    receipts.append(result if result in ('ACCEPTED','PERFORMED','ERROR','REJECTED','FAILED','DENIED','UNKNOWN') else 'OTHER')
    if result in ('ERROR','REJECTED','FAILED','DENIED'):
        raise DirectRejected('Direct stop was rejected') from None


def confirmed_off(before,after,started,now):
    previous=before.get('measurement_timestamps',{}).get('CHARGING_SUMMARY')
    stamp=after.get('measurement_timestamps',{}).get('CHARGING_SUMMARY')
    return (isinstance(previous,(int,float)) and fresh_at(stamp,now) and stamp>previous and stamp>=started
            and not after.get('contradictory') and evaluate(after,now)['direct'] is False)


CONTROL_LABELS={'not_executed':'未执行','closing':'正在关闭','verifying':'正在核验关闭结果',
                'confirmed':'已确认关闭','failed':'关闭失败','unknown':'结果未知'}
BLOCK_LABELS={'disabled':'晚间检查已关闭','storage':'持久化或日志不可用','busy':'其他请求或观察未完成',
              'auth':'认证失效','cooldown':'故障或限流冷却中','limit':'今日关闭命令额度已使用',
              'target':'目标开关无法核实为指定 Cayenne','evidence':'插枪或 Direct 条件已无法确认',
              'window':'已超过晚间检查窗口','interrupted_before_control':'检查被重启中断，关闭命令未发送'}


class DirectControl:
    def direct_target(self):
        from homeassistant.helpers import entity_registry as er
        if self.value('input_text.porsche_wake_button_entity')!=CAYENNE_BUTTON:return None
        registry=er.async_get(self.hass)
        button=registry.async_get(CAYENNE_BUTTON);switch=registry.async_get(CAYENNE_DIRECT)
        if not button or not switch:return None
        if (button.platform!='porscheconnect' or switch.platform!='porscheconnect' or button.disabled_by or switch.disabled_by
            or not button.device_id or button.device_id!=switch.device_id
            or not button.unique_id.endswith('-get_current_overview') or not switch.unique_id.endswith('-direct_charging')):return None
        return CAYENNE_DIRECT

    def control_block(self,sample,now,end,reserved=False):
        if self.value('input_boolean.porsche_wake_evening_enabled')!='on':return 'disabled'
        if self.failed:return 'storage'
        if now>=end:return 'window'
        if self.ledger.get('pending') and not (reserved and self.ledger.get('pending_purpose')=='direct_off'):return 'busy'
        if self.ledger.get('observation'):return 'busy'
        if self.ledger.get('auth_block'):return 'auth'
        if now<self.ledger.get('blocked_until',0):return 'cooldown'
        date=datetime.fromtimestamp(now,ZONE).date().isoformat()
        if not reserved and self.ledger.get('direct_off_date')==date and self.ledger.get('direct_off_count',0)>=1:return 'limit'
        if self.direct_target()!=CAYENNE_DIRECT:return 'target'
        check=evaluate(sample,now)
        if not sample.get('available') or check['plugged'] is not True or check['direct'] is not True:return 'evidence'
        return None

    async def disable_direct(self,job):
        before=self.snapshot();now=time.time()
        control={'state':'not_executed','command_sent':False,'before':before,'after':before,'cached_checks':0}
        job['direct_control']=control
        blocked=self.control_block(before,now,job['window_end'])
        if blocked:
            control.update(state='failed',reason=blocked)
            await self.save();return
        self.ledger.update(direct_off_date=datetime.fromtimestamp(now,ZONE).date().isoformat(),direct_off_count=1)
        control.update(state='closing',started=now)
        await self.save() # Reserve the separate command quota before dispatch.
        self.publish_evening()
        before=self.snapshot();blocked=self.control_block(before,time.time(),job['window_end'],reserved=True)
        if blocked:
            control.update(state='failed',reason=blocked)
            await self.save();return
        control.update(before=before,started=time.time())
        control['command_sent']=True # Persist uncertainty before an external side effect can occur.
        self.ledger.update(pending=True,pending_purpose='direct_off')
        await self.save()
        await self.record('direct_off_started',purpose='evening_check',evening_date=job['date'],before=before)
        # A final check after all awaited persistence operations prevents stale UI changes from dispatching.
        blocked=self.control_block(self.snapshot(),time.time(),job['window_end'],reserved=True)
        if blocked:
            control.update(state='failed',reason=blocked,command_sent=False)
            self.ledger['pending']=False;self.ledger.pop('pending_purpose',None)
            await self.save();return
        try:
            receipts=[];token=COMMAND_RECEIPTS.set(receipts)
            try:
                await self.direct_service_off()
                control['command_status']=receipts[-1] if receipts else 'UNKNOWN'
                if control['command_status'] in ('ERROR','REJECTED','FAILED','DENIED'):raise DirectRejected('Direct stop was rejected')
            finally:
                control['command_status_receipts']=list(receipts)
                COMMAND_RECEIPTS.reset(token)
        except Exception as exc:
            control['command_status']=receipts[-1] if receipts else 'UNKNOWN'
            rejected=isinstance(exc,DirectRejected) or control['command_status'] in ('ERROR','REJECTED','FAILED','DENIED')
            control.update(state='failed' if rejected else 'unknown',reason=self.apply_request_failure(exc,time.time()))
            self.ledger.pop('pending_purpose',None)
            await self.save()
            await self.record('direct_off_failed',purpose='evening_check',evening_date=job['date'],control_state=control['state'],reason=control['reason'])
            return
        self.ledger['pending']=False;self.ledger.pop('pending_purpose',None)
        control.update(state='verifying',returned=time.time())
        await self.save()
        self.publish_evening()
        await self.record('direct_off_returned',purpose='evening_check',evening_date=job['date'],command_status=control['command_status'],command_status_receipts=control['command_status_receipts'])
        for offset in (0,30,120):
            if offset:
                await asyncio.sleep(max(0,control['returned']+offset-time.time()))
                if self.value('input_boolean.porsche_wake_evening_enabled')!='on':break
                if self.direct_target()!=CAYENNE_DIRECT:break
                if self.ledger.get('auth_block') or time.time()<self.ledger.get('blocked_until',0):break
                control['cached_checks']+=1
                await self.save()
                try:await self.direct_cached_read()
                except Exception as exc:
                    control.update(state='unknown',reason=self.apply_request_failure(exc,time.time()))
                    await self.save();return
            after=self.snapshot();control['after']=after
            await self.record('direct_off_verification',purpose='evening_check',evening_date=job['date'],offset=offset,after=after)
            if confirmed_off(control['before'],after,control['started'],time.time()):
                control['state']='confirmed'
                await self.save();return
        control.update(state='unknown',reason='not_confirmed')
        await self.save()
