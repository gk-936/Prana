import asyncio
import httpx
import respx
from framework.messaging.whatsapp import TwilioWhatsAppChannel
from framework.messaging.base import OutboundMessage


@respx.mock
def test_twilio_sends_and_parses_id():
    respx.post(
        "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    ).mock(return_value=httpx.Response(200, json={"sid": "SM123"}))

    ch = TwilioWhatsAppChannel(
        account_sid="ACtest", auth_token="tok",
        from_number="whatsapp:+14155238886",
    )
    res = asyncio.run(ch.send(OutboundMessage(recipient="+919900", body="hi")))
    assert res.ok and res.provider_message_id == "SM123"


@respx.mock
def test_twilio_prefixes_bare_recipient():
    route = respx.post(
        "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    ).mock(return_value=httpx.Response(200, json={"sid": "SM124"}))

    ch = TwilioWhatsAppChannel(
        account_sid="ACtest", auth_token="tok",
        from_number="whatsapp:+14155238886",
    )
    asyncio.run(ch.send(OutboundMessage(recipient="+919900", body="hi")))
    sent_body = route.calls[0].request.content.decode()
    assert "To=whatsapp%3A%2B919900" in sent_body


@respx.mock
def test_twilio_does_not_double_prefix_recipient():
    route = respx.post(
        "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    ).mock(return_value=httpx.Response(200, json={"sid": "SM125"}))

    ch = TwilioWhatsAppChannel(
        account_sid="ACtest", auth_token="tok",
        from_number="whatsapp:+14155238886",
    )
    asyncio.run(
        ch.send(OutboundMessage(recipient="whatsapp:+919900", body="hi"))
    )
    sent_body = route.calls[0].request.content.decode()
    assert "To=whatsapp%3A%2B919900" in sent_body
    assert "whatsapp%3Awhatsapp" not in sent_body
