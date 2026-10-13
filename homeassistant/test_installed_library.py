"""Run inside the HA Core container; all HTTP traffic uses MockTransport.

Checks that the actual pinned library cannot retry a guarded failing request.
"""
import asyncio
import sys
import json
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from pyporscheconnectapi.connection import Connection
from pyporscheconnectapi.remote_services import RemoteServices

sys.path.insert(0,"/config/custom_components")
from porsche_wake_guard import REQUEST_FAILURES, ObservedFailure, stop_library_retry, retry_deadline
from porsche_wake_guard.direct_control import COMMAND_RECEIPTS,capture_command_receipt,DirectRejected


async def main():
    for status in (401,429,503):
        calls=[]
        async def response(request):
            calls.append(request.method)
            return httpx.Response(status,headers={"Retry-After":"172800"},json={"test":True})
        async def valid(token):pass
        async with httpx.AsyncClient(transport=httpx.MockTransport(response),event_hooks={"response":[stop_library_retry]}) as client:
            connection=object.__new__(Connection)
            connection.token_lock=asyncio.Lock()
            connection.oauth2_client=SimpleNamespace(ensure_valid_token=valid)
            connection.token=SimpleNamespace(access_token="fake-test-token")
            connection.headers={}
            connection.asyncClient=client
            token=REQUEST_FAILURES.set([])
            try:
                try:await connection.request("GET","/test?wakeUpJob=offline-test")
                except ObservedFailure as exc:
                    assert exc.status_code==status
                    assert retry_deadline(exc,100)==172900
                else:raise AssertionError("Failure was swallowed")
            finally:REQUEST_FAILURES.reset(token)
        assert len(calls)==1, calls
        print(f"HTTP {status}: exactly one mocked request, sanitized error, Retry-After preserved")

    for scenario in ('performed','rejected','http_503'):
        calls=[];cached=[]
        async def response(request):
            calls.append(request.method)
            if request.method=='POST':
                assert json.loads(request.content)=={'key':'DIRECT_CHARGING_STOP','payload':{'spin':None}}
                if scenario=='http_503':return httpx.Response(503,json={})
                if scenario=='rejected':return httpx.Response(200,json={'status':{'result':'ERROR','details':'private'}})
                return httpx.Response(200,json={'status':{'result':'ACCEPTED','id':'offline-test'}})
            return httpx.Response(200,json={'status':{'result':'PERFORMED'}})
        async def valid(token):pass
        async def cache():cached.append(1)
        async def no_wait(*a):pass
        async with httpx.AsyncClient(transport=httpx.MockTransport(response),event_hooks={'response':[stop_library_retry,capture_command_receipt]}) as client:
            connection=object.__new__(Connection);connection.token_lock=asyncio.Lock()
            connection.oauth2_client=SimpleNamespace(ensure_valid_token=valid)
            connection.token=SimpleNamespace(access_token='fake-test-token');connection.headers={};connection.asyncClient=client
            remote=object.__new__(RemoteServices);remote._connection=connection
            remote._vehicle=SimpleNamespace(vin='offline-test',get_stored_overview=cache)
            receipts=[];token=REQUEST_FAILURES.set([]);command_token=COMMAND_RECEIPTS.set(receipts)
            try:
                with patch('pyporscheconnectapi.remote_services.asyncio.sleep',no_wait):
                    try:await remote.direct_charge_off()
                    except (DirectRejected,ObservedFailure) as exc:
                        assert scenario!='performed';assert 'private' not in str(exc)
                    else:assert scenario=='performed'
            finally:
                REQUEST_FAILURES.reset(token);COMMAND_RECEIPTS.reset(command_token)
        assert calls.count('POST')==1
        if scenario=='performed':assert receipts==['ACCEPTED','PERFORMED'] and len(cached)==1
        else:assert len(calls)==1 and not cached
        print(f'Direct stop {scenario}: exactly one mocked STOP command; no real vehicle traffic')


asyncio.run(main())
