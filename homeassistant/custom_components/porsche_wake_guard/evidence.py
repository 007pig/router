"""Pure evidence classification. Record times never replace measurement times."""
from datetime import datetime
from .policy import ZONE

FAILURES = {'authentication_required','rate_limited','timeout_unknown',
            'request_failed_unknown','interrupted_request_unknown'}
SKIPS = {'unplugged','target_reached','already_charging','minimum_interval',
         'daily_limit','failure_cooldown','button_unavailable','previous_request_unknown'}


def epoch(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z','+00:00'))
        return dt.timestamp() if dt.tzinfo else None
    except (ValueError,TypeError,AttributeError):return None


def fresh(sample, at):
    t=sample.get('vehicle_timestamp')
    return isinstance(t,(int,float)) and at is not None and 0 <= at-t <= 3600


def charging(sample):
    p=sample.get('power_kw')
    return not sample.get('contradictory') and sample.get('charging_status') in ('charging','instant_charging') and isinstance(p,(int,float)) and p>0.1


def classify(rows):
    start=next((r for r in rows if r['result']=='request_started'),None)
    success=any(r['result']=='service_returned_success' for r in rows)
    failure=next((r for r in reversed(rows) if r['result'] in FAILURES),None)
    before=start.get('before',{}) if start else next((r['before'] for r in rows if 'before' in r),{})
    at=epoch(start['utc']) if start else None
    observations=[(r,r['after']) for r in rows if 'after' in r]
    after=observations[-1][1] if observations else {}
    newer=[(r,s) for r,s in observations if at is not None and fresh(s,epoch(r['utc']))
           and s['vehicle_timestamp']>at and s['vehicle_timestamp']>(before.get('vehicle_timestamp') or 0)]
    request='调用成功' if success else '请求失败或结果未知' if failure else '请求未完成' if start else '已跳过'
    if not rows:request='没有执行记录'
    response='取得车辆新数据' if newer else '未确认车辆响应' if start else '不适用'
    completed=any(not s.get('contradictory') and fresh(s,epoch(r['utc'])) and isinstance(s.get('soc'),(int,float)) and s['soc']>=100
                  and s.get('charging_status')=='charging_completed' for r,s in observations)
    before_active=at is not None and fresh(before,at) and charging(before)
    resumed=before.get('charging_status') in ('charging_paused','charging_stopped','not_charging') and at is not None and fresh(before,at) and any(charging(s) for _,s in newer)
    ended=any(r['result']=='observation' and r.get('minutes')==10 for r in rows)
    if before_active:effect='请求前已在充电'
    elif resumed:effect='观察到暂停后开始充电'
    elif completed or any(r['result']=='target_reached' for r in rows):effect='已达到目标'
    elif ended and newer and after.get('charging_status') in ('charging_paused','charging_stopped','not_charging','initialising') and after.get('power_kw')==0:effect='十分钟内未观察到恢复'
    else:effect='证据不足'
    return dict(request=request,response=response,effect=effect,before=before,after=after,
                request_time=at,observations_complete=ended,
                reason=failure['result'] if failure else (rows[-1]['result'] if rows else 'missing'))


def night_report(rows,date,departure='08:00',target=100,expected=()):
    rows=[r for r in rows if r.get('purpose') not in ('evening_check','validation')]
    groups={}
    for r in rows:
        slot=r.get('slot','')
        if slot.startswith(date+'|') and r['result'] not in ('one_off_scheduled','schedule_missed'):
            groups.setdefault(slot,[]).append(r)
    items={slot:classify(rs) for slot,rs in sorted(groups.items())}
    cutoff=datetime.fromisoformat(date+'T'+departure).replace(tzinfo=ZONE).timestamp()
    candidates=[]
    for r in rows:
        stamp=epoch(r.get('utc'))
        if stamp is None or (datetime.fromtimestamp(stamp,ZONE).date().isoformat()!=date and not r.get('slot','').startswith(date+'|')):continue
        for name in ('before','after','snapshot'):
            s=r.get(name,{})
            t=s.get('vehicle_timestamp')
            if fresh(s,epoch(r.get('utc'))) and isinstance(t,(int,float)) and t<=cutoff and datetime.fromtimestamp(t,ZONE).date().isoformat()==date and isinstance(s.get('soc'),(int,float)):
                candidates.append(s)
    latest=max(candidates,key=lambda s:s['vehicle_timestamp']) if candidates else None
    completion='已有出发前达到目标的记录' if latest and latest['soc']>=target else '出发前最新测量仍低于目标' if latest and cutoff-latest['vehicle_timestamp']<=1800 else '数据不足，无法确认按时完成'
    count=sum(r['result']=='request_started' for rs in groups.values() for r in rs)
    lines=[f'{date} Porsche 充电夜汇总',f'实时请求 {count} 次；出发核对基准 {departure}；{completion}。']
    for slot,item in items.items():
        b,a=item['before'],item['after']
        fmt=lambda value:'未知' if value is None else str(value)
        lines.append(f"{slot.split('|')[1]}：{item['request']}；{item['response']}；{item['effect']}。SOC {fmt(b.get('soc'))} → {fmt(a.get('soc'))}%；功率 {fmt(a.get('power_kw'))} kW。")
    for minute in expected:
        if date+'|'+minute not in items:lines.append(f'{minute}：没有执行记录（可能未启用或离线）。')
    if not items:lines.append('未运行或没有可用记录。')
    lines.append('时间先后不等于因果；此报告不证明 Departure Timer 根因已修复。')
    return dict(date=date,items=items,requests=count,completion=completion,
                latest=latest,has_records=bool(items),message='\n'.join(lines))
