from typing import Mapping, Optional

from fastapi import HTTPException, Request


def _parse_uint(value: Optional[str], name: str) -> int:
    """Parse a non-negative integer per Alpaca spec.

    Empty / whitespace / missing values default to 0 (Alpaca-spec behavior).
    Bad input raises HTTPException(400) so callers get the right status code
    instead of FastAPI's default 422.
    """

    if value is None:
        return 0
    s = str(value).strip()
    if not s:
        return 0
    try:
        n = int(s)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"{name} must be a non-negative integer, got {value!r}",
        )
    if n < 0:
        raise HTTPException(
            status_code=400,
            detail=f"{name} must be a non-negative integer, got {n}",
        )
    return n


def _ci_lookup(mapping: Mapping[str, str], key: str) -> Optional[str]:
    """Case-insensitive lookup. Alpaca requires that parameter names be
    matched without regard to case."""

    target = key.lower()
    for k, v in mapping.items():
        if k.lower() == target:
            return v
    return None


class AlpacaGetParams:
    """Common Alpaca GET query parameters, parsed case-insensitively.

    Also exposes case-insensitive lookups for method-specific query params
    (e.g. ISwitch's `Id` parameter). ConformU's `alpacaprotocol` test
    sends GET query parameters with inverted casing and expects them to
    be accepted, so use `params.get(name)` / `params.get_int(name)`
    instead of typed `Query(...)` declarations.
    """

    def __init__(self, request: Request):
        q = request.query_params
        self._query = q
        self.client_id = _parse_uint(_ci_lookup(q, "ClientID"), "ClientID")
        self.client_transaction_id = _parse_uint(
            _ci_lookup(q, "ClientTransactionID"), "ClientTransactionID"
        )

    def get(self, name: str) -> Optional[str]:
        """Case-insensitive query-string lookup."""
        return _ci_lookup(self._query, name)

    def get_int(self, name: str) -> int:
        """Required integer query param via case-insensitive lookup."""
        v = self.get(name)
        if v is None:
            raise HTTPException(status_code=400, detail=f"Missing required parameter {name!r}")
        try:
            return int(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{name} must be an integer, got {v!r}")


class AlpacaPutParams:
    """Common Alpaca PUT form parameters, parsed case-insensitively.

    Built via the `alpaca_put_params` dependency below because reading the
    request form requires an async `await`.
    """

    def __init__(self, client_id: int, client_transaction_id: int, form: dict):
        self.client_id = client_id
        self.client_transaction_id = client_transaction_id
        self._form = form

    def get(self, name: str) -> Optional[str]:
        """Case-insensitive form-field lookup."""
        return self._form.get(name.lower())


async def alpaca_put_params(request: Request) -> AlpacaPutParams:
    """FastAPI dependency that parses the PUT form body case-insensitively."""

    try:
        raw = await request.form()
        form = {k.lower(): str(v) for k, v in raw.items()}
    except Exception:
        form = {}
    return AlpacaPutParams(
        client_id=_parse_uint(form.get("clientid"), "ClientID"),
        client_transaction_id=_parse_uint(
            form.get("clienttransactionid"), "ClientTransactionID"
        ),
        form=form,
    )


def to_bool(value: str) -> bool:
    low = value.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise HTTPException(status_code=400, detail=f'Bad boolean value "{value}"')
