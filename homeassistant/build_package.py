"""Generate JSON (valid YAML) configuration and a dedicated UI dashboard."""
import json
from pathlib import Path

root = Path(__file__).parent
p = {
    "porsche_wake_guard": {},
    "input_boolean": {"porsche_wake_enabled": {"name": "Porsche 定时唤醒总开关", "icon": "mdi:car-clock"}},
    "input_datetime": {},
    "input_number": {},
    "input_text": {},
    "automation": [{
        "id": "porsche_wake_scheduler", "alias": "Porsche wake scheduler",
        "description": "本地调度；通过持久化保护调用实时查询 button.press。总开关默认关闭。",
        "triggers": [{"trigger": "time_pattern", "minutes": "/1"}],
        "conditions": [{"condition": "state", "entity_id": "input_boolean.porsche_wake_enabled", "state": "on"}],
        "actions": [{"action": "porsche_wake_guard.run"}],
        "mode": "single", "max_exceeded": "silent", "trace": {"stored_traces": 100},
    }],
    "script": {"porsche_wake_manual_test": {
        "alias": "Porsche 受限手动唤醒测试", "mode": "single",
        "sequence": [{"action": "porsche_wake_guard.run", "data": {"manual": True}}],
        "description": "计入每日请求上限，遵守总开关和冷却时间。",
    }},
}
for i in range(1, 6):
    p["input_boolean"][f"porsche_wake_slot_{i}"] = {"name": f"启用唤醒时段 {i}"}
    p["input_datetime"][f"porsche_wake_time_{i}"] = {
        "name": f"唤醒时间 {i}（Dublin）", "has_date": False, "has_time": True,
    }
for key,name,lo,hi,step in [
    ("target_soc","本地目标电量（不写入车辆）",1,100,1),
    ("interval_minutes","请求最小间隔（分钟）",60,1440,1),
    ("daily_limit","夜间每日请求上限",1,4,1),
]:
    p["input_number"]["porsche_wake_"+key] = {"name":name,"min":lo,"max":hi,"step":step,"mode":"box"}
for key,name in [
    ("button","实时查询按钮"),("soc","电量传感器"),("plugged","插枪二值传感器"),
    ("charging","充电状态传感器"),("power","充电功率传感器（kW）"),
    ("timestamp","车辆测量时间戳传感器（不是 HA 更新时间）"),
]:
    p["input_text"][f"porsche_wake_{key}_entity"] = {"name":name,"max":255}
p['input_text']['porsche_wake_whatsapp_target']={'name':'未插枪 WhatsApp 收件号码（E.164）','max':32}
p['input_text']['porsche_wake_whatsapp_account']={'name':'WhatsApp 账号 Entry ID','max':255}
p['input_text']['porsche_wake_notify_service']={'name':'iPhone 通知服务','max':255}
p['input_datetime']['porsche_wake_departure_time']={'name':'出发核对基准（不写入车辆）','has_date':False,'has_time':True}
p['input_datetime']['porsche_wake_summary_time']={'name':'晨间摘要时间','has_date':False,'has_time':True}
p['input_datetime']['porsche_wake_confirm_date']={'name':'确认样本日期','has_date':True,'has_time':False}
p['input_boolean']['porsche_wake_confirm_plugged']={'name':'该晚已插枪且有充电需求'}
p['input_boolean']['porsche_wake_confirm_no_intervention']={'name':'该晚无人为操作或设置变化'}
p['input_boolean']['porsche_wake_evening_enabled']={'name':'晚间充电准备检查（独立开关）'}
p['input_datetime']['porsche_wake_evening_time']={'name':'晚间充电准备检查时间','has_date':False,'has_time':True}
p['script']['porsche_wake_confirm_night']={'alias':'保存充电夜现场确认','sequence':[{'action':'porsche_wake_guard.confirm_night','data':{
    'date':"{{ states('input_datetime.porsche_wake_confirm_date') }}",
    'plugged':"{{ is_state('input_boolean.porsche_wake_confirm_plugged','on') }}",
    'no_intervention':"{{ is_state('input_boolean.porsche_wake_confirm_no_intervention','on') }}"}}]}
