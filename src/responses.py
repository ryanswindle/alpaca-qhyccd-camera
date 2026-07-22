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
        # Pass `value` through regardless of error — callers are responsible
        # for providing a type-correct default (e.g. [] for array-returning
        # methods like DeviceState). ConformU's strictly-typed deserializer
        # rejects null where it expects an array.
        err = error or Success()
        return cls(
            Value=value,
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


_DTYPE_TO_ELEMENT_TYPE = {
    np.dtype(np.uint8): ImageArrayElementTypes.BYTE,
    np.dtype(np.int16): ImageArrayElementTypes.INT16,
    np.dtype(np.uint16): ImageArrayElementTypes.UINT16,
    np.dtype(np.int32): ImageArrayElementTypes.INT32,
    np.dtype(np.uint32): ImageArrayElementTypes.UINT32,
}


IMAGEBYTES_HEADER_FORMAT = "<IIIIIIIIIII"
IMAGEBYTES_HEADER_SIZE = struct.calcsize(IMAGEBYTES_HEADER_FORMAT)  # 44

class ImageArrayResponse(PropertyResponse):
    """Response model for ImageArray property with ImageBytes support."""
    Type: int = Field(default=int(ImageArrayElementTypes.UNKNOWN), description="Image element type")
    Rank: int = Field(default=2, description="Array rank (2 for 2D)")

    @classmethod
    def create(
        cls,
        value: Any,
        client_transaction_id: int = 0,
        error: Optional[AlpacaError] = None,
    ) -> "ImageArrayResponse":
        # Infer Type and Rank from the supplied array so JSON and ImageBytes
        # paths both report correct metadata.
        # Type is the ASCOM ImageArray element type — Int32 for all integer
        # data per the ICameraV4 contract; the narrower native dtype is a
        # transmission format only (see to_imagebytes).
        err = error or Success()
        if err.Number == 0 and value is not None:
            arr = np.asarray(value)
            if np.issubdtype(arr.dtype, np.integer):
                element_type = ImageArrayElementTypes.INT32
            else:
                element_type = _DTYPE_TO_ELEMENT_TYPE.get(
                    arr.dtype, ImageArrayElementTypes.UNKNOWN
                )
            rank = arr.ndim
            value_out = arr
        else:
            element_type = ImageArrayElementTypes.UNKNOWN
            rank = 2
            value_out = None
        return cls(
            Value=value_out,
            Type=int(element_type),
            Rank=rank,
            ClientTransactionID=client_transaction_id,
            ServerTransactionID=get_next_transaction_id(),
            ErrorNumber=err.Number,
            ErrorMessage=err.Message,
        )

    def to_imagebytes(self) -> bytes:
        """Convert the image array to ASCOM ImageBytes format."""
        if self.ErrorNumber == 0 and self.Value is not None:
            value = np.asarray(self.Value)
            # Transmission uses the narrow native dtype (halves bandwidth for
            # uint16 sensors); ImageElementType stays the ASCOM array type
            # (self.Type, Int32 for integer data) and clients upcast.
            transmission_type = _DTYPE_TO_ELEMENT_TYPE.get(
                value.dtype, ImageArrayElementTypes.UNKNOWN
            )
            if transmission_type == ImageArrayElementTypes.UNKNOWN:
                # Unsupported dtype — coerce to uint16 as a safe default.
                value = value.astype(np.uint16, order="C")
                transmission_type = ImageArrayElementTypes.UINT16
            else:
                value = np.ascontiguousarray(value)

            image_bytes = value.tobytes(order="C")
            dim1 = value.shape[0] if value.ndim > 0 else 0
            dim2 = value.shape[1] if value.ndim > 1 else 0
            dim3 = value.shape[2] if value.ndim > 2 else 0
            return struct.pack(
                f"{IMAGEBYTES_HEADER_FORMAT}{len(image_bytes)}s",
                1,  # MetadataVersion
                self.ErrorNumber,  # ErrorNumber
                self.ClientTransactionID,  # ClientTransactionID
                self.ServerTransactionID,  # ServerTransactionID
                IMAGEBYTES_HEADER_SIZE,  # DataStart
                self.Type,  # ImageElementType
                int(transmission_type),  # TransmissionElementType
                self.Rank,  # Rank
                dim1,  # Dimension1
                dim2,  # Dimension2
                dim3,  # Dimension3
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
