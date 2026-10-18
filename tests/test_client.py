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
