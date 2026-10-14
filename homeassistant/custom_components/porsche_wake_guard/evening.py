"""Evening preparation check. Only one guarded real-time query per local day."""
import math
import time
from datetime import datetime,timedelta
from .policy import ZONE,daily_counts,total_requests
from .mode_evidence import describe

CONNECTED_STATES={'charging','instant_charging','charging_paused','charging_completed'}

NON_DIRECT_MODES={'PROFILE','TIMER','TIMERS','DEPARTURE','DEPARTURES','SCHEDULED','CYCLIC_DEPARTURE'}


def fresh_at(stamp,now):
    return isinstance(stamp,(float,int)) and math.isfinite(stamp) and 0<=now-stamp<=900


def evaluate(sample,now):
    times=sample.get('measurement_timestamps',{})
    summary_fresh=fresh_at(times.get('CHARGING_SUMMARY'),now)
    power_fresh=fresh_at(times.get('CHARGING_RATE'),now)
    power=sample.get('power_kw')
    positive=isinstance(power,(int,float)) and math.isfinite(power) and power>0.1
    active=sample.get('charging_status') in ('charging','instant_charging')
    disconnected=sample.get('charging_status')=='not_plugged'
    plugged=None
    if type(sample.get('plugged')) is bool and fresh_at(sample.get('plugged_timestamp'),now):
        plugged=sample['plugged']
    if summary_fresh and disconnected:plugged=False
    if summary_fresh and power_fresh and active and positive:plugged=True
    explicit=sample.get('plugged') if type(sample.get('plugged')) is bool and fresh_at(sample.get('plugged_timestamp'),now) else None
    conflict=bool(sample.get('contradictory') or (summary_fresh and power_fresh and disconnected and positive)
                  or (explicit is True and summary_fresh and disconnected)
                  or (explicit is False and summary_fresh and sample.get('charging_status') in CONNECTED_STATES)
                  or (summary_fresh and sample.get('charging_status') in ('charging_paused','charging_completed') and positive))
    if conflict:plugged=None
    mode=sample.get('charging_mode')
    switch=sample.get('direct_switch')
    direct=None
    if summary_fresh and mode=='DIRECT' and switch=='on':direct=True
    if summary_fresh and mode in NON_DIRECT_MODES and switch=='off':direct=False
    inferred=(summary_fresh and sample.get('charging_status') in CONNECTED_STATES
              and plugged is None and not conflict)
    reasons=[]
    if plugged is False:reasons.append('检测到充电枪未插入，请检查插枪。')
    elif inferred:reasons.append('依据新鲜充电状态推断已连接；具体充电状态单独显示。')
    elif plugged is None:reasons.append('无法确认充电枪是否插入，请手动确认。')
    if direct is True:reasons.append('当前为 Direct Charging，请检查车辆充电模式。')
    elif direct is None:reasons.append('无法确认充电模式，请手动确认是否为定时充电。')
    return {'plugged':plugged,'plugged_inferred':inferred,'summary_fresh':summary_fresh,
            'data_age_minutes':round((now-times['CHARGING_SUMMARY'])/60,1) if isinstance(times.get('CHARGING_SUMMARY'),(int,float)) and math.isfinite(times['CHARGING_SUMMARY']) and times['CHARGING_SUMMARY']<=now else None,
            'direct':direct,'needs_refresh':plugged is not False and ((plugged is None and not inferred) or direct is None),
            'normal':plugged is True and direct is False,'reasons':reasons}


def refresh_block(ledger,sample,now,failed=False,purpose='evening'):
    if failed:return 'storage_unavailable'
    if ledger.get('confirmation'):return 'confirmation_pending'
    if ledger.get('pending') or ledger.get('observation'):return 'request_busy'
    if ledger.get('auth_block'):return 'authentication_required'
    if now<ledger.get('blocked_until',0):return 'failure_cooldown'
    if now-ledger.get('last_attempt',0)<7200:return 'minimum_interval'
    date=datetime.fromtimestamp(now,ZONE).date().isoformat()
    night,evening=daily_counts(ledger,date)
    if purpose=='evening' and evening>=1:return 'evening_limit'
    if total_requests(ledger,date)>=5:return 'total_daily_limit'
    if not sample.get('available'):return 'button_unavailable'
    return None


def check_window(now,when):
    local=datetime.fromtimestamp(now,ZONE)
    try:
        hour,minute=map(int,when[:5].split(':'))
        for day in (local,local-timedelta(days=1)):
            due=day.replace(hour=hour,minute=minute,second=0,microsecond=0,fold=0).timestamp()
            if due<=now<due+3600:return day.date().isoformat(),due,due+3600
    except (ValueError,TypeError):return None
    # Default 20:00 -> before 21:00. Custom times retain the one-hour window.
    return None


def should_notify(result):
    # Re-evaluate persisted v1.2 results rather than replaying old "unknown" reminders.
    return result.get('plugged') is False


