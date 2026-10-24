from kamis_mcp.client import _error_code, _items, parse_price


def test_parse_price():
    assert parse_price("1,234") == 1234.0
    assert parse_price("-") is None
    assert parse_price("") is None
    assert parse_price([]) is None  # 빈 값이 리스트로 오는 경우


def test_error_code_shapes():
    assert _error_code({"data": ["200"]}) == "200"  # 샘플 키 호출 시 실제로 받은 모양
    assert _error_code({"data": {"error_code": "000", "item": []}}) == "000"


def test_items_single_dict_wrapped():
    body = {"data": {"error_code": "000", "item": {"item_name": "배추"}}}
    assert _items(body) == [{"item_name": "배추"}]


def test_transient_errors_are_retried_then_succeed():
    """아침 실행에서 실제로 겪은 406·ConnectTimeout: 기다렸다 다시 시도한다."""
    import asyncio

    import httpx

    from kamis_mcp.client import KamisClient

    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("timeout")
        if len(calls) == 2:
            return httpx.Response(406)
        return httpx.Response(200, json={"data": {"error_code": "000", "item": []}})

    c = KamisClient(cert_key="k", cert_id="i", transport=httpx.MockTransport(handler))
    c.retry_waits = (0, 0, 0)
    assert asyncio.run(c.call("dailyPriceByCategoryList")) == {"data": {"error_code": "000", "item": []}}
    assert len(calls) == 3


def test_auth_failure_is_not_retried():
    import asyncio

    import httpx
    import pytest

    from kamis_mcp.client import KamisClient, KamisError

    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"data": ["900"]})

    c = KamisClient(cert_key="k", cert_id="i", transport=httpx.MockTransport(handler))
    c.retry_waits = (0, 0, 0)
    with pytest.raises(KamisError):
        asyncio.run(c.call("dailyPriceByCategoryList"))
    assert len(calls) == 1
