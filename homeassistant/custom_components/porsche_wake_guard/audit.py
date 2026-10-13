"""Private monthly JSONL audit with exact 90-day retention and legacy reading."""
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from .evidence import epoch


class Audit:
    def __init__(self,root):
        self.root=Path(root)
        self.directory=self.root/'porsche_wake_audit'
        self.legacy=self.root/'porsche_wake_audit.jsonl'

    def paths(self):
        return ([self.legacy] if self.legacy.exists() else [])+sorted(self.directory.glob('????-??.jsonl'))

    def read(self):
        rows=[]
        for path in self.paths():
            for line in path.read_text().splitlines():
                if not line.strip():continue
                row=json.loads(line)
                if not isinstance(row,dict) or epoch(row.get('utc')) is None:raise ValueError('Invalid audit record')
                rows.append(row)
        return sorted(rows,key=lambda r:r['utc'])

    def append(self,row):
        self.directory.mkdir(mode=0o700,exist_ok=True)
        path=self.directory/(row['utc'][:7]+'.jsonl')
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600),'a') as f:
            f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())

    def prune(self,now):
        cutoff=now-90*86400
        for path in self.paths():
            lines=path.read_text().splitlines()
            keep=[]
            for line in lines:
                if not line.strip():continue
                row=json.loads(line);stamp=epoch(row.get('utc'))
                if stamp is None:raise ValueError('Invalid audit timestamp')
                if stamp>=cutoff:keep.append(line)
            if len(keep)==len(lines):continue
            temp=path.with_suffix('.tmp')
            with os.fdopen(os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:
                f.write(''.join(line+'\n' for line in keep));f.flush();os.fsync(f.fileno())
            os.replace(temp,path)
