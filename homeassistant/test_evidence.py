import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from datetime import datetime,timezone

root=Path(__file__).parent/'custom_components/porsche_wake_guard'
pkg=types.ModuleType('evidence_tests_package');pkg.__path__=[str(root)]
sys.modules[pkg.__name__]=pkg
from evidence_tests_package.evidence import classify,night_report
from evidence_tests_package.audit import Audit


def row(result,seconds,**kw):
    return dict(utc=datetime.fromtimestamp(seconds,timezone.utc).isoformat(),result=result,slot='2026-10-13|03:00',**kw)


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.t=datetime(2026,10,13,2,tzinfo=timezone.utc).timestamp()
        self.before=dict(soc=28,charging_status='charging_paused',power_kw=0,vehicle_timestamp=self.t-30)

    def records(self,after):
        return [row('request_started',self.t,before=self.before),row('service_returned_success',self.t+30,after=after),row('observation',self.t+600,minutes=10,after=after)]

    def test_resume_requires_fresh_data_and_real_power(self):
        after=dict(soc=30,charging_status='charging',power_kw=7.14,vehicle_timestamp=self.t+238)
        rows=self.records(after);rows[1]['after']=dict(self.before,charging_status='initialising',vehicle_timestamp=self.t+22)
        result=classify(rows)
        self.assertEqual(result['response'],'取得车辆新数据')
        self.assertEqual(result['effect'],'观察到暂停后开始充电')

    def test_initialising_is_not_recovery(self):
        a=dict(self.before,charging_status='initialising',vehicle_timestamp=self.t+20)
        self.assertEqual(classify(self.records(a))['effect'],'十分钟内未观察到恢复')

    def test_unchanged_cache_is_not_response(self):
        self.assertEqual(classify(self.records(self.before))['response'],'未确认车辆响应')

    def test_future_measurement_is_not_response(self):
        a=dict(self.before,vehicle_timestamp=self.t+9000)
        self.assertEqual(classify(self.records(a))['response'],'未确认车辆响应')

    def test_unknown_power_is_not_zero(self):
        a=dict(self.before,power_kw=None,vehicle_timestamp=self.t+20)
        self.assertEqual(classify(self.records(a))['effect'],'证据不足')

    def test_already_charging_is_not_resumed(self):
        self.before.update(charging_status='charging',power_kw=7)
        self.assertEqual(classify(self.records(dict(self.before,vehicle_timestamp=self.t+20)))['effect'],'请求前已在充电')

    def test_failure_does_not_become_success(self):
        self.assertEqual(classify([row('request_started',self.t,before=self.before),row('rate_limited',self.t+1)])['request'],'请求失败或结果未知')

    def test_after_departure_never_counts_as_on_time(self):
        at=datetime(2026,10,13,7,1,tzinfo=timezone.utc).timestamp()
        r=row('summary_snapshot',at,snapshot=dict(soc=100,vehicle_timestamp=at))
        report=night_report([r],'2026-10-13','08:00')
        self.assertEqual(report['completion'],'数据不足，无法确认按时完成')

    def test_no_records_are_not_charge_failure(self):
        report=night_report([],'2026-10-13')
        self.assertFalse(report['has_records'])
        self.assertIn('无法确认',report['completion'])

    def test_real_morning_replay(self):
        path=Path('/private/tmp/porsche-20261013-replay.json')
        if not path.exists():self.skipTest('Private live replay sample not present')
        report=night_report(json.loads(path.read_text()),'2026-10-13')
        self.assertEqual(report['items']['2026-10-13|01:00']['effect'],'十分钟内未观察到恢复')
        self.assertEqual(report['items']['2026-10-13|03:00']['effect'],'观察到暂停后开始充电')

    def test_legacy_monthly_retention_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Audit(tmp)
            old=row('inspection_no_request',self.t-91*86400)
            a.legacy.write_text(json.dumps(old)+'\n')
            new=row('request_started',self.t,before=self.before);a.append(new)
            self.assertEqual(len(a.read()),2)
            a.prune(self.t)
            self.assertEqual(a.read(),[new])
            self.assertEqual(a.directory.stat().st_mode & 0o777,0o700)
            a.legacy.write_text('invalid\n')
            with self.assertRaises(ValueError):a.read()
            self.assertEqual(a.legacy.read_text(),'invalid\n')


if __name__=='__main__':unittest.main()