dashboard={"title":"Porsche 唤醒试验","views":[{"title":"Cayenne","path":"cayenne","cards":[
    {"type":"markdown","content":"## Cayenne 唤醒试验\n时区 Europe/Dublin。只发送实时概览查询，不修改 Departure Timer 或 Direct Charging。\n\n**服务调用成功 ≠ 车辆响应 ≠ 恢复充电。** 首次完成 Porsche 认证、核对实体后再启用总开关。时间按分钟执行，重启不补发。"},
    {"type":"entities","title":"运行与限制","entities":["input_boolean.porsche_wake_enabled","automation.porsche_wake_scheduler","sensor.porsche_wake_result"]+["input_number.porsche_wake_"+k for k in ("target_soc","interval_minutes","daily_limit")]+["script.porsche_wake_manual_test"]},
    {"type":"entities","title":"车辆状态（云端测量）","entities":["sensor.cayenne_s_e_hybrid_my24_state_of_charge","sensor.cayenne_s_e_hybrid_my24_charging_status","sensor.porsche_wake_vehicle_power",{"type":"attribute","entity":"sensor.porsche_wake_result","attribute":"one_off_local","name":"一次性请求例外"}]},
    {"type":"entities","title":"每天的本地时间","entities":[x for i in range(1,6) for x in (f"input_boolean.porsche_wake_slot_{i}",f"input_datetime.porsche_wake_time_{i}")]},
    {"type":"entities","title":"车辆实体映射（首次配置）","entities":["input_text."+k for k in p["input_text"]]},
    {"type":"history-graph","title":"请求结果（24 小时）","hours_to_show":24,"entities":["sensor.porsche_wake_result"]},
]}]}
cards=dashboard['views'][0]['cards']
maintenance=cards.pop(4)
cards[0]['content']='## Cayenne 充电观察\n请求成功、车辆响应和充电恢复分别判断。数据年龄以车辆测量时间计算，不增加查询。'
cards.insert(1,{'type':'entities','title':'状态与效果','entities':['sensor.porsche_wake_health','sensor.porsche_wake_effect',
    {'type':'attribute','entity':'sensor.porsche_wake_health','attribute':'next_slot','name':'下一计划时刻'},
    {'type':'attribute','entity':'sensor.porsche_wake_health','attribute':'vehicle_time','name':'车辆测量时间'},
    {'type':'attribute','entity':'sensor.porsche_wake_health','attribute':'data_age_minutes','name':'数据年龄（分钟）'},
    'sensor.porsche_wake_notification','sensor.porsche_wake_trial']})
cards.append({'type':'markdown','title':'当晚执行时间线','content':"{{ state_attr('sensor.porsche_wake_timeline','markdown') or '等待数据' }}"})
cards.append({'type':'markdown','title':'最近一晚摘要','content':"{{ state_attr('sensor.porsche_wake_night_summary','message') or '等待晨间汇总' }}"})
cards.append({'type':'entities','title':'晚间充电准备','entities':['input_boolean.porsche_wake_evening_enabled','input_datetime.porsche_wake_evening_time','sensor.porsche_wake_evening_check',
    {'type':'attribute','entity':'sensor.porsche_wake_evening_check','attribute':'plugged_label','name':'检查时连接判断'},
    {'type':'attribute','entity':'sensor.porsche_wake_evening_check','attribute':'charging_label','name':'检查时充电状态'},
    {'type':'attribute','entity':'sensor.porsche_wake_evening_check','attribute':'direct_label','name':'检查时 Direct 判断'},
    {'type':'attribute','entity':'sensor.porsche_wake_evening_check','attribute':'control_label','name':'Direct 关闭结果'},
    {'type':'attribute','entity':'sensor.porsche_wake_evening_check','attribute':'notification_result','name':'iPhone 通知结果'},
    {'type':'attribute','entity':'sensor.porsche_wake_evening_check','attribute':'whatsapp_result','name':'WhatsApp 通知结果'},
    {'type':'attribute','entity':'sensor.porsche_wake_health','attribute':'evening_attempts','name':'今日晚间查询次数'},
    {'type':'attribute','entity':'sensor.porsche_wake_health','attribute':'direct_off_attempts','name':'今日 Direct 关闭尝试'},
    {'type':'attribute','entity':'sensor.porsche_wake_health','attribute':'total_attempts','name':'今日实时请求总次数'}]})
