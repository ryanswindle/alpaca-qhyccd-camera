from dataclasses import dataclass
from typing import Optional

from fastapi import Form, HTTPException, Query


@dataclass
class AlpacaGetParams:
    """Common query parameters for Alpaca GET requests."""
    client_id: int = 0
    client_transaction_id: int = 0

    def __init__(
        self,
        ClientID: Optional[int] = Query(default=0, ge=0),
        ClientTransactionID: Optional[int] = Query(default=0, ge=0),
    ):
        self.client_id = ClientID or 0
        self.client_transaction_id = ClientTransactionID or 0


@dataclass
class AlpacaPutParams:
    """Common form parameters for Alpaca PUT requests."""
    client_id: int = 0
    client_transaction_id: int = 0

    def __init__(
        self,
        ClientID: Optional[int] = Form(default=0),
        ClientTransactionID: Optional[int] = Form(default=0),
    ):
        self.client_id = ClientID or 0
        self.client_transaction_id = ClientTransactionID or 0


def to_bool(value: str) -> bool:
    low = value.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise HTTPException(status_code=400, detail=f'Bad boolean value "{value}"')