from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Dict

import jwt


SECRET_KEY = os.getenv("SECRET_KEY", "devsecret")


def verify_webhook_hmac(body: bytes, signature_header: str) -> bool:
    mac = hmac.new(SECRET_KEY.encode("utf-8"), msg=body, digestmod=sha256).hexdigest()
    # signature_header expected like: sha256=<hex>
    expected = f"sha256={mac}"
    return hmac.compare_digest(expected, signature_header)


def mint_approval_token(payload: Dict[str, Any], ttl_hours: int = 24) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=ttl_hours)
    to_encode = {**payload, "exp": int(exp.timestamp())}
    return jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")


def verify_approval_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])  # type: ignore[no-any-return]


