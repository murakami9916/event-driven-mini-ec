class ApplicationError(Exception):
    pass


class IdempotencyConflict(ApplicationError):
    pass


class NotFound(ApplicationError):
    pass


class UnsupportedEvent(ApplicationError):
    pass

