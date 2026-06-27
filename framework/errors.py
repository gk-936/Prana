from __future__ import annotations


class FrameworkError(Exception):
    """Base class for all framework errors."""


class ProviderError(FrameworkError):
    """An LLM provider call failed."""


class ToolError(FrameworkError):
    """A tool failed to execute."""


class PermissionDeniedError(FrameworkError):
    """The user lacks permission to run a tool."""


class MessagingError(FrameworkError):
    """A messaging channel failed to deliver."""


class ConfigError(FrameworkError):
    """Invalid or missing configuration."""
