from __future__ import annotations

from typing import Literal


Board = Literal["SSE_MAIN", "SZSE_MAIN", "CHINEXT", "STAR", "BSE", "UNKNOWN"]


def normalize_symbol(symbol: str) -> str:
    digits = "".join(ch for ch in str(symbol) if ch.isdigit())
    if not digits:
        raise ValueError(f"invalid A-share symbol: {symbol!r}")
    return digits.zfill(6)


def classify_board(symbol: str) -> Board:
    """Starter board classifier.

    For historical research this must eventually be validated against a
    point-in-time security master; prefix logic alone is not sufficient for
    every historical edge case.
    """
    code = normalize_symbol(symbol)
    if code.startswith(("600", "601", "603", "605")):
        return "SSE_MAIN"
    if code.startswith(("000", "001", "002", "003")):
        return "SZSE_MAIN"
    if code.startswith(("300", "301")):
        return "CHINEXT"
    if code.startswith(("688", "689")):
        return "STAR"
    if code.startswith(("4", "8", "920")):
        return "BSE"
    return "UNKNOWN"


def is_v01_execution_candidate(
    symbol: str,
    *,
    name: str = "",
    suspended: bool = False,
    one_price_limit: bool = False,
) -> bool:
    """Hard execution-universe gate for X V0.1.

    This is intentionally conservative. Price-limit distance, listing age,
    liquidity and point-in-time risk labels belong to later data-backed gates.
    """
    if classify_board(symbol) not in {"SSE_MAIN", "SZSE_MAIN"}:
        return False
    normalized_name = str(name).upper().replace(" ", "")
    if "ST" in normalized_name or "退" in normalized_name:
        return False
    if suspended or one_price_limit:
        return False
    return True
