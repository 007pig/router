"""Evening preparation check. Only one guarded real-time query per local day."""
import math
import time
from datetime import datetime,timedelta
from .policy import ZONE,daily_counts

NON_DIRECT_MODES={'PROFILE','TIMER','TIMERS','DEPARTURE','DEPARTURES','SCHEDULED'}


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
    if sample.get('plugged') in (True,False) and fresh_at(sample.get('plugged_timestamp'),now):
        plugged=sample['plugged']
    if summary_fresh and disconnected:plugged=False
    if summary_fresh and power_fresh and active and positive:plugged=True
    if sample.get('contradictory') or (summary_fresh and power_fresh and disconnected and positive):plugged=None
    mode=sample.get('charging_mode')
    switch=sample.get('direct_switch')
    direct=None
    if summary_fresh and mode=='DIRECT' and switch=='on':direct=True
    if summary_fresh and mode in NON_DIRECT_MODES and switch=='off':direct=False
    reasons=[]
    if plugged is False:reasons.append('检测到充电枪未插入，请检查插枪。')
    elif plugged is None:reasons.append('无法确认充电枪是否插入，请手动确认。')
    if direct is True:reasons.append('当前为 Direct Charging，请检查车辆充电模式。')
    elif direct is None:reasons.append('无法确认充电模式，请手动确认是否为定时充电。')
    return {'plugged':plugged,'direct':direct,'needs_refresh':plugged is None or direct is None,
            'normal':plugged is True and direct is False,'reasons':reasons}


def refresh_block(ledger,sample,now,failed=False):
    if failed:return 'storage_unavailable'
    if ledger.get('pending') or ledger.get('observation'):return 'request_busy'
    if ledger.get('auth_block'):return 'authentication_required'
    if now<ledger.get('blocked_until',0):return 'failure_cooldown'
    if now-ledger.get('last_attempt',0)<7200:return 'minimum_interval'
    date=datetime.fromtimestamp(now,ZONE).date().isoformat()
    night,evening=daily_counts(ledger,date)
    if evening>=1:return 'evening_limit'
    if night+evening>=5:return 'total_daily_limit'
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
        result=self.ledger.get('evening_result')
        if not result:
            self.hass.states.async_set('sensor.porsche_wake_evening_check','等待晚间检查',{'friendly_name':'Porsche 晚间充电准备'})
            return
        delivery=getattr(self,'meta',{}).get('notices',{}).get(result['date']+'|evening','待发送') if result['notify'] else '正常，不发送通知'
        self.hass.states.async_set('sensor.porsche_wake_evening_check',result['label'],{
            'friendly_name':'Porsche 晚间充电准备',**result,'notification_result':delivery})

    async def evening_maintenance(self,now):
        self.publish_evening()
        task=getattr(self,'evening_task',None)
        if task is not None and not task.done():return
        if self.hass.config.time_zone!='Europe/Dublin':return
        job=self.ledger.get('evening_job')
        if job:
            # A persistent unfinished job after restart is never replayed.
            self.evening_task=self.hass.async_create_background_task(self.recover_evening(),'porsche-evening-recovery')
            return
        last=self.ledger.get('evening_result')
        if last and last['notify']:
            if now<last['window_end']:
                self.hass.async_create_background_task(self.send_notice(last['message'],'evening',last['date'],'Porsche 晚间充电检查'),'porsche-evening-notification')
        if self.value('input_boolean.porsche_wake_evening_enabled')!='on':return
        window=check_window(now,self.value('input_datetime.porsche_wake_evening_time'))
        if window and window[0] not in self.ledger.get('evening_seen',[]):
            self.evening_task=self.hass.async_create_background_task(self.perform_evening(*window),'porsche-evening-check')

    async def recover_evening(self):
        async with self.lock:
            job=self.ledger.get('evening_job')
            if not job:return
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
                    except Exception as exc:reason=self.apply_request_failure(exc,time.time())
                    else:
                        self.ledger['pending']=False
                        await self.record('evening_refresh_success',purpose='evening_check',evening_date=date)
                    self.ledger.pop('pending_purpose',None)
                    await self.save()
                    sample=self.snapshot()
            await self.finish_evening(job,sample,reason)

    async def finish_evening(self,job,sample,reason=None):
        now=time.time();check=evaluate(sample,now)
        normal=check['normal'] and reason is None
        local=datetime.fromtimestamp(now,ZONE)
        message=[f"{job['date']} 晚间充电准备检查（实际检查 {local.strftime('%m-%d %H:%M:%S')} Dublin）"]
        if now-job['due']>90:message.append('这是本次计划的延迟补检。')
        message.extend(check['reasons'] or ['已确认充电设备连接，且非 Direct Charging。'])
        if reason:message.append(REASONS.get(reason,'检查未能完成，请手动确认。'))
        times=sample.get('measurement_timestamps',{})
        stamp=times.get('CHARGING_SUMMARY')
        message.append('充电模式测量时间：'+(datetime.fromtimestamp(stamp,ZONE).strftime('%m-%d %H:%M:%S') if stamp else '未知'))
        message.append('系统只检查和提醒，未修改车辆设置。')
        result={'date':job['date'],'checked_at':local.isoformat(),'window_end':job['window_end'],
                'label':'检查通过：已连接且非 Direct' if normal else '请检查晚间充电准备',
                'plugged':check['plugged'],'direct':check['direct'],'used_refresh':job['used_refresh'],
                'reason':reason,'measurement_timestamps':times,'notify':not normal,'message':'\n'.join(message)}
        self.ledger['evening_result']=result
        self.ledger.pop('evening_job',None)
        await self.save()
        await self.record('evening_check_complete',purpose='evening_check',evening_date=job['date'],after=sample,check=result)
        self.publish_evening()
        if result['notify']:
            self.hass.async_create_background_task(self.send_notice(result['message'],'evening',job['date'],'Porsche 晚间充电检查'),'porsche-evening-notification')

    async def evening_notification_test(self,call):
        await self.send_notice('【格式测试，不是车辆实际状态】\n检测到未插入充电枪，并且当前为 Direct Charging。请检查插枪及车辆充电模式。\n此测试未查询车辆、未修改车辆设置。',
            'evening_test:'+str(int(time.time())),title='Porsche 晚间充电检查 · 测试')
