from __future__ import annotations

import hmac
from hashlib import sha256

from apps.api.security import verify_webhook_hmac, SECRET_KEY


def test_verify_webhook_hmac_valid_and_invalid() -> None:
    body = b"{\"hello\":\"world\"}"
    mac = hmac.new(SECRET_KEY.encode("utf-8"), msg=body, digestmod=sha256).hexdigest()
    sig = f"sha256={mac}"
    assert verify_webhook_hmac(body, sig) is True

    bad_sig = "sha256=deadbeef"
    assert verify_webhook_hmac(body, bad_sig) is False