REASONS={
    'storage_unavailable':'持久化或日志不可用，未查询车辆',
    'request_busy':'其他车辆请求或观察尚未完成，未查询车辆',
    'authentication_required':'登录认证失效，无法查询车辆',
    'failure_cooldown':'故障或限流冷却期间，未查询车辆',
    'minimum_interval':'距上次实时请求不足 120 分钟，未查询车辆',
    'evening_limit':'今日晚间实时查询额度已使用',
    'total_daily_limit':'今日实时请求总额度已使用',
    'button_unavailable':'车辆实时查询按钮不可用',
    'timeout_unknown':'实时查询超时，是否送达车辆未知',
    'request_failed_unknown':'实时查询失败，车辆状态无法确认',
    'rate_limited':'Porsche 服务限流，查询已暂停',
    'interrupted_request_unknown':'检查被重启中断，未重复查询车辆',
}


class Evening:
    def publish_evening(self):
        if self.ledger.get('confirmation',{}).get('purpose')=='evening':
            self.hass.states.async_set('sensor.porsche_wake_evening_check','调用异常，等待缓存补验',{'friendly_name':'Porsche 晚间充电准备','confirmation_due':self.ledger['confirmation']['due']})
            return
        from .direct_control import CONTROL_LABELS
        job=self.ledger.get('evening_job',{})
        control=job.get('direct_control',{})
        if control.get('state') in ('closing','verifying'):
            self.hass.states.async_set('sensor.porsche_wake_evening_check',CONTROL_LABELS[control['state']],{
                'friendly_name':'Porsche 晚间充电准备','date':job['date'],'control_state':control['state'],
                'control_label':CONTROL_LABELS[control['state']],'control':control,'notification_result':'处理中'})
            return
        result=self.ledger.get('evening_result')
        if not result:
            self.hass.states.async_set('sensor.porsche_wake_evening_check','等待晚间检查',{'friendly_name':'Porsche 晚间充电准备','control_label':'未执行','control_state':'not_executed'})
            return
        # Re-render old check evidence at its original check time, never as a live reading.
        sample=result.get('snapshot')
        if sample is None:
            rows=getattr(self,'rows',[])
            sample=next((r.get('after') for r in reversed(rows) if r.get('result')=='evening_check_complete' and r.get('evening_date')==result['date']),None)
        display={}
        if sample:
            check=evaluate(sample,datetime.fromisoformat(result['checked_at']).timestamp())
            display=describe(sample,check)
            if check['plugged_inferred'] and result.get('control_state','not_executed')=='not_executed':
                display['label']=display['plugged_label']+' · '+display['charging_label']
                display['message']=display['plugged_label']+'；'+display['charging_label']+'。'+display['direct_label']+'。'+display['inference_note']+'。\n检查时间：'+result['checked_at']
        result={**result,**display}
        notify=should_notify(result)
        delivery=getattr(self,'meta',{}).get('notices',{}).get(result['date']+'|evening','待发送') if notify else '本次无需通知'
        self.hass.states.async_set('sensor.porsche_wake_evening_check',result['label'],{
            'friendly_name':'Porsche 晚间充电准备','control_state':'not_executed','control_label':'未执行',**result,'notify':notify,'notification_result':delivery,'whatsapp_result':getattr(self,'meta',{}).get('notices',{}).get(result['date']+'|evening|whatsapp','尚未发送') if notify else '本次无需通知'})

    async def evening_maintenance(self,now):
        self.publish_evening()
        if self.ledger.get('confirmation'):return
        task=getattr(self,'evening_task',None)
        if task is not None and not task.done():return
        if self.hass.config.time_zone!='Europe/Dublin':return
        job=self.ledger.get('evening_job')
        if job:
            # A persistent unfinished job after restart is never replayed.
            self.evening_task=self.hass.async_create_background_task(self.recover_evening(),'porsche-evening-recovery')
            return
        last=self.ledger.get('evening_result')
        if last and should_notify(last):
            if now<last['window_end']:
                self.hass.async_create_background_task(self.send_evening_notice(last),'porsche-evening-notification')
        if self.value('input_boolean.porsche_wake_evening_enabled')!='on':return
        window=check_window(now,self.value('input_datetime.porsche_wake_evening_time'))
        if window and window[0] not in self.ledger.get('evening_seen',[]):
            self.evening_task=self.hass.async_create_background_task(self.perform_evening(*window),'porsche-evening-check')

    async def recover_evening(self):
        async with self.lock:
            job=self.ledger.get('evening_job')
            if not job:return
            if job.get('direct_control',{}).get('state') in ('closing','verifying'):
                job['direct_control'].update(state='unknown',reason='interrupted_request_unknown')
            elif not job.get('direct_control'):
                original=evaluate(job.get('before',{}),job.get('started',job['due']))
                if original['plugged'] is True and original['direct'] is True:
                    job['direct_control']={'state':'failed','command_sent':False,'reason':'interrupted_before_control'}
            await self.finish_evening(job,job.get('before',{}),reason='interrupted_request_unknown')

    async def perform_evening(self,date,due,end):
        async with self.lock:
            now=time.time()
            if now>=end or self.value('input_boolean.porsche_wake_evening_enabled')!='on':return
            if date in self.ledger.get('evening_seen',[]):return
            sample=self.snapshot()
            job={'date':date,'due':due,'window_end':end,'started':now,'before':sample,'used_refresh':False}
            self.ledger['evening_seen']=(self.ledger.get('evening_seen',[])+[date])[-90:]
            self.ledger['evening_job']=job
            await self.save()
            await self.record('evening_check_started',purpose='evening_check',evening_date=date,before=sample)
            result=evaluate(sample,now)
            reason=None
            if result['needs_refresh']:
                reason=refresh_block(self.ledger,sample,now,self.failed)
                if reason is None:
                    job['used_refresh']=True
                    budget_date=datetime.fromtimestamp(now,ZONE).date().isoformat()
                    self.ledger.update(evening_date=budget_date,evening_count=1,last_attempt=now,pending=True,pending_purpose='evening')
                    await self.save()
                    await self.record('evening_refresh_started',purpose='evening_check',evening_date=date,before=sample)
                    try:await self.press_current()
                    except Exception as exc:
                        if await self.defer_request_failure(exc,'evening',sample,now):return
                        reason=self.apply_request_failure(exc,time.time())
                    else:
                        self.ledger['pending']=False
                        await self.record('evening_refresh_success',purpose='evening_check',evening_date=date)
                    self.ledger.pop('pending_purpose',None)
                    await self.save()
                    sample=self.snapshot()
            check=evaluate(sample,time.time())
            if check['plugged'] is True and check['direct'] is True:
                await self.disable_direct(job)
                sample=self.snapshot()
            await self.finish_evening(job,sample,reason)

    async def finish_evening(self,job,sample,reason=None):
        from .direct_control import CONTROL_LABELS,BLOCK_LABELS
        now=time.time();check=evaluate(sample,now)
        normal=check['normal'] and reason is None
        control=job.get('direct_control',{'state':'not_executed','command_sent':False})
        control_failed=control['state'] in ('failed','unknown')
        notify=check['plugged'] is False
        local=datetime.fromtimestamp(now,ZONE)
        message=[f"{job['date']} 晚间充电准备检查（实际检查 {local.strftime('%m-%d %H:%M:%S')} Dublin）"]
        if now-job['due']>90:message.append('这是本次计划的延迟补检。')
        if check['plugged'] is False:message.append('检测到充电枪未插入，请检查插枪。')
        if control['state']=='confirmed':message.append('新车辆数据已确认关闭 Direct Charging；未修改 Departure Timer。')
        elif control_failed:
            if not control['command_sent']:message.append('未发送关闭命令：'+BLOCK_LABELS.get(control.get('reason'),'保护条件未满足'))
            else:message.append('已尝试关闭 Direct Charging，但关闭失败或结果未知，请手动检查。')
        elif check['plugged_inferred']:message.append('推断已连接；'+describe(sample,check)['charging_label']+'。')
        elif normal:message.append('已确认连接且非 Direct，无需操作。')
        elif check['plugged'] is not False:message.append('状态无法确认，未执行自动关闭；仅记录到面板。')
        details=describe(sample,check)
        message.append(details['direct_label'])
        if reason:message.append(REASONS.get(reason,'本次查询未能完成。'))
        times=sample.get('measurement_timestamps',{})
        stamp=times.get('CHARGING_SUMMARY')
        message.append('充电模式测量时间：'+(datetime.fromtimestamp(stamp,ZONE).strftime('%m-%d %H:%M:%S') if stamp else '未知'))
        if control['state']!='not_executed':message.append('关闭 Direct 不等于确认 Departure Timer 已启用或能按时充电。')
        label=('Direct 已确认关闭' if control['state']=='confirmed' else 'Direct 关闭失败或结果未知' if control_failed
               else '未插充电枪，请检查' if check['plugged'] is False else '检查通过：已连接且非 Direct' if normal
               else details['plugged_label']+' · '+details['charging_label'] if check['plugged_inferred'] else '状态无法确认，未执行关闭')
        result={'date':job['date'],'checked_at':local.isoformat(),'window_end':job['window_end'],
                'label':label,'control_state':control['state'],'control_label':CONTROL_LABELS[control['state']],
                'control':control,'snapshot':sample,**details,'query_result':job.get('query_result'),
                'plugged_inferred':check['plugged_inferred'],
                'plugged':check['plugged'],'direct':check['direct'],'used_refresh':job['used_refresh'],
                'reason':reason,'measurement_timestamps':times,'notify':notify,'message':'\n'.join(message)}
        self.ledger['evening_result']=result
        self.ledger.pop('evening_job',None)
        await self.save()
        await self.record('evening_check_complete',purpose='evening_check',evening_date=job['date'],after=sample,check=result)
        self.publish_evening()
        if result['notify']:
            self.hass.async_create_background_task(self.send_evening_notice(result),'porsche-evening-notification')

    async def evening_notification_test(self,call):
        await self.send_evening_notice({'date':datetime.now(ZONE).date().isoformat()},test=True)
