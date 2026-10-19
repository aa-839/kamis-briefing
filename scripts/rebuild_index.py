"""site/data의 브리핑 파일들로 index.json(발행 목록)을 다시 만든다.

    uv run python scripts/rebuild_index.py site/data

자동 발행(GitHub Actions)과 소급 생성이 동시에 index.json을 고쳐 git 충돌이 날 때 쓴다.
목록은 각 브리핑 파일에서 그대로 뽑으므로, 파일만 맞으면 목록도 맞다.
"""

import json
import sys
from pathlib import Path


def main(out_dir: str) -> None:
    out = Path(out_dir)
    entries = []
    for path in sorted(out.glob("????-??-??.json")):
        b = json.loads(path.read_text(encoding="utf-8"))
        entries.append({
            "date": b["date"], "headline": b["headline"], "verified": b["verification"]["passed"],
            "is_mock": b["is_mock"], "backfilled": b.get("backfilled", False),
            "generated_at": b["generated_at"], "file": path.name,
        })  # fmt: skip
    entries.sort(key=lambda e: e["date"], reverse=True)
    index = {"briefings": entries, "updated_at": max((e["generated_at"] for e in entries), default=None)}
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(entries)}개 브리핑 → {out / 'index.json'}")


if __name__ == "__main__":
    main(sys.argv[1])
