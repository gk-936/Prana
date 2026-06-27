import asyncio
import pytest
from framework.messaging.base import OutboundMessage, MessageChannel
from framework.messaging.mock import MockChannel
from framework.messaging.registry import MessagingRegistry
from framework.errors import MessagingError


def test_mock_channel_records_and_acks():
    ch = MockChannel()
    res = asyncio.run(ch.send(OutboundMessage(recipient="+1", body="hi")))
    assert res.ok and ch.sent[0].body == "hi"


def test_mock_satisfies_protocol():
    assert isinstance(MockChannel(), MessageChannel)


def test_registry_routes_to_named_channel():
    reg = MessagingRegistry(); reg.add(MockChannel())
    res = asyncio.run(reg.send(channel="mock", recipient="+1", body="yo"))
    assert res.ok


def test_registry_unknown_channel_raises():
    with pytest.raises(MessagingError):
        asyncio.run(MessagingRegistry().send(channel="nope", recipient="+1", body="x"))
