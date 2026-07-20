class ControlPlaneError(Exception):
    """Base control-plane exception."""


class ProviderUnavailable(ControlPlaneError):
    """Raised when a model provider cannot serve a request."""


class PolicyDenied(ControlPlaneError):
    """Raised when a requested operation violates policy."""


class InvalidTransition(ControlPlaneError):
    """Raised when a task state transition is not permitted."""
