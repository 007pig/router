#!/usr/bin/env bash
set -euo pipefail
# Preserve master/automation state; change only the user's schedule and limits.
python3 "$(dirname "$0")/guest.py" <<'GUEST'
docker exec -i homeassistant python3 - <<'PY'
import os,asyncio,aiohttp
async def main():
 async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=os.environ['SUPERVISOR_CORE_API_SOCKET'])) as s:
  async def call(domain,name,data):
   async with s.post(f'http://localhost/api/services/{domain}/{name}',json=data) as r:
    assert r.status==200,(domain,name,r.status)
  for i,hour in enumerate((1,3,5,7,9),1):
   await call('input_datetime','set_datetime',{'entity_id':f'input_datetime.porsche_wake_time_{i}','time':f'{hour:02d}:00:00'})
   await call('input_boolean','turn_on' if i<=4 else 'turn_off',{'entity_id':f'input_boolean.porsche_wake_slot_{i}'})
  for key,value in [('target_soc',100),('interval_minutes',120),('daily_limit',4)]:
   await call('input_number','set_value',{'entity_id':'input_number.porsche_wake_'+key,'value':value})
  print('Schedule saved: Europe/Dublin 01:00,03:00,05:00,07:00; 120m; 4/day')
asyncio.run(main())
PY
GUEST
