"""Durable, serialized guard around the official integration's button.press.

No credentials are handled here. Unknown vehicle timestamps never count as fresh.
"""
import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextvars import ContextVar
from types import SimpleNamespace

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.components import persistent_notification
from homeassistant.exceptions import HomeAssistantError

from .policy import ZONE, decide, slot_key
from .audit import Audit
from .runtime import Runtime
from .evening import Evening,NON_DIRECT_MODES

DOMAIN = "porsche_wake_guard"
RESULT_LABELS = {
    "evening_check_started":"正在检查晚间充电准备",
    "evening_refresh_started":"晚间检查正在查询车辆实时状态",
    "evening_refresh_success":"晚间实时查询调用成功",
    "evening_check_complete":"晚间充电准备检查已完成",
    "evening_interrupted":"晚间检查被重启中断，未重复查询",
    "total_daily_limit":"已达到今日实时请求总上限，本次已跳过",
    "observation_node_missed": "错过观察节点，未补发缓存查询",
    "observation_finished": "观察窗口已结束",
    "summary_snapshot": "晨间汇总已读取本地缓存",
    "ready_disabled_until_configured": "唤醒保护已就绪",
    "inspection_no_request": "已查看车辆缓存，未发送唤醒请求",
    "request_started": "正在请求车辆实时状态",
    "service_returned_success": "实时查询调用成功，车辆响应待核实",
    "observation": "已记录请求后的车辆状态",
    "observation_cancelled": "总开关已关闭，后续观察已停止",
    "cached_read_success": "已读取云端缓存，未额外唤醒车辆",
    "cached_read_failed": "云端缓存读取失败，后续唤醒已暂停",
    "one_off_scheduled": "已安排一次性唤醒请求",
    "authentication_hold_cleared": "认证暂停已解除，等待下一次计划",
    "authentication_required": "登录认证失效，请重新登录 Porsche",
    "rate_limited": "Porsche 服务限流，后续请求已暂停",
    "timeout_unknown": "请求超时，是否送达车辆尚不确定",
    "request_failed_unknown": "请求失败，车辆响应尚不确定",
    "interrupted_request_unknown": "请求被重启中断，结果未知，已暂停 24 小时",
    "previous_request_unknown": "上次请求结果尚未确认，本次已跳过",
    "failure_cooldown": "故障或限流冷却中，本次已跳过",
    "minimum_interval": "尚未达到最小请求间隔，本次已跳过",
    "daily_limit": "已达到今日请求上限，本次已跳过",
    "button_unavailable": "车辆实时查询按钮不可用，本次已跳过",
    "unplugged": "车辆未连接充电设备，本次已跳过",
    "target_reached": "车辆已达到目标电量，本次已跳过",
    "already_charging": "车辆正在正常充电，本次已跳过",
    "duplicate": "该时刻已处理，本次不重复执行",
}
REQUEST_FAILURES = ContextVar("porsche_wake_failures", default=None)
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)


class ObservedFailure(HomeAssistantError):
    """Sanitized signal for an exception swallowed by the upstream library."""
    def __init__(self, code=None, retry_after=None):
        super().__init__("Porsche request failed")
        self.status_code = code
        self.response = SimpleNamespace(status_code=code,headers={"Retry-After":retry_after or ""})


async def stop_library_retry(response):
    """HTTPX supported response hook: abort before upstream status-error retry.

The shared client is untouched for requests outside this guard's ContextVar.
No response body, URL, VIN, token or credential is retained in the exception.
"""
    if REQUEST_FAILURES.get() is not None and response.status_code >= 400:
        raise ObservedFailure(response.status_code,response.headers.get("Retry-After")) from None


def retry_deadline(exc, now):
    """Honor exposed Retry-After without retaining headers or response bodies."""
    until = now + 86400
    headers = getattr(getattr(exc,"response",None),"headers",{})
    retry = headers.get("Retry-After", "")
    try:
        seconds = float(retry)
        if math.isfinite(seconds):until = max(until, now+seconds)
    except (TypeError,ValueError):
        from email.utils import parsedate_to_datetime
        try:until = max(until,parsedate_to_datetime(retry).timestamp())
        except (TypeError,ValueError,OverflowError):pass
    return until


