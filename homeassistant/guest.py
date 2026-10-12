"""Run an explicitly supplied shell script in VM105 via PVE QEMU Guest Agent.

Caller must restrict output to nonsensitive status. Never use this to print config
entries, environment values, credentials or unfiltered diagnostics.
"""
import json
import subprocess
import sys

r=subprocess.run(['ssh','-o','BatchMode=yes','root@192.168.1.200',
    'qm guest exec 105 --timeout 30 --pass-stdin -- /bin/sh'],
    input=sys.stdin.read(),text=True,capture_output=True)
if r.returncode:
    print(r.stderr);sys.exit(r.returncode)
data=json.loads(r.stdout)
if not data.get('exited'):
    print(json.dumps(data));sys.exit(0)
print(data.get('out-data',''))
if data.get('err-data'):print(data['err-data'],file=sys.stderr)
sys.exit(data.get('exitcode',1))
