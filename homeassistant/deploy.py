"""Install task assets via existing PVE Guest Agent. No credentials are read.

Usage: python3 homeassistant/deploy.py /path/to/extracted/porscheconnect
"""
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

root=Path(__file__).parent
release=Path(sys.argv[1])
assert json.loads((release/"manifest.json").read_text())["version"] == "0.1.11"
buffer=io.BytesIO()
with tarfile.open(fileobj=buffer,mode="w:gz") as tar:
    for path in sorted(release.rglob("*")):
        if path.is_file():tar.add(path,arcname="custom_components/porscheconnect/"+str(path.relative_to(release)))
    for path in sorted((root/"custom_components").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            tar.add(path,arcname=str(path.relative_to(root)))
    for rel in ("packages/porsche_wake.yaml","porsche_wake_dashboard.yaml"):
        tar.add(root/rel,arcname=rel)
encoded=base64.b64encode(buffer.getvalue()).decode()
script="""set -eu
docker exec -i homeassistant python3 - <<'PY'
import base64,io,tarfile,pathlib,os
p=pathlib.Path('/config')
c=p/'configuration.yaml'
text=c.read_text()
keys={l.split(':')[0] for l in text.splitlines() if l and not l.startswith((' ','#'))}
assert not keys.intersection({'homeassistant','lovelace','recorder','logger'}), 'Existing sections require reviewed merge'
assert not (p/'custom_components/porscheconnect').exists(), 'Preserve existing integration'
backup=p/'configuration.yaml.pre-porsche-20261012'
assert not backup.exists(), 'Do not overwrite rollback copy'
backup.write_text(text);backup.chmod(0o600)
with tarfile.open(fileobj=io.BytesIO(base64.b64decode('PAYLOAD')),mode='r:gz') as t:
 t.extractall(p,filter='data')
text+='''
# Porsche wake trial: keep existing configuration above intact.
homeassistant:
  packages: !include_dir_named packages
recorder:
  purge_keep_days: 30
logger:
  logs:
    custom_components.porscheconnect: critical
    pyporscheconnectapi: critical
lovelace:
  dashboards:
    porsche-wake:
      mode: yaml
      title: Porsche 唤醒试验
      icon: mdi:car-clock
      show_in_sidebar: true
      filename: porsche_wake_dashboard.yaml
'''
c.write_text(text)
print('Installed Porsche Connect 0.1.11, wake guard, package and dashboard; master remains off')
PY
ha core check --raw-json
""".replace('PAYLOAD',encoded)
r=subprocess.run(['ssh','-o','BatchMode=yes','root@192.168.1.200',
    'qm guest exec 105 --timeout 30 --pass-stdin -- /bin/sh'],input=script,text=True,capture_output=True)
print(r.stdout)
if r.returncode:print(r.stderr);sys.exit(r.returncode)
