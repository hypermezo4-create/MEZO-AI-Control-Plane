class ApplicationError(Exception):
    code = "application_error"


class NotFoundError(ApplicationError):
    code = "not_found"


class ConflictError(ApplicationError):
    code = "conflict"


class InvalidTransitionError(ApplicationError):
    code = "invalid_transition"


class AuthorizationError(ApplicationError):
    code = "authorization_denied"


class DependencyUnavailableError(ApplicationError):
    code = "dependency_unavailable"
