class AIError(Exception):
    """Base exception for AI-related failures."""


class QuotaExhaustedError(AIError):
    """Provider/model quota exhausted or rate limited across all keys/models."""


class ModelTimeoutError(AIError):
    """A model call exceeded the allowed time budget."""


class NoSuitableModelError(AIError):
    """No model exists that can satisfy required capabilities."""
