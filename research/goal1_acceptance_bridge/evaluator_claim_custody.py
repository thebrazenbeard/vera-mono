"""Isolated evaluator-owned claim and readback service (experimental only)."""
class ClaimDenied(RuntimeError):
    pass
class CustodyLedger:
    def __init__(self,*args,**kwargs): raise NotImplementedError("durable custody not implemented")
class ClaimEvidenceReader:
    def __init__(self,*args,**kwargs): raise NotImplementedError("independent readback not implemented")
def serve_mtls(*args,**kwargs): raise NotImplementedError("authenticated service not implemented")
