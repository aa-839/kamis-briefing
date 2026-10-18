"""브리핑에서 매일 추적하는 장바구니 품목.

같은 품목을 매번 다뤄야 회차끼리 비교가 된다. 배추·무·사과처럼 철마다 품종(고랭지/가을, 홍로/후지)이
바뀌는 품목은 kind_codes를 비워 두고 그날 조사된 품종을 그대로 쓴다. 화면에는 품종이 따로 표시된다.

규칙: label에 품종을 적었다면(예: '배(신고)') kind_codes로 그 품종만 허용한다.
그 품종이 조사되지 않은 날 다른 품종 가격을 가져오면 이름과 숫자가 어긋나 허위가 된다.
(실제로 10월엔 후지가 조사되지 않아 '사과(후지)' 라벨에 홍로 가격이 붙을 뻔했다.)
코드는 실제 응답(2026-10-16)으로 확인했다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BasketItem:
    label: str  # 브리핑에 표시할 이름
    category_code: str
    item_code: str
    kind_codes: tuple[str, ...] = ()  # 이 품종만 허용(앞쪽 우선). 비어 있으면 그날 조사된 품종 아무거나
    rank_codes: tuple[str, ...] = ("04",)  # 선호 등급(앞쪽 우선). 없으면 그날 있는 등급 중 첫 번째


BASKET: tuple[BasketItem, ...] = (
    # 식량작물
    BasketItem("쌀(20kg)", "100", "111", ("01", "05")),
    BasketItem("감자", "100", "152", ("00", "01")),
    BasketItem("고구마", "100", "151"),
    # 채소류
    BasketItem("배추", "200", "211"),
    BasketItem("양배추", "200", "212"),
    BasketItem("무", "200", "231"),
    BasketItem("대파", "200", "246", ("00",)),
    BasketItem("양파", "200", "245", ("00",)),
    BasketItem("깐마늘", "200", "258", ("01",)),
    BasketItem("오이", "200", "223"),
    BasketItem("애호박", "200", "224", ("01",)),
    BasketItem("시금치", "200", "213"),
    BasketItem("상추", "200", "214", ("01", "02")),
    BasketItem("풋고추", "200", "242", ("00",)),
    BasketItem("당근", "200", "232"),
    BasketItem("토마토", "200", "225"),
    # 과일류
    BasketItem("사과", "400", "411"),  # 철마다 홍로·시나노골드·후지
    BasketItem("배(신고)", "400", "412", ("01",)),
    BasketItem("감귤", "400", "415", ("01", "02"), ("15",)),  # 노지 우선, M과
    BasketItem("바나나", "400", "418"),
    # 축산물
    BasketItem("돼지 삼겹살", "500", "4304", ("27",), ("00",)),
    BasketItem("계란(특란 30구)", "500", "9903", ("23",), ("71",)),
    # 수산물
    BasketItem("고등어", "600", "611", ("05",), ("20", "21")),  # 국산 신선 냉장, 大
    BasketItem("오징어", "600", "619", ("03",), ("20", "21")),  # 연근해 신선 냉장, 大
)

CATEGORIES = tuple(dict.fromkeys(b.category_code for b in BASKET))
