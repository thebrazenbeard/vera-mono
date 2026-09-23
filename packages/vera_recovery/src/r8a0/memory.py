"""Governed memory with external policy signatures and CAS store heads."""
from __future__ import annotations
import fcntl,hashlib,hmac,os,tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Mapping
from .canonical import canonical_bytes,canonical_dumps,canonical_sha256,strict_loads
from .signatures import public_key_id,verify_signature
class MemoryAdmissionError(ValueError):pass
class StaleMemoryHead(MemoryAdmissionError):pass
class MemoryClass(str,Enum):AUTOBIOGRAPHICAL='AUTOBIOGRAPHICAL';WORKING_PROJECT='WORKING_PROJECT';HISTORICAL_AUDIT='HISTORICAL_AUDIT'
READBACK_PREFIX={MemoryClass.AUTOBIOGRAPHICAL:'I remember this through my persistent memory.',MemoryClass.WORKING_PROJECT:'I have this in my working or project memory.',MemoryClass.HISTORICAL_AUDIT:'The historical or audit record shows this.'}
def _key(k:bytes)->bytes:
 if not isinstance(k,bytes) or len(k)<16:raise MemoryAdmissionError('store integrity key must contain at least 16 bytes')
 return k
def _mac(k:bytes,v:Any)->str:return hmac.new(k,canonical_bytes(v),hashlib.sha256).hexdigest()
@dataclass(frozen=True)
class AdmissionRequest:
 record_id:str;text:str;memory_class:MemoryClass;source_actor:str;provenance:str;operation_id:str;authority_binding_id:str;privacy_binding_id:str;project_id:str;governed_identity_id:str;status:str='CURRENT';supersedes:str|None=None
 def payload(self)->dict[str,Any]:return {'record_id':self.record_id,'text':self.text,'memory_class':self.memory_class.value,'source_actor':self.source_actor,'provenance':self.provenance,'operation_id':self.operation_id,'authority_binding_id':self.authority_binding_id,'privacy_binding_id':self.privacy_binding_id,'project_id':self.project_id,'governed_identity_id':self.governed_identity_id,'supersedes':self.supersedes}
 def request_digest(self)->str:return canonical_sha256(self.payload())
