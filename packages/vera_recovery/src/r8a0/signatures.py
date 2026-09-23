"""Verification-only RSA PKCS#1 v1.5 signatures for bounded R8A0 evidence."""
from __future__ import annotations
import hashlib
from typing import Any, Mapping
from .canonical import canonical_bytes
_DER_SHA256=bytes.fromhex('3031300d060960864801650304020105000420')

def _public_key(key:Mapping[str,Any])->tuple[str,int,int]:
 if set(key)!={'key_id','n_hex','e'}: raise ValueError('public key fields are missing or unknown')
 key_id=str(key['key_id']);n=int(str(key['n_hex']),16);e=int(key['e'])
 if not key_id or n.bit_length()<1024 or e<3: raise ValueError('invalid public key')
 return key_id,n,e

def verify_signature(payload:Any,signature_hex:str,key:Mapping[str,Any])->bool:
 try:
  _,n,e=_public_key(key);k=(n.bit_length()+7)//8;s=int(signature_hex,16)
  if s<=0 or s>=n:return False
  em=pow(s,e,n).to_bytes(k,'big');digest=hashlib.sha256(canonical_bytes(payload)).digest();tail=_DER_SHA256+digest
  if len(tail)+11>k:return False
  return em==b'\x00\x01'+b'\xff'*(k-len(tail)-3)+b'\x00'+tail
 except (ValueError,TypeError,OverflowError):return False

def public_key_id(key:Mapping[str,Any])->str:return _public_key(key)[0]
