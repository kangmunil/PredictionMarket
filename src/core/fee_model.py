from dataclasses import dataclass


@dataclass
class FeeModel:
    taker_fee: float = 0.002
    maker_fee: float = 0.0

    def cost(self, price: float, size: float, is_taker: bool = True) -> float:
        fee_rate = self.taker_fee if is_taker else self.maker_fee
        return price * size * fee_rate
