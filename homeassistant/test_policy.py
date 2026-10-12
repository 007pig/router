"""Safety and DST regression tests; never connect to a vehicle."""
import importlib.util
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import unittest

spec=importlib.util.spec_from_file_location("policy",Path(__file__).parent/"custom_components/porsche_wake_guard/policy.py")
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,12,1,tzinfo=p.ZONE).timestamp()
        self.key=p.slot_key(self.now,["01:00"])
        self.ledger=dict(seen=[],count=0,date="",last_attempt=0)
        self.snap=dict(available=True)

    def result(self):
        return p.decide(self.now,self.key,self.ledger,self.snap,100,60,5)

    def test_five_times(self):
        for hour in range(1,6):
            t=datetime(2026,10,12,hour,tzinfo=p.ZONE).timestamp()
            self.assertIsNotNone(p.slot_key(t,[f"{h:02d}:00" for h in range(1,6)]))
        self.assertIsNone(p.slot_key(self.now,["02:00"]))

    def test_fall_repeat_deduplicated(self):
        a=datetime(2026,10,25,1,tzinfo=p.ZONE,fold=0).timestamp()
        b=datetime(2026,10,25,1,tzinfo=p.ZONE,fold=1).timestamp()
        self.assertEqual(b-a,3600)
        key=p.slot_key(a,["01:00"])
        self.assertEqual(key,p.slot_key(b,["01:00"]))
        self.ledger["seen"]=[key]
        self.assertEqual(p.decide(b,key,self.ledger,self.snap,100,60,5),"duplicate")

    def test_spring_missing_hour(self):
        # Walk real UTC instants: nonexistent local 01:00 never matches.
        start=datetime(2027,3,28,tzinfo=ZoneInfo("UTC")).timestamp()
        self.assertFalse(any(p.slot_key(start+i*60,["01:00"]) for i in range(180)))

    def test_stale_unknown_can_send(self):
        self.assertEqual(self.result(),"send")
        self.snap.update(vehicle_timestamp=self.now-3601,plugged=False,soc=100,charging=True)
        self.assertEqual(self.result(),"send")

    def test_fresh_skip_conditions(self):
        for fields,expected in [(dict(plugged=False),"unplugged"),(dict(soc=100),"target_reached"),(dict(charging=True),"already_charging")]:
            self.snap=dict(available=True,vehicle_timestamp=self.now,**fields)
            self.assertEqual(self.result(),expected)

    def test_future_timestamp_not_trusted(self):
        self.snap.update(vehicle_timestamp=self.now+20,plugged=False)
        self.assertEqual(self.result(),"send")

    def test_pending_and_auth_fail_closed(self):
        self.ledger["pending"]=True
        self.assertEqual(self.result(),"previous_request_unknown")
        self.ledger.update(pending=False,auth_block=True)
        self.assertEqual(self.result(),"authentication_required")

    def test_limits_and_next_day(self):
        self.ledger.update(date="2026-10-12",count=5)
        self.assertEqual(self.result(),"daily_limit")
        self.ledger["date"]="2026-10-11"
        self.assertEqual(self.result(),"send")
        self.ledger["last_attempt"]=self.now-3599
        self.assertEqual(self.result(),"minimum_interval")
        self.ledger["last_attempt"]=self.now-3600
        self.assertEqual(self.result(),"send")

    def test_failure_cooldown(self):
        self.ledger["blocked_until"]=self.now+86400
        self.assertEqual(self.result(),"failure_cooldown")

    def test_button_missing(self):
        self.snap["available"]=False
        self.assertEqual(self.result(),"button_unavailable")

    def test_one_off_does_not_bypass_auth_or_rate_limit(self):
        self.ledger.update(one_off=self.key,last_attempt=self.now-90*60)
        self.snap.update(vehicle_timestamp=self.now,soc=100,charging=True)
        self.assertEqual(p.decide(self.now,self.key,self.ledger,self.snap,100,120,4),'send')
        self.ledger['auth_block']=True
        self.assertEqual(self.result(),'authentication_required')
        self.ledger.update(auth_block=False,blocked_until=self.now+100)
        self.assertEqual(self.result(),'failure_cooldown')

    def test_one_off_is_exact_date_time_only(self):
        self.ledger.update(one_off='2026-10-12|07:00',last_attempt=self.now-90*60)
        self.assertEqual(p.decide(self.now,self.key,self.ledger,self.snap,100,120,4),'minimum_interval')


if __name__=="__main__":unittest.main()
