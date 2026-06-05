import json


def summarize_events(raw: str) -> dict:
    records = [json.loads(line) for line in raw.splitlines()]
    emails = [record["email"] for record in records if record.get("active")]
    return {"active_count": len(emails), "emails": emails, "tag_counts": {}}

