import pytest
from framework.errors import (
    FrameworkError, ProviderError, ToolError,
    PermissionDeniedError, MessagingError, ConfigError,
)

@pytest.mark.parametrize("exc", [
    ProviderError, ToolError, PermissionDeniedError, MessagingError, ConfigError,
])
def test_all_errors_subclass_framework_error(exc):
    assert issubclass(exc, FrameworkError)
    with pytest.raises(FrameworkError):
        raise exc("boom")