cards.append({'type':'entities','title':'当前缓存证据（不额外查询）','entities':['sensor.porsche_wake_charging_evidence',
    {'type':'attribute','entity':'sensor.porsche_wake_charging_evidence','attribute':'charging_label','name':'具体充电状态'},
    {'type':'attribute','entity':'sensor.porsche_wake_charging_evidence','attribute':'direct_label','name':'Direct 判断'},
    {'type':'attribute','entity':'sensor.porsche_wake_charging_evidence','attribute':'charging_mode_raw','name':'原始 mode（安全枚举）'},
    {'type':'attribute','entity':'sensor.porsche_wake_charging_evidence','attribute':'charging_mode_type','name':'mode 数据类型'},
    {'type':'attribute','entity':'sensor.porsche_wake_charging_evidence','attribute':'charging_mode_filtered','name':'是否被白名单过滤'}]})
cards.append({'type':'markdown','content':"{{ state_attr('sensor.porsche_wake_evening_check','message') or '每日 20:00 检查；状态无法确认时最多查询一次。' }}"})
cards.append({'type':'entities','title':'一次性只读验收','entities':['sensor.porsche_wake_validation',
    *[{'type':'attribute','entity':'sensor.porsche_wake_validation','attribute':key,'name':name} for key,name in [('id','计划时间'),('before_status','查询前状态'),('after_status','查询后状态'),('before_measured_at','查询前测量时间'),('after_measured_at','查询后测量时间'),('finished','完成时间'),('used_refresh','使用实时查询'),('data_age_minutes','判定时数据年龄（分钟）'),('reason_text','保护原因'),('vehicle_response','车辆响应证据'),('plugged_label','连接判断'),('charging_label','具体充电状态'),('direct_label','模式判断'),('charging_mode_raw','原始模式'),('iphone_result','iPhone 结果'),('whatsapp_result','WhatsApp 结果')]]],
    'footer':{'type':'buttons','entities':[{'entity':'sensor.porsche_wake_validation','name':'取消待执行验收','tap_action':{'action':'call-service','service':'porsche_wake_guard.cancel_validation'}}]}})
dashboard['views'].append({'title':'设置与样本','path':'settings','cards':[
    maintenance,{'type':'entities','title':'通知与核对时间','entities':['sensor.porsche_wake_whatsapp_notification','input_text.porsche_wake_whatsapp_target','input_text.porsche_wake_whatsapp_account','input_text.porsche_wake_notify_service','input_datetime.porsche_wake_departure_time','input_datetime.porsche_wake_summary_time']},
    {'type':'entities','title':'确认有效充电夜（不确定时不要勾选）','entities':['input_datetime.porsche_wake_confirm_date','input_boolean.porsche_wake_confirm_plugged','input_boolean.porsche_wake_confirm_no_intervention','script.porsche_wake_confirm_night']},
    {'type':'markdown','content':'异常和晨间摘要推送到已选 iPhone；普通成功、正常跳过不逐条通知。08:00 是本地核对基准，不修改车辆定时器。手机接口接受不代表实际送达。\n\n晚间检查有独立开关。仅确认未插枪时发送 WhatsApp 中文消息和 iPhone Time Sensitive 提醒；确认已插枪且为 Direct 时，每天最多尝试关闭一次。成功、失败或结果未知均只记录，不发送晚间提醒；普通状态不明只记录。关闭 Direct 可能停止直接充电，不等于保证定时器生效。状态查询仍为夜间最多 4 次＋晚间最多 1 次，关闭命令另计。'}]})
(root/"packages").mkdir(exist_ok=True)
(root/"packages/porsche_wake.yaml").write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n")
(root/"porsche_wake_dashboard.yaml").write_text(json.dumps(dashboard,ensure_ascii=False,indent=2)+"\n")
