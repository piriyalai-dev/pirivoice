class NotFoundError(Exception):
    """Raised when a resource is not found."""
    pass

class ForbiddenError(Exception):
    """Raised when a user does not have permission."""
    pass

class ValidationError(Exception):
    """Raised when data validation fails."""
    pass

class ConflictError(Exception):
    """Raised when an operation conflicts with existing data (e.g. duplicate)."""
    pass

class ServiceUnavailableError(Exception):
    """Raised when a dependency (e.g. Redis queue) is temporarily unavailable."""
    pass

class PayloadTooLargeError(Exception):
    """Raised when an uploaded file exceeds the configured size limit (→ 413)."""
    pass

class RateLimitError(Exception):
    """Raised when a user exceeds an allowed rate (e.g. images per hour) (→ 429)."""
    pass