class GovernedMemoryStore:
 def __init__(self,path:str|Path,*,authority_registry:Mapping[str,Mapping],privacy_registry:Mapping[str,Mapping],trusted_policy_keys:Mapping[str,Mapping],expected_registry_heads:Mapping[str,str],store_integrity_key:bytes,expected_project_id:str,expected_identity_id:str):
  self.path=Path(path);self.lock_path=self.path.with_suffix(self.path.suffix+'.lock');self.authority_registry=dict(authority_registry);self.privacy_registry=dict(privacy_registry);self.policy_keys=dict(trusted_policy_keys);self.registry_heads=dict(expected_registry_heads);self.store_key=_key(store_integrity_key);self.project=expected_project_id;self.identity=expected_identity_id
  if not self.project or not self.identity or set(self.registry_heads)!={'authority','privacy'}:raise MemoryAdmissionError('project, identity, and registry heads are required')
 @staticmethod
 def _without(m:Mapping[str,Any],*keys:str)->dict[str,Any]:return {k:v for k,v in m.items() if k not in set(keys)}
 def _genesis(self)->dict[str,Any]:return self._seal_store({'schema':'VERA_R8A0_GOVERNED_MEMORY_STORE_V4','generation':0,'predecessor_head':'0'*64,'records':[],'operations':{}})
 def _seal_store(self,body:Mapping[str,Any])->dict[str,Any]:
  b=dict(body);head=canonical_sha256(b);a=b|{'head_digest':head};return a|{'head_mac':_mac(self.store_key,a)}
 def _verify_store(self,data:Mapping[str,Any])->None:
  if set(data)!={'schema','generation','predecessor_head','records','operations','head_digest','head_mac'} or data['schema']!='VERA_R8A0_GOVERNED_MEMORY_STORE_V4':raise MemoryAdmissionError('invalid memory store schema or fields')
  a=self._without(data,'head_mac');b=self._without(data,'head_digest','head_mac')
  if not hmac.compare_digest(str(data['head_mac']),_mac(self.store_key,a)) or data['head_digest']!=canonical_sha256(b):raise MemoryAdmissionError('memory store head authentication mismatch')
  if not isinstance(data['generation'],int) or data['generation']<0 or not isinstance(data['records'],list) or not isinstance(data['operations'],dict):raise MemoryAdmissionError('invalid memory store containers')
 def _verify_graph(self,data:Mapping[str,Any])->None:
  records=list(data['records']);operations=dict(data['operations']);record_ops=[]
  for record in records:self._verify_record(record);record_ops.append(str(record.get('operation_id','')))
  if len(record_ops)!=len(set(record_ops)) or set(record_ops)!=set(operations):raise MemoryAdmissionError('memory store record-operation graph mismatch')
  for operation_id,operation in operations.items():self._verify_operation(operation_id,operation,str(operation.get('request_digest','')),records,require_current=False)
 def _read_unlocked(self)->dict[str,Any]:
  if not self.path.exists():return self._genesis()
  d=strict_loads(self.path.read_bytes());self._verify_store(d);self._verify_graph(d);return d
 def current_head(self)->str:return self._read_unlocked()['head_digest']
 def _write_unlocked(self,data:dict[str,Any])->None:
  self.path.parent.mkdir(parents=True,exist_ok=True)
  fd,name=tempfile.mkstemp(prefix=self.path.name+'.',suffix='.tmp',dir=self.path.parent);os.close(fd);tmp=Path(name)
  try:tmp.write_text(canonical_dumps(data),encoding='utf-8');os.replace(tmp,self.path)
  finally:
   if tmp.exists():tmp.unlink()
  r=strict_loads(self.path.read_bytes());self._verify_store(r)
  if r['head_digest']!=data['head_digest']:raise MemoryAdmissionError('memory store write readback mismatch')
 def _binding(self,registry:Mapping[str,Mapping],binding_id:str,request_digest:str,kind:str)->dict[str,Any]:
  raw=registry.get(binding_id)
  if raw is None:raise MemoryAdmissionError(f'unknown {kind} binding')
  x=dict(raw);fields={'binding_id','request_digest','source','source_digest','decision','kind','registry_head_digest','issuer','key_id','signature'}
  if set(x)!=fields:raise MemoryAdmissionError(f'invalid {kind} binding fields')
  sig=x.pop('signature');issuer=str(x['issuer']);pk=self.policy_keys.get(issuer)
  if pk is None or public_key_id(pk)!=x['key_id'] or not verify_signature(x,sig,pk):raise MemoryAdmissionError(f'invalid {kind} binding signature')
  if x['kind']!=kind or x['binding_id']!=binding_id or x['request_digest']!=request_digest:raise MemoryAdmissionError(f'{kind} binding mismatch')
  if x['registry_head_digest']!=self.registry_heads[kind]:raise MemoryAdmissionError(f'{kind} registry head mismatch')
  if len(str(x['source_digest']))!=64:raise MemoryAdmissionError(f'invalid {kind} source digest')
  expected='AUTHORIZED' if kind=='authority' else 'ELIGIBLE'
  if x['decision']!=expected:raise MemoryAdmissionError(f'{kind} binding denies admission')
  return x
 def _seal_record(self,body:Mapping[str,Any])->dict[str,Any]:
  b=dict(body);ad=canonical_sha256(self._without(b,'status','superseded_by','admission_digest','record_digest','record_mac'));b['admission_digest']=ad;rd=canonical_sha256(b);a=b|{'record_digest':rd};return a|{'record_mac':_mac(self.store_key,a)}
 def _verify_record(self,r:Mapping[str,Any])->None:
  if r.get('project_id')!=self.project or r.get('governed_identity_id')!=self.identity:raise MemoryAdmissionError('persistent-memory project or identity mismatch')
  a=self._without(r,'record_mac');b=self._without(r,'record_digest','record_mac')
  if not hmac.compare_digest(str(r.get('record_mac','')),_mac(self.store_key,a)) or r.get('record_digest')!=canonical_sha256(b):raise MemoryAdmissionError('persistent-memory record authentication mismatch')
  keys={'record_id','text','memory_class','source_actor','provenance','operation_id','authority_binding_id','privacy_binding_id','project_id','governed_identity_id','supersedes'};req=canonical_sha256({k:r[k] for k in keys})
  if r.get('request_digest')!=req:raise MemoryAdmissionError('persistent-memory request digest mismatch')
  self._binding(self.authority_registry,str(r['authority_binding_id']),req,'authority');self._binding(self.privacy_registry,str(r['privacy_binding_id']),req,'privacy')
 def _seal_receipt(self,b:Mapping[str,Any])->dict[str,Any]:
  x=dict(b);return x|{'receipt_mac':_mac(self.store_key,x)}
 def _verify_receipt(self,r:Mapping[str,Any],request_digest:str,operation_id:str)->None:
  b=self._without(r,'receipt_mac')
  if not hmac.compare_digest(str(r.get('receipt_mac','')),_mac(self.store_key,b)):raise MemoryAdmissionError('admission receipt authentication mismatch')
  if r.get('schema')!='VERA_R8A0_GOVERNED_MEMORY_ADMISSION_RECEIPT_V1' or r.get('operation_id')!=operation_id or r.get('request_digest')!=request_digest:raise MemoryAdmissionError('admission receipt binding mismatch')
  if r.get('project_id')!=self.project or r.get('governed_identity_id')!=self.identity:raise MemoryAdmissionError('admission receipt project or identity mismatch')
  MemoryClass(r['memory_class'])
 def _seal_operation(self,digest:str,receipt:Mapping[str,Any])->dict[str,Any]:
  b={'request_digest':digest,'receipt':dict(receipt)};return b|{'operation_mac':_mac(self.store_key,b)}
 def _verify_operation(self,opid:str,op:Mapping[str,Any],digest:str,records:list[Mapping],require_current:bool=True)->dict[str,Any]:
  b=self._without(op,'operation_mac')
  if set(op)!={'request_digest','receipt','operation_mac'} or not hmac.compare_digest(str(op.get('operation_mac','')),_mac(self.store_key,b)) or op.get('request_digest')!=digest:raise MemoryAdmissionError('operation replay authentication mismatch')
  receipt=dict(op['receipt']);self._verify_receipt(receipt,digest,opid);record=next((r for r in records if r.get('record_id')==receipt.get('record_id')),None)
  if record is None:raise MemoryAdmissionError('operation replay record is missing')
  self._verify_record(record)
  if require_current and record.get('status')!='CURRENT':raise MemoryAdmissionError('operation replay record is not current')
  for k in ('operation_id','request_digest','admission_digest','memory_class','identity_owner','runtime_owner','project_id','governed_identity_id'):
   if record.get(k)!=receipt.get(k):raise MemoryAdmissionError('operation replay receipt-to-record binding mismatch')
  return receipt
 def admit(self,request:AdmissionRequest,*,expected_store_head:str)->dict[str,Any]:
  if request.project_id!=self.project or request.governed_identity_id!=self.identity:raise MemoryAdmissionError('memory request project or identity mismatch')
  if request.status!='CURRENT':raise MemoryAdmissionError('only CURRENT records may be admitted')
  self.lock_path.parent.mkdir(parents=True,exist_ok=True)
  with self.lock_path.open('a+b') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);data=self._read_unlocked();digest=request.request_digest()
   if request.operation_id in data['operations']:
    receipt=self._verify_operation(request.operation_id,data['operations'][request.operation_id],digest,data['records']);return receipt|{'store_head':data['head_digest']}
   if data['head_digest']!=expected_store_head:raise StaleMemoryHead('stale expected memory store head')
   auth=self._binding(self.authority_registry,request.authority_binding_id,digest,'authority');priv=self._binding(self.privacy_registry,request.privacy_binding_id,digest,'privacy')
   byid={r['record_id']:r for r in data['records']}
   if request.record_id in byid:raise MemoryAdmissionError('record ID already exists')
   if request.supersedes:
    old=byid.get(request.supersedes)
    if not old or old.get('status')!='CURRENT':raise MemoryAdmissionError('supersession predecessor missing or non-current')
    self._verify_record(old);body=self._without(old,'record_digest','record_mac');body['status']='SUPERSEDED';body['superseded_by']=request.record_id;old.clear();old.update(self._seal_record(body))
   owner='VERA' if request.memory_class is MemoryClass.AUTOBIOGRAPHICAL else 'PROJECT_RECORD'
   body=request.payload()|{'status':'CURRENT','identity_owner':owner,'runtime_owner':False,'request_digest':digest,'authority_source':auth['source'],'authority_source_digest':auth['source_digest'],'privacy_source':priv['source'],'privacy_source_digest':priv['source_digest'],'superseded_by':None}
   record=self._seal_record(body);data['records'].append(record)
   receipt=self._seal_receipt({'schema':'VERA_R8A0_GOVERNED_MEMORY_ADMISSION_RECEIPT_V1','operation_id':request.operation_id,'record_id':request.record_id,'memory_class':request.memory_class.value,'identity_owner':owner,'runtime_owner':False,'request_digest':digest,'admission_digest':record['admission_digest'],'authority_binding_id':request.authority_binding_id,'privacy_binding_id':request.privacy_binding_id,'project_id':request.project_id,'governed_identity_id':request.governed_identity_id,'result':'ADMITTED'})
   data['operations'][request.operation_id]=self._seal_operation(digest,receipt);new=self._seal_store({'schema':data['schema'],'generation':data['generation']+1,'predecessor_head':data['head_digest'],'records':data['records'],'operations':data['operations']});self._write_unlocked(new);return receipt|{'store_head':new['head_digest']}
 def readback(self,record_id:str,*,expected_store_head:str)->str:
  data=self._read_unlocked()
  if data['head_digest']!=expected_store_head:raise StaleMemoryHead('memory store head mismatch')
  r=next((x for x in data['records'] if x['record_id']==record_id),None)
  if not r:raise KeyError(record_id)
  self._verify_record(r)
  if r['status']!='CURRENT':raise MemoryAdmissionError('record is not current')
  return f"{READBACK_PREFIX[MemoryClass(r['memory_class'])]} {r['text']}"
 def verify_head(self,expected_store_head:str)->str:
  data=self._read_unlocked()
  if data['head_digest']!=expected_store_head:raise StaleMemoryHead('memory store head mismatch')
  for r in data['records']:self._verify_record(r)
  for opid,op in data['operations'].items():self._verify_operation(opid,op,op['request_digest'],data['records'],False)
  return data['head_digest']
