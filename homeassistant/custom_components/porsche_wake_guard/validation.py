"""Durable one-off, read-only vehicle validation; never invokes control services."""
import asyncio
from datetime import datetime
import time
from .policy import ZONE
from .evening import evaluate,refresh_block,REASONS
from .mode_evidence import describe

VALIDATION_REASONS={'validation_limit':'今日验收查询额度已使用','timezone_mismatch':'HA 时区不是 Europe/Dublin','validation_window_expired':'已超过验收执行窗口'}

LABELS={'waiting_confirmation':'调用异常，等待缓存补验','scheduled':'等待一次性验收','running':'正在验收','unplugged':'已确认未插枪',
        'connected':'未发现未插枪','incomplete':'本次验收未完成','missed':'错过验收',
        'unknown':'验收被重启中断，结果未知','cancelled':'已取消'}

def validation_policy_ledger(ledger,job,rows):
    """Apply explicit, per-job exceptions to a copy; never clear live protection."""
    policy=dict(ledger)
    if job.get('override_limits'):
        policy.update(last_attempt=0,count=0,evening_count=0,validation_count=0)
    approved=job.get('approved_unknown_cooldown_until')
    if approved and approved==ledger.get('blocked_until') and not ledger.get('auth_block'):
        failure=None
        for row in reversed(rows):
            code=row.get('reason') or row.get('result')
            if code in ('request_failed_unknown','timeout_unknown','rate_limited','authentication_required','cached_read_failed','interrupted_request_unknown'):
                failure=code;break
            if row.get('result')=='validation_complete' and row.get('validation',{}).get('reason') in ('rate_limited','authentication_required'):
                failure=row['validation']['reason'];break
        if failure in ('request_failed_unknown','timeout_unknown'):policy['blocked_until']=0
    return policy