class PrivateFailureCapture(logging.Filter):
    def filter(self, record):
        failures = REQUEST_FAILURES.get()
        if failures is not None and record.levelno >= logging.ERROR:
            exc = record.exc_info[1] if record.exc_info else None
            code = getattr(exc, "code", None)
            if type(exc).__name__ in ("PorscheWrongCredentialsError", "PorscheCaptchaRequiredError"):
                code = 401
            failures.append(code if isinstance(code, int) else None)
        # Never emit the upstream raw response, URL, VIN or exception message.
        return False


async def async_setup(hass, config):
    guard = Guard(hass)
    if not await guard.load():
        return False
    hass.data[DOMAIN] = guard
    vehicle_logger = logging.getLogger("pyporscheconnectapi.vehicle")
    vehicle_logger.addFilter(PrivateFailureCapture())
    vehicle_logger.setLevel(logging.ERROR)
    hass.services.async_register(DOMAIN, "run", guard.run,
        schema=vol.Schema({vol.Optional("manual", default=False): cv.boolean}))
    hass.services.async_register(DOMAIN, "resume", guard.resume, schema=vol.Schema({}))
    hass.services.async_register(DOMAIN, "inspect", guard.inspect, schema=vol.Schema({}))
    hass.services.async_register(DOMAIN, "request_once_at", guard.request_once_at,
        schema=vol.Schema({vol.Required("slot"): str}))
    hass.services.async_register(DOMAIN,"refresh_report",guard.refresh_report,schema=vol.Schema({}))
    hass.services.async_register(DOMAIN,"notification_test",guard.notification_test,schema=vol.Schema({}))
    hass.services.async_register(DOMAIN,"evening_notification_test",guard.evening_notification_test,schema=vol.Schema({}))
    hass.services.async_register(DOMAIN,"confirm_night",guard.confirm_night,schema=vol.Schema({
        vol.Required("date"):str,vol.Required("plugged"):cv.boolean,vol.Required("no_intervention"):cv.boolean}))
    if hass.is_running:
        await guard.runtime_start()
    else:
        hass.bus.async_listen_once('homeassistant_started',guard.runtime_start)
    return True


