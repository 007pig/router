"""Local reports and notifications; dispatches the separately guarded evening job."""
import asyncio
import hashlib
import time
from pathlib import Path
from datetime import datetime,timedelta,timezone
from homeassistant.helpers.storage import Store
from homeassistant.components import persistent_notification
from .policy import ZONE,daily_counts
from .evidence import classify,night_report,epoch

DOMAIN='porsche_wake_guard'


from .evening_notifications import EveningNotifications

class Runtime(EveningNotifications):
    async def runtime_start(self,event=None):
        from homeassistant.helpers.event import async_track_time_interval
        self.meta_store=Store(self.hass,1,DOMAIN+'_reports',private=True,atomic_writes=True)
        marker=Path(self.hass.config.path('.porsche_wake_reports_initialized'))
        try:loaded=await self.meta_store.async_load()
        except Exception:loaded=None
        self.notification_disabled=bool(loaded and loaded.get('notification_disabled')) or (loaded is None and await self.hass.async_add_executor_job(marker.exists))
        self.meta=loaded or {'notices':{},'armed':{},'nights':{}}
        if self.notification_disabled:
            self.meta['notification_disabled']=True
            self.meta['settings_initialized']=True
            persistent_notification.async_create(self.hass,'通知去重记录不可用，手机推送已暂停；车辆唤醒规则保持。请检查持久化文件。',title='Porsche 通知状态异常',notification_id=DOMAIN+'_notification_storage')
        self.meta.setdefault('evening_channel_cutover',time.time())
        await self.meta_store.async_save(self.meta)
        self.meta_lock=asyncio.Lock()
        self.maintenance_lock=asyncio.Lock()
        if not self.meta.get('settings_initialized'):
            for key,value in (('departure_time','08:00:00'),('summary_time','08:05:00')):
                await self.hass.services.async_call('input_datetime','set_datetime',{'entity_id':'input_datetime.porsche_wake_'+key,'time':value},blocking=True)
            targets=[name for name in self.hass.services.async_services().get('notify',{}) if name.startswith('mobile_app_')]
            if len(targets)==1:
                await self.hass.services.async_call('input_text','set_value',{'entity_id':'input_text.porsche_wake_notify_service','value':'notify.'+targets[0]},blocking=True)
            self.meta['settings_initialized']=True
            await self.meta_store.async_save(self.meta)
        if not self.notification_disabled:
            await self.hass.async_add_executor_job(marker.touch)
        if not self.meta.get('evening_initialized'):
            await self.hass.services.async_call('input_datetime','set_datetime',{'entity_id':'input_datetime.porsche_wake_evening_time','time':'20:00:00'},blocking=True)
            await self.hass.services.async_call('input_boolean','turn_on',{'entity_id':'input_boolean.porsche_wake_evening_enabled'},blocking=True)
            self.meta['evening_initialized']=True
            await self.meta_store.async_save(self.meta)
        try:self.rows=await self.hass.async_add_executor_job(self.audit.read)
        except Exception:
            self.failed=True
            self.notify('审计日志无法读取，已停止唤醒。请检查日志文件。','audit_unreadable')
            return
        night_rows=[r for r in self.rows if r.get('purpose')!='evening_check']
        if night_rows:
            last=night_rows[-1];self.last_recorded=last['utc']
            self.publish(last['result'],**{k:v for k,v in last.items() if k not in ('utc','vehicle','result','request_id')})
        async_track_time_interval(self.hass,self.maintenance,timedelta(seconds=30))
        await self.maintenance()
        if self.ledger.get('observation'):
            self.hass.async_create_background_task(self.resume_observation(),'porsche-observation-recovery')

    def schedule(self):
        times=[]
        for i in range(1,6):
            t=self.value(f'input_datetime.porsche_wake_time_{i}')[:5]
            if self.value(f'input_boolean.porsche_wake_slot_{i}')=='on' and len(t)==5 and t[2]==':':times.append(t)
        return sorted(set(times))

    def notify(self,message,code=None):
        code=code or hashlib.sha256(message.encode()).hexdigest()[:16]
        if not hasattr(self,'meta_lock'):
            persistent_notification.async_create(self.hass,message,title='Porsche 定时唤醒',notification_id=DOMAIN)
            return
        self.hass.async_create_background_task(self.send_notice(message,'fault:'+code),'porsche-notification')

    def notification_target(self):
        target=self.value('input_text.porsche_wake_notify_service').removeprefix('notify.')
        return target if target.startswith('mobile_app_') and self.hass.services.has_service('notify',target) else None

    async def send_notice(self,message,kind,date=None,title='Porsche 定时唤醒'):
        date=date or datetime.now(ZONE).date().isoformat()
        key=date+'|'+kind
        tag=DOMAIN+'_'+hashlib.sha256(key.encode()).hexdigest()[:16]
        async with self.meta_lock:
            if key in self.meta['notices']:return
            self.meta['notices'][key]='reserved'
            if kind.startswith('fault:'):self.meta['last_fault']=kind
            try:await self.meta_store.async_save(self.meta)
            except Exception:
                self.notification_disabled=True
                self.meta['notification_disabled']=True
                persistent_notification.async_create(self.hass,message+'\n通知去重记录无法保存，未发送手机推送。',title=title,notification_id=tag)
                return
        persistent_notification.async_create(self.hass,message,title=title,notification_id=tag)
        target=None if getattr(self,'notification_disabled',False) else self.notification_target()
        status='待配置' if target is None else '接口已接受，送达需手机确认'
        if target:
            notification_data={'url':'/porsche-wake/cayenne','tag':tag,'group':'porsche_wake'}
            if kind=='evening' or kind.startswith('evening_test:'):
                notification_data['push']={'interruption-level':'time-sensitive'}
            try:
                async with asyncio.timeout(15):
                    await self.hass.services.async_call('notify',target,{'title':title,'message':message,
                        'data':notification_data},blocking=True)
            except Exception:
                status='手机推送失败'
                persistent_notification.async_create(self.hass,'iPhone 推送失败，报告已保留在 HA 通知和面板。',
                    title='Porsche 通知通道',notification_id=DOMAIN+'_delivery')
        async with self.meta_lock:
            self.meta['notices'][key]=status
            self.meta['delivery']=status
            self.meta['delivery_at']=datetime.now(timezone.utc).isoformat()
            try:await self.meta_store.async_save(self.meta)
            except Exception:
                self.notification_disabled=True
                self.meta['notification_disabled']=True
        self.hass.states.async_set('sensor.porsche_wake_notification',status,{'friendly_name':'Porsche 手机通知','last_attempt':self.meta['delivery_at']})

    async def notification_test(self,call):
        await self.send_notice('这是一条通知通道测试，没有发送车辆唤醒请求。点击打开 Porsche 面板。',
                               'test:'+str(int(time.time())),title='Porsche 通知测试')

    async def confirm_night(self,call):
        date=call.data['date'];datetime.strptime(date,'%Y-%m-%d')
        if date>datetime.now(ZONE).date().isoformat():raise ValueError('Cannot confirm a future night')
        async with self.meta_lock:
            departure=self.value('input_datetime.porsche_wake_departure_time')[:5]
            self.meta['nights'][date]={'plugged':call.data['plugged'],'no_intervention':call.data['no_intervention'],
                                     'departure':departure if len(departure)==5 else '08:00','target':self.number('target_soc',100)}
            await self.meta_store.async_save(self.meta)
        await self.maintenance(allow_evening=False)

    async def refresh_report(self,call):
        await self.maintenance(allow_evening=False)

    async def maintenance(self,event=None,allow_evening=True):
        if not hasattr(self,'maintenance_lock') or self.maintenance_lock.locked():return
        async with self.maintenance_lock:
            now=time.time();local=datetime.fromtimestamp(now,ZONE);date=local.date().isoformat()
            snapshot=self.snapshot();self.publish_power(snapshot)
            if self.last_recorded:
                state=self.hass.states.get('sensor.porsche_wake_result')
                if state:
                    attrs=dict(state.attributes);attrs['today_attempts']=self.ledger.get('count',0) if self.ledger.get('date')==date else 0
                    self.hass.states.async_set('sensor.porsche_wake_result',state.state,attrs)
            enabled=self.value('input_boolean.porsche_wake_enabled')=='on' and self.value('automation.porsche_wake_scheduler')=='on'
            times=self.schedule()
            next_slots=[datetime.fromisoformat((local+timedelta(days=day)).date().isoformat()+'T'+t).replace(tzinfo=ZONE)
                        for day in (0,1) for t in times]
            next_slot=next((d for d in sorted(next_slots) if d.timestamp()>now and d.strftime('%Y-%m-%d|%H:%M') not in self.ledger['seen']),None)
            pause='持久化或日志异常' if self.failed else '需要重新认证' if self.ledger.get('auth_block') else '冷却暂停中' if now<self.ledger.get('blocked_until',0) else '已关闭' if not enabled else '无'
            stamp=snapshot.get('vehicle_timestamp')
            self.hass.states.async_set('sensor.porsche_wake_health','运行正常' if pause=='无' else pause,{
                'friendly_name':'Porsche 运行状态','next_slot':next_slot.isoformat() if next_slot and enabled else None,
                'today_attempts':self.ledger.get('count',0) if self.ledger.get('date')==date else 0,
                'evening_attempts':self.ledger.get('evening_count',0) if self.ledger.get('evening_date')==date else 0,
                'direct_off_attempts':self.ledger.get('direct_off_count',0) if self.ledger.get('direct_off_date')==date else 0,
                'total_attempts':sum(daily_counts(self.ledger,date)),
                'vehicle_time':datetime.fromtimestamp(stamp,ZONE).isoformat() if stamp else None,
                'data_age_minutes':round((now-stamp)/60,1) if stamp and stamp<=now else None,
                'pause_reason':pause,'observation_in_progress':bool(self.ledger.get('observation'))})
            # Detect missing schedule records independently of the wake automation's execution.
            missed=[]
            async with self.meta_lock:
                for t in times:
                    key=date+'|'+t;at=datetime.fromisoformat(date+'T'+t).replace(tzinfo=ZONE).timestamp()
                    if at>now:
                        if enabled:self.meta['armed'][key]=at
                        else:self.meta['armed'].pop(key,None)
                seen={r.get('slot') for r in self.rows if r['result'] not in ('one_off_scheduled','schedule_missed')}
                for key,at in list(self.meta['armed'].items()):
                    if now>=at+120:
                        if key not in seen:missed.append(key)
                        self.meta['armed'].pop(key,None)
                self.meta['notices']={k:v for k,v in self.meta['notices'].items() if k[:10]>=(local-timedelta(days=90)).date().isoformat()}
                await self.meta_store.async_save(self.meta)
            for key in missed:self.notify(f'{key} 已启用的计划没有执行或跳过记录。请检查 HA/自动化是否曾离线；不会补发唤醒。','schedule_missed:'+key)
            departure=self.value('input_datetime.porsche_wake_departure_time')[:5]
            if len(departure)!=5 or departure[2]!=':':departure='08:00'
            report=night_report(self.rows,date,departure,self.number('target_soc',100),times)
            items=report['items']
            effect_items=items
            if not effect_items:
                past=sorted({r.get('slot','')[:10] for r in self.rows if r.get('slot') and r['result']=='request_started'})
                if past:effect_items=night_report(self.rows,past[-1],departure,self.number('target_soc',100))['items']
            if effect_items:
                requests={k:v for k,v in effect_items.items() if v['request_time'] is not None}
                key=next(reversed(requests or effect_items))
                latest=effect_items[key]
                self.hass.states.async_set('sensor.porsche_wake_effect',latest['effect'],{
                    'friendly_name':'Porsche 最近请求效果',**latest,'slot':key,
                    'causality':'观察到变化不等于证明请求导致变化'})
            lines=[]
            for key,item in items.items():
                b,a=item['before'],item['after']
                fmt=lambda v:'未知' if v is None else str(v)
                measured=lambda s:datetime.fromtimestamp(s['vehicle_timestamp'],ZONE).strftime('%m-%d %H:%M:%S') if s.get('vehicle_timestamp') else '未知'
                lines.append(f"**{key.split('|')[1]}** · {item['request']} · {item['response']} · {item['effect']}\n\nSOC {fmt(b.get('soc'))} → {fmt(a.get('soc'))}% ｜ 功率 {fmt(b.get('power_kw'))} → {fmt(a.get('power_kw'))} kW\n\n车辆测量：{measured(b)} → {measured(a)}")
            self.hass.states.async_set('sensor.porsche_wake_timeline',date,{'friendly_name':'Porsche 当晚时间线','markdown':'\n\n---\n\n'.join(lines) or '当晚暂无执行记录。'})
            eligible=[]
            for night,confirmation in sorted(self.meta['nights'].items()):
                if not all(confirmation.get(k) is True for k in ('plugged','no_intervention')):continue
                r=night_report(self.rows,night,confirmation.get('departure',departure),confirmation.get('target',100))
                if any(isinstance(x['before'].get('soc'),(int,float)) and x['before']['soc']<confirmation.get('target',100) for x in r['items'].values()):
                    eligible.append({'date':night,'requests':r['requests'],'responses':sum(x['response']=='取得车辆新数据' for x in r['items'].values()),'resumption_observed':any(x['effect']=='观察到暂停后开始充电' for x in r['items'].values()),'completion':r['completion']})
            self.hass.states.async_set('sensor.porsche_wake_trial',f'{len(eligible)}/7 个有效充电夜',{'friendly_name':'Porsche 观察样本','nights':eligible[-7:],'note':'需确认插枪、无人工干预且有充电需求；不会自动调整时间'})
            when=self.value('input_datetime.porsche_wake_summary_time')[:5]
            if len(when)!=5 or when[2]!=':':when='08:05'
            due=datetime.fromisoformat(date+'T'+when).replace(tzinfo=ZONE).timestamp()
            if due<=now and local.hour<12:
                if self.meta.get('summary',{}).get('date')!=date:
                    # Capture a read-only cache sample; never fetch additional vehicle data.
                    await self.record('summary_snapshot',snapshot=snapshot)
                    report=night_report(self.rows,date,departure,self.number('target_soc',100),times)
                    report['delayed']=now-due>90
                    async with self.meta_lock:
                        self.meta['summary']=report
                        await self.meta_store.async_save(self.meta)
                summary=self.meta['summary']
                if summary['has_records']:
                    self.hass.async_create_background_task(self.send_notice(('延迟汇总\n' if summary.get('delayed') else '')+summary['message'],'summary',date,'Porsche 晨间摘要'),'porsche-summary-notification')
            summary=self.meta.get('summary')
            self.hass.states.async_set('sensor.porsche_wake_night_summary',summary['date'] if summary else '等待晨间汇总',{
                'friendly_name':'Porsche 最近一晚摘要','message':summary['message'] if summary else '每天本地时间 08:05 汇总。',
                'completion':summary['completion'] if summary else None})
            delivery='通知存储异常，推送暂停' if getattr(self,'notification_disabled',False) else self.meta.get('delivery','已配置，尚未发送') if self.notification_target() else '待配置'
            self.hass.states.async_set('sensor.porsche_wake_notification',delivery,{'friendly_name':'Porsche 手机通知','last_attempt':self.meta.get('delivery_at')})
            if self.meta.get('pruned')!=date:
                await self.hass.async_add_executor_job(self.audit.prune,now)
                self.rows=await self.hass.async_add_executor_job(self.audit.read)
                async with self.meta_lock:
                    self.meta['pruned']=date
                    await self.meta_store.async_save(self.meta)
            self.publish_whatsapp()
            if allow_evening:await self.evening_maintenance(now)
            else:self.publish_evening()
