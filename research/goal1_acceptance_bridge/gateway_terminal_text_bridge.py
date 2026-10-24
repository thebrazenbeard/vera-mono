"""PR95 gateway terminal -> networkless-QVR text acceptance (research only)."""

class GatewayTextHold(RuntimeError):
    pass

class CapturingBackend:
    def __init__(self, delegate):
        self.delegate=delegate
        self.observations=[]
    def generate(self, prompt: str, *, model: str, max_tokens: int):
        observation=self.delegate.generate(prompt,model=model,max_tokens=max_tokens)
        self.observations.append(observation)
        return observation

class GatewayTerminalTextBridge:
    def __init__(self, **kwargs):
        self.kwargs=kwargs
    def __call__(self, prompt: str, *, model: str, model_digest: str, max_tokens: int) -> dict:
        raise NotImplementedError('signed terminal checked text delivery is not implemented')
