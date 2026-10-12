"""Pure scheduling policy: no network, credentials or Home Assistant imports."""
from datetime import datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Dublin")


def slot_key(now, times, manual=False):
    local = datetime.fromtimestamp(now, ZONE)
    minute = local.strftime("%H:%M")
    if not manual and minute not in times:
        return None
    return local.strftime("%Y-%m-%d") + "|" + minute


def decide(now, key, ledger, snapshot, target, interval, limit):
    one_off = ledger.get("one_off") == key
    if key in ledger["seen"]:
        return "duplicate"
    if ledger.get("pending"):
        return "previous_request_unknown"
    if ledger.get("auth_block"):
        return "authentication_required"
    if now < ledger.get("blocked_until", 0):
        return "failure_cooldown"
    if now - ledger.get("last_attempt", 0) < (60 if one_off else max(60, interval)) * 60:
        return "minimum_interval"
    date = key.split("|")[0]
    if ledger.get("date") == date and ledger.get("count", 0) >= min(5, limit):
        return "daily_limit"
    if not snapshot.get("available"):
        return "button_unavailable"
    if one_off:
        return "send"
    stamp = snapshot.get("vehicle_timestamp")
    fresh = isinstance(stamp, (float, int)) and 0 <= now - stamp <= 3600
    if fresh:
        if snapshot.get("plugged") is False:
            return "unplugged"
        soc = snapshot.get("soc")
        if isinstance(soc, (int, float)) and soc >= target:
            return "target_reached"
        if snapshot.get("charging") is True:
            return "already_charging"
    return "send"
