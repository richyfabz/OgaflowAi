class DomainError(ValueError):
    """Reject an unsafe business operation with a stable reason code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
