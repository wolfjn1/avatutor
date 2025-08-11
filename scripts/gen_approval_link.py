from __future__ import annotations

import sys
from urllib.parse import quote

from apps.api.security import mint_approval_token


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: gen_approval_link.py DECISION_KEY")
        sys.exit(1)
    dec = sys.argv[1]
    token = mint_approval_token({"decision_key": dec})
    print(f"http://localhost:8080/approve?token={quote(token)}")


if __name__ == "__main__":
    main()


