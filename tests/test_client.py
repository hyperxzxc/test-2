import httpx
import pytest

from app.config import Settings
from app.errors import KeitaroError
from app.keitaro import KeitaroClient


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 500, 503])
def test_write_errors_are_never_automatically_retried_or_leaked(status):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["Api-Key"] == "secret-not-for-browser"
        return httpx.Response(status, text="secret-not-for-browser internal server details")

    client = KeitaroClient(
        Settings(keitaro_api_key="secret-not-for-browser"), httpx.MockTransport(handle)
    )
    with pytest.raises(KeitaroError) as error:
        client.create_campaign({"name": "Test"})
    assert len(calls) == 1
    assert error.value.uncertain == (status >= 500)
    assert "secret-not-for-browser" not in str(error.value)
    client.close()


def test_read_retries_transient_failure_only_once():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(503, json={}) if len(calls) == 1 else httpx.Response(200, json=[])

    client = KeitaroClient(Settings(keitaro_api_key="test"), httpx.MockTransport(handle))
    assert client.offers() == []
    assert len(calls) == 2
    client.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"id": 1},
        [{"id": 1, "campaign_id": 101}],
        [{"id": 1, "campaign_id": 101, "offers": [{"offer_id": 1, "share": -1}]}],
        [{"id": 1, "campaign_id": 102, "offers": []}],
    ],
)
def test_incomplete_or_invalid_stream_responses_fail_instead_of_archiving(payload):
    client = KeitaroClient(
        Settings(keitaro_api_key="test"),
        httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    with pytest.raises(KeitaroError):
        client.streams(101)
    client.close()


def test_invalid_json_after_write_is_uncertain():
    client = KeitaroClient(
        Settings(keitaro_api_key="test"),
        httpx.MockTransport(lambda _: httpx.Response(200, text="<html>proxy error</html>")),
    )
    with pytest.raises(KeitaroError) as error:
        client.create_campaign({})
    assert error.value.uncertain
    client.close()
