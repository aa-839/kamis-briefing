"""테스트 공용 도구: 저장해 둔 실제 KAMIS 응답(tests/fixtures/)을 돌려주는 가짜 네트워크."""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from save_fixtures import fixture_name  # noqa: E402  (저장할 때와 같은 이름 규칙)

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureTransport(httpx.AsyncBaseTransport):
    """요청 파라미터로 fixture 파일을 찾아 응답한다. 없으면 KAMIS처럼 001(데이터 없음)."""

    def __init__(self):
        self.requests: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        path = FIXTURES / fixture_name(params)
        body = path.read_bytes() if path.exists() else json.dumps({"data": ["001"]}).encode()
        return httpx.Response(200, content=body, headers={"content-type": "text/plain; charset=utf-8"})


@pytest.fixture
def kamis():
    from kamis_mcp.client import KamisClient

    return KamisClient(cert_key="test-key", cert_id="test-id", transport=FixtureTransport())
