from __future__ import annotations

from .ops_brain import run_daily


def main() -> None:
    result = run_daily()
    print(result)


if __name__ == "__main__":
    main()


