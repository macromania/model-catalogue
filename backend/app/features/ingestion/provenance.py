from datetime import date, datetime


def azure_provenance(document: dict) -> dict:
    fetched_at = document.get("fetched_at")
    if fetched_at is not None:
        if not isinstance(fetched_at, str):
            raise ValueError("Azure fetched_at must be an ISO 8601 timestamp")
        timestamp = datetime.fromisoformat(fetched_at)
        if timestamp.tzinfo is None:
            raise ValueError("Azure fetched_at must include its time zone")
    api_version = document.get("api_version")
    if api_version is not None:
        if not isinstance(api_version, str):
            raise ValueError("Azure api_version must be a date or date-preview string")
        date.fromisoformat(api_version.removesuffix("-preview"))
    return {"fetched_at": fetched_at, "api_version": api_version}
