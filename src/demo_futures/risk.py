"""Pure offline risk decisions. No account, credentials, or network access."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


def dec(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Financial inputs must be finite")
    return result


@dataclass(frozen=True)
class BacktestConfig:
    initial_equity: Decimal = Decimal("10000")
    risk_fraction: Decimal = Decimal("0.005")
    leverage: Decimal = Decimal("2")
    daily_loss_fraction: Decimal = Decimal("0.02")
    fee_rate: Decimal = Decimal("0.0005")
    slippage_rate: Decimal = Decimal("0.0002")
    funding_reserve_rate: Decimal = Decimal("0.001")
    stop_atr: Decimal = Decimal("2")
    target_atr: Decimal = Decimal("3")
    max_positions: int = 1
    max_holding_bars: int = 48
    allow_missing_funding: bool = False

    def __post_init__(self):
        numeric = ("initial_equity", "risk_fraction", "leverage", "daily_loss_fraction",
                   "fee_rate", "slippage_rate", "funding_reserve_rate", "stop_atr", "target_atr")
        for name in numeric:
            object.__setattr__(self, name, dec(getattr(self, name)))
        if self.initial_equity <= 0 or not 0 < self.risk_fraction <= Decimal("0.005"):
            raise ValueError("Equity must be positive; risk cannot exceed 0.5%")
        if not 0 < self.leverage <= 2 or not 0 < self.daily_loss_fraction <= Decimal("0.02"):
            raise ValueError("Leverage cannot exceed 2x; daily loss limit cannot exceed 2%")
        if any(getattr(self, name) < 0 for name in ("fee_rate", "slippage_rate", "funding_reserve_rate")):
            raise ValueError("Cost rates cannot be negative")
        if self.fee_rate >= 1 or self.slippage_rate >= 1:
            raise ValueError("Fee/slippage rates must be less than one")
        if self.stop_atr <= 0 or self.target_atr <= 0:
            raise ValueError("ATR multiples must be positive")
        if type(self.max_positions) is not int or not 1 <= self.max_positions <= 2:
            raise ValueError("Position cap must be 1 or 2")
        if type(self.max_holding_bars) is not int or self.max_holding_bars < 1:
            raise ValueError("Holding cap must be a positive integer")


@dataclass(frozen=True)
class ContractSpec:
    tick_size: Decimal
    quantity_step: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    max_quantity: Decimal = Decimal("1000000")

    def __post_init__(self):
        for name in ("tick_size", "quantity_step", "min_quantity", "min_notional", "max_quantity"):
            object.__setattr__(self, name, dec(getattr(self, name)))
        if min(self.tick_size, self.quantity_step, self.min_quantity, self.min_notional) <= 0:
            raise ValueError("Offline contract assumptions must be positive")
        if self.max_quantity < self.min_quantity:
            raise ValueError("Invalid quantity limits")


# Research assumptions, not fetched or asserted to be historical Binance filters.
DEFAULT_SPECS = {
    "BTCUSDT": ContractSpec("0.10", "0.001", "0.001", "100"),
    "ETHUSDT": ContractSpec("0.01", "0.001", "0.001", "20"),
}


def round_step(value, step, upward=False):
    value, step = dec(value), dec(step)
    if step <= 0:
        raise ValueError("Step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_CEILING if upward else ROUND_FLOOR) * step


def fill_price(reference, is_buy, spec, config):
    reference = dec(reference)
    if reference <= 0:
        raise ValueError("Price must be positive")
    adjusted = reference * (1 + config.slippage_rate if is_buy else 1 - config.slippage_rate)
    result = round_step(adjusted, spec.tick_size, upward=is_buy)
    if result <= 0:
        raise ValueError("Rounded price must be positive")
    return result


@dataclass(frozen=True)
class PositionPlan:
    quantity: Decimal
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    budget: Decimal
    planned_loss: Decimal
    margin: Decimal


def size_position(equity, reference, atr, side, spec, config, reserved_notional=0):
    equity, reference, atr, reserved = map(dec, (equity, reference, atr, reserved_notional))
    if equity <= 0 or reference <= 0 or atr <= 0 or reserved < 0 or side not in ("LONG", "SHORT"):
        return None, "Invalid equity, price, ATR, reservation or side"
    long = side == "LONG"
    entry = fill_price(reference, long, spec, config)
    stop = round_step(reference - config.stop_atr * atr if long else reference + config.stop_atr * atr,
                      spec.tick_size, upward=not long)
    target = round_step(reference + config.target_atr * atr if long else reference - config.target_atr * atr,
                        spec.tick_size, upward=long)
    if stop <= 0 or target <= 0 or not (stop < entry < target if long else target < entry < stop):
        return None, "Invalid protective levels after adverse fill"
    stop_fill = fill_price(stop, not long, spec, config)
    price_loss = entry - stop_fill if long else stop_fill - entry
    unit_loss = price_loss + config.fee_rate * (entry + stop_fill) + entry * config.funding_reserve_rate
    if unit_loss <= 0 or unit_loss >= entry / config.leverage:
        return None, "Stop risk could consume allocated margin"
    budget = equity * config.risk_fraction
    available_notional = max(Decimal(0), equity * config.leverage - reserved)
    # Reserve entry fees and entry price friction as well as position margin.
    available_equity = max(Decimal(0), equity - reserved / config.leverage)
    margin_unit = entry / config.leverage + entry * config.fee_rate + abs(entry - reference)
    quantity = round_step(min(budget / unit_loss, available_notional / entry,
                              available_equity / margin_unit, spec.max_quantity), spec.quantity_step)
    if quantity < spec.min_quantity or quantity * entry < spec.min_notional:
        return None, "Rounded size below minimum quantity/notional; never increase risk to meet minimums"
    loss = quantity * unit_loss
    if loss > budget or quantity * entry + reserved > equity * config.leverage:
        return None, "Risk or portfolio leverage ceiling exceeded"
    return PositionPlan(quantity, entry, stop, target, budget, loss, quantity * entry / config.leverage), "Approved within fixed risk budget"


class DailyLossGuard:
    def __init__(self, limit):
        self.limit = dec(limit)
        if not 0 < self.limit <= Decimal("0.02"):
            raise ValueError("Invalid daily limit")
        self.day = None
        self.anchor = None
        self.halted = False

    def begin_day(self, day, equity):
        equity = dec(equity)
        if self.day is not None and day < self.day:
            raise ValueError("Days must be chronological")
        if day != self.day:
            self.day, self.anchor, self.halted = day, equity, equity <= 0

    def check(self, equity):
        if self.anchor is None:
            raise ValueError("Daily anchor is not initialized")
        if dec(equity) <= self.anchor * (1 - self.limit):
            self.halted = True
        return self.halted
