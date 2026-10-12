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
    ("daily_limit","每日请求上限",1,5,1),
]:
    p["input_number"]["porsche_wake_"+key] = {"name":name,"min":lo,"max":hi,"step":step,"mode":"box"}
for key,name in [
    ("button","实时查询按钮"),("soc","电量传感器"),("plugged","插枪二值传感器"),
    ("charging","充电状态传感器"),("power","充电功率传感器（kW）"),
    ("timestamp","车辆测量时间戳传感器（不是 HA 更新时间）"),
]:
    p["input_text"][f"porsche_wake_{key}_entity"] = {"name":name,"max":255}
dashboard={"title":"Porsche 唤醒试验","views":[{"title":"Cayenne","path":"cayenne","cards":[
    {"type":"markdown","content":"## Cayenne 唤醒试验\n时区 Europe/Dublin。只发送实时概览查询，不修改 Departure Timer 或 Direct Charging。\n\n**服务调用成功 ≠ 车辆响应 ≠ 恢复充电。** 首次完成 Porsche 认证、核对实体后再启用总开关。时间按分钟执行，重启不补发。"},
    {"type":"entities","title":"运行与限制","entities":["input_boolean.porsche_wake_enabled","automation.porsche_wake_scheduler","sensor.porsche_wake_result"]+["input_number.porsche_wake_"+k for k in ("target_soc","interval_minutes","daily_limit")]+["script.porsche_wake_manual_test"]},
    {"type":"entities","title":"车辆状态（云端测量）","entities":["sensor.cayenne_s_e_hybrid_my24_state_of_charge","sensor.cayenne_s_e_hybrid_my24_charging_status","sensor.porsche_wake_vehicle_power",{"type":"attribute","entity":"sensor.porsche_wake_result","attribute":"one_off_local","name":"一次性请求例外"}]},
    {"type":"entities","title":"每天的本地时间","entities":[x for i in range(1,6) for x in (f"input_boolean.porsche_wake_slot_{i}",f"input_datetime.porsche_wake_time_{i}")]},
    {"type":"entities","title":"车辆实体映射（首次配置）","entities":["input_text."+k for k in p["input_text"]]},
    {"type":"history-graph","title":"请求结果（24 小时）","hours_to_show":24,"entities":["sensor.porsche_wake_result"]},
]}]}
(root/"packages").mkdir(exist_ok=True)
(root/"packages/porsche_wake.yaml").write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n")
(root/"porsche_wake_dashboard.yaml").write_text(json.dumps(dashboard,ensure_ascii=False,indent=2)+"\n")
