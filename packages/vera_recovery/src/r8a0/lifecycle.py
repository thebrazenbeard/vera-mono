"""Atomic one-successor lifecycle consumption registry."""
from __future__ import annotations
import fcntl,hashlib,hmac,os,tempfile
from pathlib import Path
from typing import Any
from .canonical import canonical_bytes,canonical_dumps,canonical_sha256,strict_loads
class LifecycleRegistryError(ValueError):pass
class StaleLifecycleHead(LifecycleRegistryError):pass
def _key(k:bytes)->bytes:
 if not isinstance(k,bytes) or len(k)<16:raise LifecycleRegistryError('lifecycle registry key must contain at least 16 bytes')
 return k
def _mac(k:bytes,v:Any)->str:return hmac.new(k,canonical_bytes(v),hashlib.sha256).hexdigest()
class LifecycleRegistry:
 def __init__(self,path:str|Path,key:bytes):self.path=Path(path);self.lock=self.path.with_suffix(self.path.suffix+'.lock');self.key=_key(key)
 def _seal(self,body:dict)->dict:
  head=canonical_sha256(body);a=body|{'head_digest':head};return a|{'head_mac':_mac(self.key,a)}
 def _genesis(self):return self._seal({'schema':'VERA_R8A0_LIFECYCLE_REGISTRY_V1','generation':0,'predecessor_head':'0'*64,'events':{}})
 def _read(self):
  d=self._genesis() if not self.path.exists() else strict_loads(self.path.read_bytes())
  if set(d)!={'schema','generation','predecessor_head','events','head_digest','head_mac'} or d['schema']!='VERA_R8A0_LIFECYCLE_REGISTRY_V1':raise LifecycleRegistryError('invalid lifecycle registry')
  a={k:v for k,v in d.items() if k!='head_mac'};b={k:v for k,v in d.items() if k not in {'head_digest','head_mac'}}
  if not hmac.compare_digest(str(d['head_mac']),_mac(self.key,a)) or d['head_digest']!=canonical_sha256(b):raise LifecycleRegistryError('lifecycle registry authentication mismatch')
  return d
 def current_head(self)->str:return self._read()['head_digest']
 def consume(self,*,termination_signature:str,checkpoint_signature:str,predecessor_runtime_id:str,successor_runtime_id:str,resumption_claim_digest:str,expected_head:str)->str:
  self.lock.parent.mkdir(parents=True,exist_ok=True)
  with self.lock.open('a+b') as f:
   fcntl.flock(f,fcntl.LOCK_EX);d=self._read()
   if d['head_digest']!=expected_head:raise StaleLifecycleHead('stale lifecycle registry head')
   if termination_signature in d['events']:raise LifecycleRegistryError('termination event already consumed')
   event={'termination_signature':termination_signature,'checkpoint_signature':checkpoint_signature,'predecessor_runtime_id':predecessor_runtime_id,'successor_runtime_id':successor_runtime_id,'resumption_claim_digest':resumption_claim_digest,'state':'CONSUMED'};events=dict(d['events']);events[termination_signature]=event;new=self._seal({'schema':d['schema'],'generation':d['generation']+1,'predecessor_head':d['head_digest'],'events':events});self.path.parent.mkdir(parents=True,exist_ok=True);fd,n=tempfile.mkstemp(prefix=self.path.name+'.',suffix='.tmp',dir=self.path.parent);os.close(fd);t=Path(n)
   try:t.write_text(canonical_dumps(new),encoding='utf-8');os.replace(t,self.path)
   finally:
    if t.exists():t.unlink()
   if self._read()['head_digest']!=new['head_digest']:raise LifecycleRegistryError('lifecycle registry write readback mismatch')
   return new['head_digest']
 def event(self,termination_signature:str)->dict|None:return self._read()['events'].get(termination_signature)