class Validation:
    async def schedule_validation(self,call):
        dt=datetime.fromisoformat(call.data['at'])
        if dt.tzinfo is None:raise ValueError('Execution time must include timezone')
        due=dt.timestamp()
        if due<=time.time():raise ValueError('Execution time must be in the future')
        if self.hass.config.time_zone!='Europe/Dublin':raise ValueError('Europe/Dublin required')
        async with self.lock:
            old=self.ledger.get('validation',{})
            if old.get('status') in ('running','waiting_confirmation'):raise ValueError('Validation is already running')
            key=dt.astimezone(ZONE).isoformat()
            if old.get('id')==key:return
            if key in self.ledger.get('validation_seen',[]):raise ValueError('Validation already attempted')
            self.ledger['validation']={'id':key,'due':due,'end':due+300,'status':'scheduled',
                'date':dt.astimezone(ZONE).date().isoformat(),'used_refresh':False,
                'override_limits':call.data.get('override_limits',False),
                'approved_unknown_cooldown_until':call.data.get('approved_unknown_cooldown_until')}
            await self.record('validation_scheduled',purpose='validation',validation_id=key,
                override_limits=call.data.get('override_limits',False),approved_unknown_cooldown_until=call.data.get('approved_unknown_cooldown_until'))
            await self.save()
        self.publish_validation()

    async def cancel_validation(self,call):
        if self.lock.locked():raise ValueError('Vehicle operation in progress; cannot cancel now')
        async with self.lock:
            job=self.ledger.get('validation')
            if job and job['status']=='scheduled':
                job['status']='cancelled';await self.save()
        self.publish_validation()

    def publish_validation(self):
        job=self.ledger.get('validation',{})
        attrs={'friendly_name':'Porsche 一次性验收',**job}
        if job:
            for name in ('before','after'):
                sample=job.get(name,{})
                attrs[name+'_status']=sample.get('charging_status')
                attrs[name+'_soc']=sample.get('soc')
                stamp=sample.get('measurement_timestamps',{}).get('CHARGING_SUMMARY')
                attrs[name+'_measured_at']=datetime.fromtimestamp(stamp,ZONE).isoformat() if isinstance(stamp,(int,float)) else None
            key=job['date']+'|validation:'+job['id']
            notices=getattr(self,'meta',{}).get('notices',{})
            attrs['iphone_result']=notices.get(key,'尚未发送' if job.get('notify') else '无需通知')
            attrs['whatsapp_result']=notices.get(key+'|whatsapp','尚未发送' if job.get('notify') else '无需通知')
        self.hass.states.async_set('sensor.porsche_wake_validation',LABELS.get(job.get('status'),'未安排验收'),attrs)

    async def validation_maintenance(self,now):
        self.publish_validation()
        if self.ledger.get('confirmation'):return
        task=getattr(self,'validation_task',None)
        if task and not task.done():return
        job=self.ledger.get('validation')
        if not job:return
        if job['status']=='running':
            job.update(status='unknown',notify=False,reason='interrupted_request_unknown')
            await self.save();self.publish_validation();return
        if job.get('notify') and now<job['end']:
            self.hass.async_create_background_task(self.validation_notice(dict(job)),'porsche-validation-notice')
        if job['status']=='scheduled' and now>=job['due']:
            self.validation_task=self.hass.async_create_background_task(self.perform_validation(),'porsche-validation')

    async def perform_validation(self):
        job=self.ledger['validation'];now=time.time()
        if job['status']!='scheduled':return
        if now>=job['end']:
            job.update(status='missed',notify=False);await self.save();self.publish_validation();return
        if self.lock.locked():
            job.update(status='incomplete',reason='request_busy',notify=False);await self.save();self.publish_validation();return
        async with self.lock:
            if job['status']!='scheduled':return
            job.update(status='running',started=now)
            self.ledger['validation_seen']=(self.ledger.get('validation_seen',[])+[job['id']])[-180:]
            await self.save()
            before=self.snapshot();job['before']=before
            await self.record('validation_started',purpose='validation',validation_id=job['id'],before=before)
            check=evaluate(before,now)
            # This path needs only connection evidence, not Direct mode knowledge.
            sufficient=check['plugged'] is not None or check['plugged_inferred']
            reason=None
            if not sufficient:
                now=time.time()
                policy=validation_policy_ledger(self.ledger,job,self.rows)
                reason=refresh_block(policy,before,now,self.failed,purpose='validation')
                date=datetime.fromtimestamp(now,ZONE).date().isoformat()
                if not job.get('override_limits') and self.ledger.get('validation_date')==date and self.ledger.get('validation_count',0)>=1:reason='validation_limit'
                if now>=job['end']:reason='validation_window_expired'
                if self.hass.config.time_zone!='Europe/Dublin':reason='timezone_mismatch'
                if reason is None:
                    attempts=self.ledger.get('validation_count',0) if self.ledger.get('validation_date')==date else 0
                    self.ledger.update(validation_date=date,validation_count=attempts+1,last_attempt=now,pending=True,pending_purpose='validation')
                    job.update(used_refresh=True,request_started=now)
                    await self.save()
                    try:await self.press_current()
                    except Exception as exc:
                        if await self.defer_request_failure(exc,'validation',before,now):return
                        reason=self.apply_request_failure(exc,time.time())
                    else:job['request_result']='调用成功';self.ledger['pending']=False
                    self.ledger.pop('pending_purpose',None)
                    await self.save()
            await self.complete_validation(job,self.snapshot(),reason)

    async def complete_validation(self,job,after,reason):
        now=time.time();check=evaluate(after,now)
        previous=job['before'].get('measurement_timestamps',{}).get('CHARGING_SUMMARY')
        stamp=after.get('measurement_timestamps',{}).get('CHARGING_SUMMARY')
        new_data=bool(job.get('request_started') and isinstance(stamp,(int,float)) and
                      stamp>job['request_started'] and stamp<=now and
                      (previous is None or stamp>previous))
        status=('unplugged' if check['plugged'] is False else 'connected' if check['plugged'] is True or check['plugged_inferred'] else 'incomplete')
        if reason:status='incomplete'
        job.update(status=status,finished=datetime.fromtimestamp(now,ZONE).isoformat(),after=after,
            reason=reason,reason_text=REASONS.get(reason,VALIDATION_REASONS.get(reason,reason)),vehicle_response='取得请求后的新车辆测量' if new_data else '未验证请求后的车辆响应' if job['used_refresh'] else '仅使用现有缓存',
            notify=status=='unplugged',**describe(after,check))
        if reason and job['used_refresh']:job['request_result']='失败或结果未知'
        await self.save()
        await self.record('validation_complete',purpose='validation',validation_id=job['id'],validation=dict(job))
        self.publish_validation()
        if job['notify']:self.hass.async_create_background_task(self.validation_notice(dict(job)),'porsche-validation-notice')

    async def validation_notice(self,job):
        if not job.get('notify') or job['status']!='unplugged':return
        stamp=job['after'].get('measurement_timestamps',{}).get('CHARGING_SUMMARY')
        scheduled=datetime.fromtimestamp(job['due'],ZONE).strftime('%H:%M')
        measured=datetime.fromtimestamp(stamp,ZONE).isoformat() if stamp else '未知'
        message=f'【Porsche {scheduled} 一次性验收】\n新鲜车辆数据确认未插入充电枪。此次为约定的验收检查，行车期间无需处理。\n检查时间：{job["finished"]}\n车辆测量时间：{measured}\n系统未修改车辆充电设置。'
        kind='validation:'+job['id']
        await asyncio.gather(self.send_notice(message,kind,job['date'],'Porsche 一次性验收'),self.send_whatsapp(message,kind,job['date']))
        self.publish_validation()
