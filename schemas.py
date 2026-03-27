from typing import Optional
from pydantic import BaseModel, Field


class RawExtraction(BaseModel):
    origin_text: Optional[str] = Field(default=None, description="Origin port/city text as mentioned in email")
    destination_text: Optional[str] = Field(default=None, description="Destination port/city text as mentioned in email")
    incoterm: Optional[str] = Field(default=None, description="Incoterm if explicitly present")
    cargo_weight_raw: Optional[str] = Field(default=None, description="Raw cargo weight text")
    cargo_cbm_raw: Optional[str] = Field(default=None, description="Raw cargo volume text (CBM/RT/CMB)")
    is_dangerous: Optional[bool] = Field(default=None, description="Whether cargo appears dangerous")


class ShipmentExtraction(BaseModel):
    id: str
    product_line: Optional[str] = None
    incoterm: Optional[str] = None
    origin_port_code: Optional[str] = None
    origin_port_name: Optional[str] = None
    destination_port_code: Optional[str] = None
    destination_port_name: Optional[str] = None
    cargo_weight_kg: Optional[float] = Field(default=None)
    cargo_cbm: Optional[float] = Field(default=None)
    is_dangerous: bool = False
