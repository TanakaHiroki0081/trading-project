from pydantic import BaseModel

class PositionData(BaseModel):
    ticket: int
    symbol: str
    volume: float
    sl: float
    tp: float
    type: int
    magic: int
    comment: str
    action: str  # "OPEN", "MODIFY", "CLOSE"
