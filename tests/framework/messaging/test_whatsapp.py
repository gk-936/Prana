import asyncio
import httpx
import respx
from framework.messaging.whatsapp import WhatsAppChannel
from framework.messaging.base import OutboundMessage


@respx.mock
def test_whatsapp_sends_and_parses_id():
    respx.post("https://graph.facebook.com/v20.0/PNID/messages").mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "wamid.123"}]})
    )
    ch = WhatsAppChannel(access_token="tok", phone_number_id="PNID")
    res = asyncio.run(ch.send(OutboundMessage(recipient="+919900", body="hi")))
    assert res.ok and res.provider_message_id == "wamid.123"
