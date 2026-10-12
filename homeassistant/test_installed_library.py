"""Run inside the HA Core container; all HTTP traffic uses MockTransport.

Checks that the actual pinned library cannot retry a guarded failing request.
"""
import asyncio
import sys
from types import SimpleNamespace
import httpx
from pyporscheconnectapi.connection import Connection

sys.path.insert(0,"/config/custom_components")
from porsche_wake_guard import REQUEST_FAILURES, ObservedFailure, stop_library_retry, retry_deadline


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


asyncio.run(main())
