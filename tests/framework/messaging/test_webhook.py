import asyncio
import httpx
import respx
from framework.messaging.webhook import WebhookChannel
from framework.messaging.base import OutboundMessage


@respx.mock
def test_webhook_sends_success():
    route = respx.post("https://example.com/hook").mock(
        return_value=httpx.Response(200, json={"status": "received"})
    )
    ch = WebhookChannel(url="https://example.com/hook")
    res = asyncio.run(ch.send(OutboundMessage(recipient="+919900", body="hi")))

    assert res.ok is True
    assert respx.calls.call_count == 1
    sent_json = route.calls.last.request.read()
    import json
    payload = json.loads(sent_json)
    assert payload["recipient"] == "+919900"
    assert payload["body"] == "hi"


@respx.mock
def test_webhook_http_error_returns_failed_result():
    respx.post("https://example.com/hook").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    ch = WebhookChannel(url="https://example.com/hook")
    res = asyncio.run(ch.send(OutboundMessage(recipient="+919900", body="hi")))

    assert res.ok is False
    assert res.error is not None
