"""List every case currently in Postgres so test artifacts can be identified."""
import requests

BASE = "http://127.0.0.1:8000"


def main():
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"badgeNumber": "IND-LE-8402", "password": "password123"},
        timeout=30,
    )
    r.raise_for_status()
    h = {"Authorization": "Bearer " + r.json()["token"]}

    res = requests.get(f"{BASE}/api/cases", params={"limit": 300}, headers=h, timeout=60).json()
    items = res.get("items", res) if isinstance(res, dict) else res
    print(f"{len(items)} cases in Postgres\n")
    for c in sorted(items, key=lambda x: str(x.get("case_id"))):
        print(
            f"  {str(c.get('case_id')):34} "
            f"entities={c.get('total_entities')} "
            f"evidence={c.get('evidence_count')} "
            f"title={c.get('title')}"
        )

    q = requests.post(
        f"{BASE}/api/graph/cypher",
        json={"query": "MATCH (n:Entity) RETURN n.case_id AS c, count(*) AS k ORDER BY k DESC"},
        headers=h,
        timeout=60,
    )
    print("\nNeo4j case_ids:\n ", q.text[:1200])


if __name__ == "__main__":
    main()
