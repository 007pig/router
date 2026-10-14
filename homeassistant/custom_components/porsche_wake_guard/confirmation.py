"""One persistent cached read after an ambiguous real-time query failure."""
import hashlib
import math
import time
from datetime import datetime
from .policy import ZONE


def failure_code(exc):
    response=getattr(exc,'response',None)
    return getattr(exc,'status_code',None) or getattr(exc,'code',None) or getattr(response,'status_code',None)


def summary_advanced(before,after,started,now):
    old=before.get('measurement_timestamps',{}).get('CHARGING_SUMMARY')
    new=after.get('measurement_timestamps',{}).get('CHARGING_SUMMARY')
    valid=lambda x:type(x) in (int,float) and math.isfinite(x)
    return valid(new) and new>started and 0<=now-new<=900 and (old is None or valid(old) and new>old)


class Confirmation:
    async def test_realtime_then_cache(self,call):
        if self.lock.locked() or any(self.ledger.get(k) for k in ('confirmation','pending','observation','evening_job')):
            raise ValueError('Vehicle task in progress')
        async with self.lock:
            if self.failed or self.ledger.get('auth_block'):raise ValueError('Storage or authentication protection active')
            if not call.data.get('override_limits',False):raise ValueError('Explicit test override required')
            before=self.snapshot()
            if not before.get('available') or self.vehicle is None:raise ValueError('Vehicle unavailable')
            now=time.time();date=datetime.fromtimestamp(now,ZONE).date().isoformat()
            old_cooldown=self.ledger.get('blocked_until',0)
            self.ledger.update(pending=True,pending_purpose='manual_test',last_attempt=now,
                validation_count=(self.ledger.get('validation_count',0) if self.ledger.get('validation_date')==date else 0)+1,validation_date=date)
            await self.save()
            job={'purpose':'manual_test','started':now,'before':before,'due':now+300,'end':now+600,
                'state':'waiting','error_category':None,'status_code':None,
                'button':self.value('input_text.porsche_wake_button_entity'),
                'vehicle_fingerprint':hashlib.sha256(self.vehicle.vin.encode()).hexdigest(),
                'approved_cooldown':old_cooldown,'test_id':datetime.fromtimestamp(now,ZONE).isoformat()}
            await self.record('paired_test_realtime_started',purpose='validation',test_id=job['test_id'],before=before)
            try:await self.press_current()
            except Exception as exc:
                code=failure_code(exc);job.update(real_call='异常',error_category=type(exc).__name__,status_code=code if isinstance(code,int) else None)
                if code in (401,403,429):
                    job['cache_exception_type']=type(exc).__name__
                    reason=self.apply_request_failure(exc,time.time());self.ledger.pop('pending_purpose',None)
                    self.ledger['last_confirmation']={**job,'state':'failed','reason':reason};await self.save();self.publish_confirmation();return
            else:job['real_call']='调用成功'
            job['real_returned']=time.time();job['after_realtime']=self.snapshot()
            self.ledger['pending']=False;self.ledger.pop('pending_purpose',None);self.ledger['confirmation']=job
            await self.save()
            await self.record('paired_test_realtime_returned',purpose='validation',test_id=job['test_id'],real_call=job['real_call'],after=job['after_realtime'])
            self.publish_confirmation()

    async def test_confirmation_cache(self,call):
        """Explicit diagnostic: one cached read, never reclassify a historical request."""
        if self.lock.locked() or self.ledger.get('confirmation') or self.ledger.get('pending') or self.ledger.get('observation') or self.ledger.get('evening_job'):
            raise ValueError('Vehicle operation in progress')
        async with self.lock:
            if self.failed or self.ledger.get('auth_block'):raise ValueError('Storage or authentication protection active')
            if time.time()<self.ledger.get('blocked_until',0) and not call.data.get('ignore_cooldown',False):raise ValueError('Cooldown active')
            before=self.snapshot()
            if self.vehicle is None:raise ValueError('Vehicle unavailable')
            job={'button':self.value('input_text.porsche_wake_button_entity'),
                 'vehicle_fingerprint':hashlib.sha256(self.vehicle.vin.encode()).hexdigest()}
            failures=[r for r in self.rows if r.get('result') in ('request_failed_unknown','timeout_unknown') and r.get('slot')]
            source=failures[-1] if failures else None
            source_start=next((r for r in self.rows if source and r.get('slot')==source['slot'] and r.get('result')=='request_started'),None)
            test={'status':'reading','started':time.time(),'before':before,'ignore_cooldown':call.data.get('ignore_cooldown',False),
                  'source_slot':source.get('slot') if source else None,'note':'手动缓存读取测试，不将数小时后的数据改记为原请求五分钟补验成功'}
            self.ledger['confirmation_test']=test;await self.save()
            try:await self.confirmation_cached_read(job)
            except Exception as exc:
                code=failure_code(exc)
                test.update(status='failed',error='缓存读取超时' if isinstance(exc,TimeoutError) else '缓存读取失败',status_code=code if isinstance(code,int) else None)
                if code in (401,403,429):self.apply_request_failure(exc,time.time())
            else:test['status']='success'
            after=self.snapshot();now=time.time()
            test.update(after=after,finished=now,vehicle_data_after_test_started=summary_advanced(before,after,test['started'],now))
            test['source_criterion_met']=summary_advanced(source_start.get('before',{}),after,datetime.fromisoformat(source_start['utc']).timestamp(),now) if source_start else None
            await self.save()
            await self.record('manual_confirmation_cache_test',purpose='validation',test=test)
            self.hass.states.async_set('sensor.porsche_wake_confirmation_test','缓存读取成功' if test['status']=='success' else '缓存读取失败',{'friendly_name':'Porsche 手动缓存补检',**test})

    async def defer_request_failure(self,exc,purpose,before,started,slot=None):
        code=failure_code(exc)
        if code in (401,403,429):return False
        now=time.time()
        job={'purpose':purpose,'before':before,'started':started,'failed_at':now,'due':now+300,
             'end':now+600,'state':'waiting','slot':slot,
             'button':self.value('input_text.porsche_wake_button_entity'),
             'vehicle_fingerprint':hashlib.sha256(self.vehicle.vin.encode()).hexdigest() if self.vehicle is not None else None,
             'error_category':'timeout_unknown' if isinstance(exc,TimeoutError) else 'request_failed_unknown',
             'status_code':code if isinstance(code,int) else None}
        self.ledger['confirmation']=job
        self.ledger['pending']=False;self.ledger.pop('pending_purpose',None)
        if purpose=='validation':self.ledger['validation']['status']='waiting_confirmation'
        await self.save()
        await self.record('request_confirmation_pending',**self.confirmation_context(job),before=before,
                          error_category=job['error_category'],confirmation_due=job['due'])
        self.publish_confirmation()
        return True

    def confirmation_context(self,job):
        if job['purpose']=='manual_test':return {'purpose':'validation','test_id':job['test_id']}
        if job['purpose']=='night':return {'slot':job['slot']}
        if job['purpose']=='evening':return {'purpose':'evening_check','evening_date':self.ledger.get('evening_job',{}).get('date')}
        return {'purpose':'validation','validation_id':self.ledger.get('validation',{}).get('id')}

    def publish_confirmation(self):
        job=self.ledger.get('confirmation') or self.ledger.get('last_confirmation')
        if not job:
            self.hass.states.async_set('sensor.porsche_wake_confirmation','无待补验请求',{'friendly_name':'Porsche 缓存补验'});return
        labels={'waiting':'调用异常，等待缓存补验','reading':'正在读取缓存补验','success':'延迟确认成功','failed':'补验后仍无法确认'}
        if job['purpose']=='manual_test':labels['waiting']='实时请求已结束，等待五分钟缓存测试'
        attrs={'friendly_name':'Porsche 缓存补验',**job,'note':'新车辆测量不证明服务端曾接受请求或请求导致变化'}
        attrs['due_local']=datetime.fromtimestamp(job['due'],ZONE).isoformat()
        self.hass.states.async_set('sensor.porsche_wake_confirmation',labels.get(job['state'],'补验结果待处理'),attrs)

    async def confirmation_maintenance(self,now):
        self.publish_confirmation()
        job=self.ledger.get('confirmation');task=getattr(self,'confirmation_task',None)
        if not job or task and not task.done():return
        if job['state']=='waiting' and now<job['due']:return
        self.confirmation_task=self.hass.async_create_background_task(self.perform_confirmation(),'porsche-cached-confirmation')

    async def confirmation_cached_read(self,job):
        sample=self.snapshot()
        if job['button']!=self.value('input_text.porsche_wake_button_entity') or not sample.get('available') or self.vehicle is None:
            raise ValueError('Vehicle mapping unavailable')
        if not job.get('vehicle_fingerprint') or hashlib.sha256(self.vehicle.vin.encode()).hexdigest()!=job['vehicle_fingerprint']:
            raise ValueError('Vehicle identity changed')
        await self.protected_io(self.vehicle.get_stored_overview,timeout=30)
        self.coordinator.async_update_listeners()

    async def perform_confirmation(self):
        if self.lock.locked():return
        async with self.lock:
            job=self.ledger.get('confirmation')
            if not job:return
            now=time.time()
            reason=None;success=False
            if job['state']=='reading':reason='interrupted_request_unknown'
            elif job['state']=='ready':
                await self.finish_confirmation(job,job['after'],job['confirmed'],job.get('reason'));return
            elif now<job['due']:return
            elif self.failed:reason='storage_unavailable'
            elif self.ledger.get('auth_block'):reason='authentication_required'
            elif now<self.ledger.get('blocked_until',0) and not (job['purpose']=='manual_test' and job.get('approved_cooldown')==self.ledger.get('blocked_until')):reason='failure_cooldown'
            elif self.hass.config.time_zone!='Europe/Dublin':reason='timezone_mismatch'
            elif job['button']!=self.value('input_text.porsche_wake_button_entity'):reason='vehicle_mapping_unavailable'
            elif now<job['end']:
                job['state']='reading';await self.save();self.publish_confirmation()
                try:await self.confirmation_cached_read(job)
                except Exception as exc:
                    job['cache_exception_type']=type(exc).__name__
                    reason=self.apply_request_failure(exc,time.time())
                else:job['cached_read_returned']=True
            else:job['cached_read_skipped']='恢复窗口已过，仅检查现有缓存'
            after=self.snapshot();now=time.time()
            if reason is None:success=summary_advanced(job['before'],after,job['started'],now)
            if not success and reason is None:reason='confirmation_no_new_data'
            job.update(state='ready',after=after,confirmed=success,reason=reason,finished=now)
            await self.save()
            await self.finish_confirmation(job,after,success,reason)

    async def finish_confirmation(self,job,after,success,reason):
        if not success and reason not in ('authentication_required','failure_cooldown','rate_limited','storage_unavailable'):
            # Existing/newer protections are never shortened by a generic failure.
            self.apply_request_failure(RuntimeError('Unconfirmed query'),time.time())
        result='request_delayed_confirmed' if success else 'request_confirmation_failed'
        await self.record(result,**self.confirmation_context(job),before=job['before'],after=after,
                          request_started=job['started'],error_category=job['error_category'],reason=reason)
        self.ledger['last_confirmation']={**job,'state':'success' if success else 'failed'}
        self.ledger.pop('confirmation',None)
        await self.save()
        self.publish_confirmation()
        if job['purpose']=='night':
            if not success:self.notify('实时查询异常，5 分钟缓存补验仍未确认新车辆数据；后续请求已暂停。',reason)
        elif job['purpose']=='evening':
            parent=self.ledger.get('evening_job')
            if parent:
                parent['query_result']='延迟确认成功' if success else '补验后仍无法确认'
                from .evening import evaluate
                check=evaluate(after,time.time())
                if success and time.time()<parent['window_end'] and check['plugged'] is True and check['direct'] is True:
                    await self.disable_direct(parent);after=self.snapshot()
                await self.finish_evening(parent,after,None if success else reason)
        elif job['purpose']=='validation':
            parent=self.ledger.get('validation')
            if parent:
                parent['request_result']='实时调用异常，延迟确认成功' if success else '补验后仍无法确认'
                await self.complete_validation(parent,after,None if success else reason)
