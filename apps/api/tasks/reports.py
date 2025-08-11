from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from io import BytesIO

from minio import Minio

from ..celery_app import celery_app
from ..db import Event, session_scope


def _minio_client() -> Minio:
    endpoint = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY", "minio")
    secret_key = os.getenv("MINIO_SECRET_KEY", "miniosecret")
    # Remove http:// for Minio SDK endpoint param
    clean_endpoint = endpoint.replace("http://", "").replace("https://", "")
    return Minio(clean_endpoint, access_key=access_key, secret_key=secret_key, secure=False)


@celery_app.task(name="apps.api.tasks.reports.generate_morning_brief")
def generate_morning_brief() -> str:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)
    with session_scope() as s:
        total_events = s.query(Event).filter(Event.ts >= since).count()
    html = f"""
    <html>
    <body>
    <h1>Morning Brief</h1>
    <p>Since: {since.isoformat()}</p>
    <p>Total events: {total_events}</p>
    </body>
    </html>
    """.strip()

    client = _minio_client()
    bucket = "reports"
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    obj_name = f"morning_brief_{now.strftime('%Y%m%d')}.html"
    data = BytesIO(html.encode("utf-8"))
    client.put_object(bucket, obj_name, data, length=len(html.encode("utf-8")))

    # Emit event
    with session_scope() as s:
        ev = Event(
            name="report.morning_brief_sent",
            session_id="ops",
            user_id="ops",
            props={"object": f"{bucket}/{obj_name}"},
        )
        s.add(ev)
        s.flush()
    return f"s3://{bucket}/{obj_name}"


