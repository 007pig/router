"""Bounded, non-sensitive mode diagnostics and human-readable charging evidence."""
import re


def mode_evidence(values,known_modes):
    raw=values.get('mode')
    safe=isinstance(raw,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_ -]{0,47}',raw) is not None
    normalized=raw.upper() if safe else None
    return {'charging_mode':normalized if normalized in known_modes else None,
            'charging_mode_raw':raw if safe else None,
            'charging_mode_type':type(raw).__name__,
            'charging_mode_present':'mode' in values,
            'charging_mode_filtered':bool(safe and normalized not in known_modes),
            'charging_mode_redacted':raw is not None and not safe}


def describe(sample,check):
    inferred=check.get('plugged_inferred',False)
    plugged=('未连接' if check['plugged'] is False else '推断已连接' if inferred or check['plugged'] is True else '未知')
    status=sample.get('charging_status')
    labels={'charging':'正在充电','instant_charging':'正在即时充电','charging_paused':'暂停等待',
            'charging_completed':'充电完成','not_plugged':'未插枪','charging_stopped':'充电已停止',
            'charging_error':'充电错误','initialising':'初始化中','not_charging':'未充电',
            'unknown':'未知','unavailable':'不可用','other':'未识别状态','off':'off','on':'on'}
    charging_label=labels.get(status,'未知')
    if not check.get('summary_fresh'):charging_label+='（陈旧或时间未知）'
    switch=sample.get('direct_switch')
    direct=('已确认 Direct' if check['direct'] is True else '已确认非 Direct' if check['direct'] is False
            else '开关显示 off，不发送关闭命令；原始模式未确认' if switch=='off'
            else 'Direct 模式无法确认')
    if not check.get('summary_fresh'):direct+='；车辆模式数据陈旧或时间未知'
    if sample.get('charging_mode')=='CYCLIC_DEPARTURE':
        direct=('非 Direct：周期出发模式（CYCLIC_DEPARTURE）' if check['direct'] is False
                else '最近原始模式 CYCLIC_DEPARTURE；当前模式需结合新鲜度及开关判断')
        if switch=='off':direct+='；开关 off，不发送关闭命令'
        if not check.get('summary_fresh'):direct+='；车辆模式数据陈旧或时间未知'
    return {'plugged_label':plugged,'connection_state':plugged,'charging_status':status if status in labels else 'other',
            'charging_label':charging_label,'control_connection_confirmed':check['plugged'] is True,'direct_label':direct,
            'data_age_minutes':check.get('data_age_minutes'),'direct_switch':switch,'charging_mode_raw':sample.get('charging_mode_raw'),
            'charging_mode_type':sample.get('charging_mode_type','未记录'),
            'charging_mode_filtered':sample.get('charging_mode_filtered'),
            'inference_note':'暂停原因未确认，不保证 Departure Timer 将正常恢复充电' if status=='charging_paused' and check.get('summary_fresh') else '连接推断不作为自动控制的充分依据' if inferred else ''}