class Guard(Runtime,Evening):
    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, DOMAIN, private=True, atomic_writes=True)
        self.lock = asyncio.Lock()
        self.ledger = None
        self.failed = False
        self.vehicle = None
        self.coordinator = None
        self.logpath = Path(hass.config.path("porsche_wake_audit.jsonl"))
        self.marker = Path(hass.config.path(".porsche_wake_initialized"))
        self.audit = Audit(hass.config.path(''))
        self.rows = []
        self.last_recorded = None
        self.evening_task = None

    async def load(self):
        try:
            self.ledger = await self.store.async_load()
            if self.ledger is None:
                if await self.hass.async_add_executor_job(self.marker.exists):
                    raise ValueError("previous ledger missing")
                self.ledger = dict(seen=[], count=0, date="", last_attempt=0,
                                   pending=False, blocked_until=0, auth_block=False)
                await self.store.async_save(self.ledger)
            def mark_initialized():
                fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT, 0o600)
                os.close(fd)
            await self.hass.async_add_executor_job(mark_initialized)
            if not isinstance(self.ledger.get("seen"), list):
                raise ValueError("invalid ledger")
            if self.ledger.get("pending"):
                self.ledger["pending"] = False
                self.ledger["blocked_until"] = max(time.time()+86400, self.ledger.get("blocked_until", 0))
                purpose=self.ledger.pop('pending_purpose',None)
                await self.store.async_save(self.ledger)
                if purpose=='evening':
                    await self.record('evening_interrupted',purpose='evening_check')
                else:
                    await self.record("interrupted_request_unknown")
                    self.notify("上次请求被系统重启中断，结果未知；暂停 24 小时，不自动补发。")
            return True
        except Exception:
            self.notify("唤醒持久化状态不可用，已停止发送请求。请检查存储。")
            return False

    def publish(self, result, **attrs):
        sample = attrs.get("snapshot") or attrs.get("after") or attrs.get("before")
        if sample:
            self.publish_power(sample)
        label = RESULT_LABELS.get(result, "未识别的执行结果，请查看状态代码")
        self.hass.states.async_set("sensor.porsche_wake_result", label, {
            "result_code": result,
            "friendly_name": "Porsche 唤醒结果", "last_recorded": self.last_recorded or datetime.now(timezone.utc).isoformat(),
            "today_attempts": self.ledger.get("count", 0) if self.ledger.get('date')==datetime.now(ZONE).date().isoformat() else 0,
            "one_off_local": self.ledger.get("one_off"),
            "blocked_until_utc": self.ledger.get("blocked_until", 0), **attrs})

    def publish_power(self, sample):
        power = sample.get("power_kw")
        self.hass.states.async_set("sensor.porsche_wake_vehicle_power",power if power is not None else "unavailable",{
            "friendly_name":"Porsche 充电功率（车辆测量）","unit_of_measurement":"kW",
            "device_class":"power","state_class":"measurement",
            "source_field":sample.get("power_source"),"vehicle_timestamp":sample.get("vehicle_timestamp")})

    async def save(self):
        try:
            await self.store.async_save(self.ledger)
        except Exception:
            self.failed = True
            self.notify("无法保存请求去重记录，已停止所有后续请求。")
            raise

    async def record(self, result, **attrs):
        row = dict(utc=datetime.now(timezone.utc).isoformat(), vehicle="Cayenne", result=result, **attrs)
        if attrs.get('slot'):row['request_id']='Cayenne|'+attrs['slot']
        elif attrs.get('purpose')=='evening_check' and attrs.get('evening_date'):
            row['request_id']='Cayenne|evening|'+attrs['evening_date']
        try:
            await self.hass.async_add_executor_job(self.audit.append,row)
        except Exception:
            self.failed = True
            self.notify("无法写入唤醒审计记录，已停止发送请求。")
            raise
        self.rows.append(row)
        if attrs.get('purpose')!='evening_check':
            self.last_recorded=row['utc']
            self.publish(result, **attrs)

    def value(self, entity):
        state = self.hass.states.get(entity)
        return state.state if state else "unavailable"

    def number(self, key, default):
        try:
            value = float(self.value("input_number.porsche_wake_"+key))
            return value if math.isfinite(value) else default
        except ValueError:
            return default

    def snapshot(self):
        def mapped(kind):
            entity = self.value("input_text.porsche_wake_"+kind+"_entity")
            return self.value(entity)
        def numeric(value):
            try:
                n = float(value)
                return n if math.isfinite(n) else None
            except (TypeError, ValueError):
                return None
        button = self.value("input_text.porsche_wake_button_entity")
        # Require this exact integration's real-time-overview button, never arbitrary buttons.
        from homeassistant.helpers import entity_registry as er
        entry = er.async_get(self.hass).async_get(button)
        valid = bool(entry and entry.platform == "porscheconnect"
                     and entry.unique_id.endswith("-get_current_overview") and not entry.disabled_by)
        plugged = mapped("plugged")
        status = mapped("charging")
        power = None
        power_source = "unknown"
        stamp = None
        raw_stamp = mapped("timestamp")
        try:
            parsed = datetime.fromisoformat(raw_stamp.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                stamp = parsed.timestamp()
        except (ValueError, TypeError):
            pass
        metadata = []
        vehicle_times = {}
        mode=None
        direct_switch='unavailable'
        self.vehicle = None
        self.coordinator = None
        if valid:
            for coordinator in self.hass.data.get("porscheconnect", {}).values():
                for vehicle in getattr(coordinator, "vehicles", []):
                    if f"{vehicle.vin}-get_current_overview" != entry.unique_id:
                        continue
                    self.vehicle, self.coordinator = vehicle, coordinator
                    for measurement in getattr(vehicle,"status",{}).get("measurements",[]):
                        if measurement.get("key") in ("BATTERY_LEVEL","CHARGING_SUMMARY","CHARGING_RATE","CHARGING_SETTINGS"):
                            if measurement['key']=='CHARGING_SUMMARY':
                                raw_mode=measurement.get('value',{}).get('mode')
                                if isinstance(raw_mode,str) and raw_mode.upper() in NON_DIRECT_MODES|{'DIRECT'}:mode=raw_mode.upper()
                            if measurement["key"] == "CHARGING_RATE":
                                values=measurement.get('value',{})
                                for field in ('chargingPowerkW','chargingPower'):
                                    native_power=numeric(values.get(field))
                                    # The library synthesizes chargingPower=0 when chargingRate is absent.
                                    if field=='chargingPower' and not values.get('chargingRate'):
                                        continue
                                    if native_power is not None and native_power>=0:
                                        power,power_source=native_power,'CHARGING_RATE.'+field
                                        break
                            metadata.append({"key":measurement["key"],"fields":sorted(measurement),
                                "status_fields":sorted(measurement.get("status",{})),
                                "value_fields":sorted(measurement.get("value",{}))})
                            modified = measurement.get("value",{}).get("lastModified")
                            if isinstance(modified,str):
                                try:
                                    parsed = datetime.fromisoformat(modified.replace("Z","+00:00"))
                                    if parsed.tzinfo is not None:
                                        vehicle_times[measurement["key"]] = parsed.timestamp()
                                except ValueError:
                                    pass
        required_times = ("BATTERY_LEVEL","CHARGING_SUMMARY","CHARGING_RATE")
        if all(k in vehicle_times for k in required_times) and max(vehicle_times[k] for k in required_times) <= time.time():
            stamp = min(vehicle_times[k] for k in required_times)
        connected = {"on":True,"off":False}.get(plugged)
        if connected is None and status == "not_plugged":
            connected = False
        if valid:
            device_id=getattr(entry,'device_id',None)
            registry=er.async_get(self.hass)
            if device_id and hasattr(registry,'entities'):
                matches=[e.entity_id for e in registry.entities.values() if e.platform=='porscheconnect' and e.device_id==device_id and e.entity_id.startswith('switch.') and e.unique_id.endswith('-direct_charging') and not e.disabled_by]
                if len(matches)==1:direct_switch=self.value(matches[0])
        contradictory = (status in ('charging_completed','not_plugged','charging_paused') and power is not None and power>0.1)
        return dict(available=valid and self.value(button) != "unavailable",
                    soc=numeric(mapped("soc")), plugged=connected,
                    charging=True if not contradictory and status in ('charging','instant_charging') and power is not None and power>0.1 else None,
                    contradictory=contradictory,
                    charging_mode=mode,direct_switch=direct_switch,
                    plugged_timestamp=vehicle_times.get('CHARGING_SUMMARY') if status=='not_plugged' else None,
                    charging_status=status if status in {"charging", "charging_paused", "charging_stopped", "charging_completed", "charging_error", "initialising", "instant_charging", "not_charging", "not_plugged", "off", "on", "unknown", "unavailable"} else "other",
                    power_kw=power, power_source=power_source, vehicle_timestamp=stamp, measurement_timestamps=vehicle_times,
                    measurement_metadata=metadata)

    async def inspect(self, call):
        async with self.lock:
            await self.record("inspection_no_request", snapshot=self.snapshot())

    async def request_once_at(self, call):
        key = call.data["slot"]
        date, minute = key.split("|")
        requested = datetime.strptime(date+" "+minute,"%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
        if not 0 < requested.timestamp()-time.time() <= 86400:
            raise ValueError("One-off must be within the next 24 hours")
        async with self.lock:
            self.ledger["one_off"] = key
            await self.save()
            await self.record("one_off_scheduled",slot=key)

    async def resume(self, call):
        async with self.lock:
            self.ledger["auth_block"] = False
            await self.save()
            await self.record("authentication_hold_cleared")

    async def press_current(self):
        # Revalidate the configured real-time-overview button immediately before dispatch.
        if not self.snapshot().get('available'):
            raise HomeAssistantError('Vehicle real-time button is unavailable')
        button=self.value('input_text.porsche_wake_button_entity')
        if self.vehicle is not None:
            hooks=self.vehicle.connection.asyncClient.event_hooks['response']
            if stop_library_retry not in hooks:hooks.append(stop_library_retry)
        logger=logging.getLogger('pyporscheconnectapi.vehicle')
        if not any(isinstance(f,PrivateFailureCapture) for f in logger.filters):logger.addFilter(PrivateFailureCapture())
        logger.setLevel(logging.ERROR)
        failures=[];token=REQUEST_FAILURES.set(failures)
        try:
            async with asyncio.timeout(300):
                await self.hass.services.async_call('button','press',{'entity_id':button},blocking=True)
            if failures:raise ObservedFailure(failures[0])
        finally:REQUEST_FAILURES.reset(token)

    def apply_request_failure(self,exc,now):
        response=getattr(exc,'response',None)
        status=getattr(exc,'status_code',None) or getattr(exc,'code',None) or getattr(response,'status_code',None)
        reason='timeout_unknown' if isinstance(exc,TimeoutError) else 'request_failed_unknown'
        until=datetime.fromtimestamp(now,ZONE).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        self.ledger['blocked_until']=until.timestamp()
        if status in (401,403):
            self.ledger['auth_block']=True;reason='authentication_required'
        elif status==429:
            reason='rate_limited';self.ledger['blocked_until']=retry_deadline(exc,now)
        self.ledger['pending']=False
        return reason

    async def run(self, call):
        if self.lock.locked() or self.failed:
            return
        async with self.lock:
            if self.value("input_boolean.porsche_wake_enabled") != "on":
                return
            if self.hass.config.time_zone != "Europe/Dublin":
                self.notify("Home Assistant 时区必须为 Europe/Dublin，已跳过唤醒。")
                return
            times = [self.value(f"input_datetime.porsche_wake_time_{i}")[:5] for i in range(1,6)
                     if self.value(f"input_boolean.porsche_wake_slot_{i}") == "on"]
            now = time.time()
            key = slot_key(now, times, call.data.get("manual", False))
            before = self.snapshot()
            self.publish_power(before)  # Cached data only; no network traffic.
            if key is None:
                return
            reason = decide(now, key, self.ledger, before,
                            self.number("target_soc", 100), self.number("interval_minutes",120),
                            self.number("daily_limit",4))
            if reason == "minimum_interval":
                remaining = self.ledger.get("last_attempt", 0) + (60 if self.ledger.get("one_off")==key else max(60, self.number("interval_minutes",120)))*60 - now
                if 0 < remaining < 5:
                    # Hourly dispatch jitter must not skip an entire scheduled hour.
                    await asyncio.sleep(remaining + 0.05)
                    now = time.time()
                    if self.value("input_boolean.porsche_wake_enabled") != "on":
                        return
                    reason = decide(now,key,self.ledger,before,self.number("target_soc",100),
                                    self.number("interval_minutes",120),self.number("daily_limit",4))
            if reason == "duplicate":
                return
            self.ledger["seen"] = (self.ledger["seen"] + [key])[-1000:]
            if self.ledger.get("one_off") == key:
                self.ledger.pop("one_off")
            if reason != "send":
                await self.save()
                await self.record(reason, slot=key, before=before)
                if reason in ("button_unavailable", "authentication_required"):
                    self.notify("Porsche 集成或实时查询按钮不可用；请在集成页面检查认证及实体配置。")
                return
            if self.ledger.get('observation'):
                return
            date = key.split("|")[0]
            self.ledger["count"] = (self.ledger.get("count",0) if self.ledger.get("date")==date else 0)+1
            self.ledger.update(date=date, last_attempt=now, pending=True)
            await self.save()  # Must finish atomic persistent reservation BEFORE button.press.
            await self.record("request_started", slot=key, before=before)
            button = self.value("input_text.porsche_wake_button_entity")
            try:
                await self.press_current()
            except Exception as exc:
                reason=self.apply_request_failure(exc,time.time())
                await self.save()
                await self.record(reason, slot=key, before=before)
                self.notify("实时查询失败或结果未知，后续请求已暂停。请查看 Porsche 唤醒结果与集成状态。",reason)
                return
            self.ledger["pending"] = False
            self.ledger['observation']={'slot':key,'before':before,'started':time.time(),'cursor':0,'button':button}
            await self.save()
            await self.record("service_returned_success",slot=key,before=before,after=self.snapshot())
            if hasattr(self,'meta') and self.meta.get('last_fault'):
                self.hass.async_create_background_task(self.send_notice('实时查询已恢复正常；充电效果仍以车辆测量为准。','recovery:'+self.meta['last_fault']),'porsche-recovery-notice')
                self.meta.pop('last_fault',None)
            await self.observe()

    async def resume_observation(self):
        async with self.lock:
            await self.observe(resuming=True)

    async def observe(self,resuming=False):
            job=self.ledger.get('observation')
            if not job:return
            key,before=job['slot'],job['before']
            if resuming:
                self.snapshot()
                if job.get('button')!=self.value('input_text.porsche_wake_button_entity') or self.vehicle is None:
                    await self.record('observation_cancelled',slot=key,reason='vehicle_mapping_unavailable')
                    self.ledger.pop('observation',None);await self.save();return
            for index,minutes in enumerate((2,4,6,8,10)):
                if index<job['cursor']:continue
                due=job['started']+minutes*60
                if resuming and due<time.time():
                    job['cursor']=index+1;await self.save()
                    await self.record('observation_node_missed',slot=key,minutes=minutes)
                    continue
                await asyncio.sleep(max(0,due-time.time()))
                if self.value("input_boolean.porsche_wake_enabled") != "on":
                    await self.record("observation_cancelled",slot=key,minutes=minutes)
                    self.ledger.pop('observation',None);await self.save()
                    return
                job['cursor']=index+1
                await self.save() # Reserve observation node before a possible cached API request.
                if minutes in (2,10) and self.vehicle is not None:
                    hooks=self.vehicle.connection.asyncClient.event_hooks['response']
                    if stop_library_retry not in hooks:hooks.append(stop_library_retry)
                    failures = []
                    context_token = REQUEST_FAILURES.set(failures)
                    try:
                        async with asyncio.timeout(30):
                            await self.vehicle.get_stored_overview()
                        if failures:
                            raise ObservedFailure(failures[0])
                        self.coordinator.async_update_listeners()
                        await self.record("cached_read_success",slot=key,minutes=minutes)
                    except Exception as exc:
                        code = getattr(exc,"status_code",None) or getattr(exc,"code",None)
                        self.ledger["blocked_until"] = max(self.ledger.get("blocked_until",0),retry_deadline(exc,time.time()))
                        if code in (401,403):self.ledger["auth_block"] = True
                        await self.save()
                        await self.record("cached_read_failed",slot=key,minutes=minutes,
                                          status_code=code if isinstance(code,int) else None)
                        self.notify("后续缓存查询失败，暂停唤醒 24 小时；不重复发送实时查询。",'cached_read_failed:'+str(code))
                        self.ledger.pop('observation',None);await self.save()
                        return
                    finally:
                        REQUEST_FAILURES.reset(context_token)
                await self.record("observation",slot=key,minutes=minutes,before=before,after=self.snapshot())
            self.ledger.pop('observation',None)
            await self.save()
