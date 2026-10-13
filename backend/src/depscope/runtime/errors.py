"""Safe domain errors; messages must never contain credentials or raw provider replies."""


class DomainError(Exception):
    def __init__(self, code: str, message: str, pointers: tuple[str, ...] = (),
                 retryable: bool = False):
        self.code = code
        self.message = message
        self.pointers = pointers
        self.retryable = retryable
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message,
                "pointers": list(self.pointers), "retryable": self.retryable}
