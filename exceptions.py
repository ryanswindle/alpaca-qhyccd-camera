import traceback
from typing import Optional


class AlpacaError:
    """Base class for Alpaca error responses."""

    def __init__(self, number: int, message: str):
        self.number = number
        self.message = message

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message


class Success(AlpacaError):
    def __init__(self):
        super().__init__(0, "")


class NotImplementedException(AlpacaError):
    def __init__(self, message: str = "Property or method not implemented."):
        super().__init__(0x400, message)


class InvalidValueException(AlpacaError):
    def __init__(self, message: str = "Invalid value given."):
        super().__init__(0x401, message)


class ValueNotSetException(AlpacaError):
    def __init__(self, message: str = "The value has not yet been set."):
        super().__init__(0x402, message)


class NotConnectedException(AlpacaError):
    def __init__(self, message: str = "The device is not connected."):
        super().__init__(0x407, message)


class InvalidOperationException(AlpacaError):
    def __init__(self, message: str = "The requested operation cannot be undertaken at this time."):
        super().__init__(0x40B, message)


class ActionNotImplementedException(AlpacaError):
    def __init__(self, message: str = "The requested action is not implemented in this driver."):
        super().__init__(0x40C, message)


class OperationCancelledException(AlpacaError):
    def __init__(self, message: str = "In-progress (async) operation was cancelled."):
        super().__init__(0x40E, message)


class DriverException(AlpacaError):
    def __init__(self, number: int = 0x500, message: str = "Internal driver error.", exc: Optional[BaseException] = None):
        if number < 0x500 or number > 0xFFF:
            number = 0x500
        full_message = message
        if exc is not None:
            full_message = f"{message}\n{traceback.format_exc()}"
        super().__init__(number, full_message)
