from enum import IntEnum
import struct
from threading import Lock
from typing import Any, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from exceptions import AlpacaError, Success


# Thread-safe server transaction ID counter
_stid_lock = Lock()
_stid = 0


def get_next_transaction_id() -> int:
    global _stid
    with _stid_lock:
        _stid += 1
        return _stid


class StateValue(BaseModel):
    """Name/value pair for DeviceState property."""
    Name: str = Field(description="Property name")
    Value: Any = Field(description="Property value")


class AlpacaResponse(BaseModel):
    """Base response model for all Alpaca API responses."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    ClientTransactionID: int = Field(default=0)
    ServerTransactionID: int = Field(default=0)
    ErrorNumber: int = Field(default=0)
    ErrorMessage: str = Field(default="")
    
    @classmethod
    def create(
        cls,
        client_transaction_id: int = 0,
        error: Optional[AlpacaError] = None,
        **kwargs,
    ) -> "AlpacaResponse":
        err = error or Success()
        return cls(
            ClientTransactionID=client_transaction_id,
            ServerTransactionID=get_next_transaction_id(),
            ErrorNumber=err.Number,
            ErrorMessage=err.Message,
            **kwargs,
        )


class PropertyResponse(AlpacaResponse):
    """Response model for property GET requests."""
    Value: Optional[Any] = Field(default=None)
    
    @classmethod
    def create(
        cls,
        value: Any,
        client_transaction_id: int = 0,
        error: Optional[AlpacaError] = None,
    ) -> "PropertyResponse":
        err = error or Success()
        return cls(
            Value=value if err.Number == 0 else None,
            ClientTransactionID=client_transaction_id,
            ServerTransactionID=get_next_transaction_id(),
            ErrorNumber=err.Number,
            ErrorMessage=err.Message,
        )


class MethodResponse(AlpacaResponse):
    """Response model for method PUT requests."""
    Value: Optional[Any] = Field(default=None)
    
    @classmethod
    def create(
        cls,
        client_transaction_id: int = 0,
        error: Optional[AlpacaError] = None,
        value: Any = None,
    ) -> "MethodResponse":
        err = error or Success()
        return cls(
            Value=value if err.Number == 0 and value is not None else None,
            ClientTransactionID=client_transaction_id,
            ServerTransactionID=get_next_transaction_id(),
            ErrorNumber=err.Number,
            ErrorMessage=err.Message,
        )


class ImageArrayElementTypes(IntEnum):
    """Image array element types for ImageBytes format."""
    UNKNOWN = 0
    INT16 = 1
    INT32 = 2
    DOUBLE = 3
    SINGLE = 4
    UINT64 = 5
    BYTE = 6
    INT64 = 7
    UINT16 = 8
    UINT32 = 9


IMAGEBYTES_HEADER_FORMAT = "<IIIIIIIIIII"
IMAGEBYTES_HEADER_SIZE = struct.calcsize(IMAGEBYTES_HEADER_FORMAT)  # 44

class ImageArrayResponse(PropertyResponse):
    """Response model for ImageArray property with ImageBytes support."""
    Type: int = Field(default=2, description="Image element type")
    Rank: int = Field(default=2, description="Array rank (2 for 2D)")

    def to_imagebytes(self) -> bytes:
        """Convert the image array to ASCOM ImageBytes format."""
        if self.ErrorNumber == 0 and self.Value is not None:
            value = np.asarray(self.Value)
            if value.dtype == np.int16:
                image_element_type = transmission_element_type = (
                    ImageArrayElementTypes.INT16
                )
            elif value.dtype == np.uint16:
                image_element_type = transmission_element_type = (
                    ImageArrayElementTypes.UINT16
                )
            elif value.dtype == np.int32:
                image_element_type = transmission_element_type = (
                    ImageArrayElementTypes.INT32
                )
            elif value.dtype == np.uint32:
                image_element_type = transmission_element_type = (
                    ImageArrayElementTypes.UINT32
                )
            else:
                image_element_type = transmission_element_type = (
                    ImageArrayElementTypes.UINT16
                )
                value = value.astype(np.uint16, order="C")

            image_bytes = value.astype(value.dtype, order="C").tobytes(order="C")
            return struct.pack(
                f"{IMAGEBYTES_HEADER_FORMAT}{len(image_bytes)}s",
                1,  # MetadataVersion
                self.ErrorNumber,  # ErrorNumber
                self.ClientTransactionID,  # ClientTransactionID
                self.ServerTransactionID,  # ServerTransactionID
                IMAGEBYTES_HEADER_SIZE,  # DataStart
                image_element_type,  # ImageElementType
                transmission_element_type,  # TransmissionElementType
                self.Rank,  # Rank
                value.shape[0],  # Dimension1
                value.shape[1],  # Dimension2
                0,  # Dimension3
                image_bytes,  # Pixel data
            )
        else:
            error_message = self.ErrorMessage.encode("utf-8")
            return struct.pack(
                f"{IMAGEBYTES_HEADER_FORMAT}{len(error_message)}s",
                1,  # MetadataVersion
                self.ErrorNumber,  # ErrorNumber
                self.ClientTransactionID,  # ClientTransactionID
                self.ServerTransactionID,  # ServerTransactionID
                IMAGEBYTES_HEADER_SIZE,  # DataStart
                0,  # ImageElementType
                0,  # TransmissionElementType
                0,  # Rank
                0,  # Dimension1
                0,  # Dimension2
                0,  # Dimension3
                error_message,  # Error message (UTF-8)
            )
