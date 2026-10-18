"""Session cleanup and explicit transaction ownership."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from svaar.db import get_session


@pytest.mark.parametrize("failed", [False, True])
def test_session_context_closes_without_implicit_commit(failed: bool) -> None:
    context = Mock()
    session = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_factory=Mock(return_value=context)))
    )
    dependency = get_session(request)
    assert next(dependency) is session
    if failed:
        with pytest.raises(RuntimeError):
            dependency.throw(RuntimeError("request failed"))
    else:
        with pytest.raises(StopIteration):
            next(dependency)
    context.__exit__.assert_called_once()
    session.commit.assert_not_called()
