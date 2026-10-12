"""Reconcile/verify only the three existing HA105 Zabbix monitoring objects.

ZABBIX_ADMIN_PASSWORD must be supplied through the existing secrets environment.
Never prints auth values, notification destinations or arbitrary API responses.
"""
import json
import os
import sys
import time
import urllib.request

URL="http://192.168.1.115:8080/api_jsonrpc.php"
token=None


def api(method, params):
    body=dict(jsonrpc="2.0",method=method,params=params,id=1)
    if token:body["auth"]=token
    req=urllib.request.Request(URL,json.dumps(body).encode(),{"Content-Type":"application/json-rpc"})
    data=json.load(urllib.request.urlopen(req,timeout=20))
    if "error" in data:raise RuntimeError("Zabbix API failed: "+method)
    return data["result"]


def one(items):
    assert len(items)==1, "Expected one exact object"
    return items[0]


token=api("user.login",dict(username="Admin",password=os.environ["ZABBIX_ADMIN_PASSWORD"]))
try:
    host=one(api("host.get",dict(output=["hostid","status"],filter={"host":["home-assistant"]})))
    web=one(api("httptest.get",dict(output=["httptestid","status"],hostids=[host["hostid"]],filter={"name":["Home Assistant HTTP"]})))
    http=one(api("trigger.get",dict(output=["triggerid","status","value","state"],hostids=[host["hostid"]],filter={"description":["home-assistant: Home Assistant HTTP is unavailable"]})))
    vm=one(api("item.get",dict(output=["itemid","lastvalue","lastclock","state"],host="Proxmox VE",filter={"key_":["proxmox.qemu.vmstatus[qemu/105]"]},selectTriggers=["triggerid","description","status","value","state"])))
    trigger=one([t for t in vm["triggers"] if t["description"].endswith(": Not running")])
    if sys.argv[1]=="provision":
        api("httptest.update",dict(httptestid=web["httptestid"],status=0))
        for t in (http,trigger):api("trigger.update",dict(triggerid=t["triggerid"],status=0))
        print("Enabled existing VM105 HTTP scenario and two triggers; no other objects changed")
    else:
        fail=one(api("item.get",dict(output=["lastvalue","lastclock","state"],hostids=[host["hostid"]],webitems=True,filter={"key_":["web.test.fail[Home Assistant HTTP]"]})))
        checks=dict(host_enabled=host["status"]=="0",web_enabled=web["status"]=="0",
            triggers_enabled=all(t["status"]=="0" for t in (http,trigger)),
            triggers_recovered=all(t["value"]=="0" and t["state"]=="0" for t in (http,trigger)),
            vm_running=vm["lastvalue"]=="running",http_success=fail["lastvalue"]=="0",
            fresh=all(int(t["lastclock"])>=time.time()-age and t["state"]=="0" for t,age in ((vm,900),(fail,300))))
        print('sample_age_seconds',{'vm':round(time.time()-int(vm['lastclock'])),'http':round(time.time()-int(fail['lastclock']))})
        print(json.dumps(checks))
        assert all(checks.values()), "HA monitoring acceptance incomplete"
finally:
    api("user.logout",[])
