class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class KeitaroError(AppError):
    def __init__(self, message: str, upstream_status: int | None = None, uncertain: bool = False):
        super().__init__("keitaro_error", message, 502)
        self.upstream_status = upstream_status
        self.uncertain = uncertain
