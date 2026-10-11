import unittest
from decimal import Decimal as D
from demo_futures.risk import BacktestConfig, ContractSpec, DailyLossGuard, fill_price, size_position

SPEC = ContractSpec(".01", ".001", ".001", "1")


class RiskTests(unittest.TestCase):
    def test_zero_cost_half_percent_budget_hand_calculation(self):
        config = BacktestConfig(fee_rate=0, slippage_rate=0, funding_reserve_rate=0)
        plan, _ = size_position(10000, 100, 1, "LONG", SPEC, config)
        self.assertEqual(plan.quantity, D(25))
        self.assertEqual(plan.stop_price, D(98))
        self.assertEqual(plan.target_price, D(103))
        self.assertEqual(plan.budget, D(50))
        self.assertEqual(plan.planned_loss, D(50))
        self.assertEqual(plan.margin, D(1250))

    def test_costs_and_funding_reserve_reduce_size(self):
        clean = BacktestConfig(fee_rate=0, slippage_rate=0, funding_reserve_rate=0)
        costed = BacktestConfig()
        base, _ = size_position(10000, 100, 1, "LONG", SPEC, clean)
        smaller, _ = size_position(10000, 100, 1, "LONG", SPEC, costed)
        self.assertLess(smaller.quantity, base.quantity)
        self.assertLessEqual(smaller.planned_loss, smaller.budget)

    def test_leverage_and_margin_cap(self):
        config = BacktestConfig(fee_rate=0, slippage_rate=0, funding_reserve_rate=0)
        plan, _ = size_position(1000, 100, ".001", "LONG", SPEC, config)
        self.assertLessEqual(plan.quantity * plan.entry_price, D(2000))
        self.assertLessEqual(plan.margin, D(1000))
        blocked, _ = size_position(1000, 100, 1, "LONG", SPEC, config, reserved_notional=2000)
        self.assertIsNone(blocked)

    def test_round_down_never_up_for_minimum_notional(self):
        config = BacktestConfig(fee_rate=0, slippage_rate=0, funding_reserve_rate=0)
        spec = ContractSpec(".1", "3", "3", "1")
        plan, _ = size_position(10000, 100, 1, "LONG", spec, config)
        self.assertEqual(plan.quantity, D(24))
        blocked, reason = size_position(100, 100, 1, "LONG", ContractSpec(".01", ".001", ".001", "100"), config)
        self.assertIsNone(blocked)
        self.assertIn("never increase risk", reason)

    def test_invalid_equity_atr_and_levels_rejected(self):
        for equity, price, atr in ((0, 100, 1), (-1, 100, 1), (10000, 100, 0),
                                   (10000, 100, -1), (10000, 1, 10)):
            with self.subTest(equity=equity, price=price, atr=atr):
                plan, _ = size_position(equity, price, atr, "LONG", SPEC, BacktestConfig())
                self.assertIsNone(plan)
        with self.assertRaises(ValueError):
            size_position("NaN", 100, 1, "LONG", SPEC, BacktestConfig())

    def test_configuration_cannot_raise_hard_risk_limits(self):
        for arguments in ({"risk_fraction": ".006"}, {"leverage": "3"},
                          {"daily_loss_fraction": ".021"}, {"fee_rate": "-1"},
                          {"slippage_rate": "1"}, {"max_positions": 0}, {"max_holding_bars": True}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                BacktestConfig(**arguments)

    def test_daily_exact_threshold_latches_and_resets_only_new_day(self):
        guard = DailyLossGuard(".02")
        guard.begin_day(1, 10000)
        self.assertFalse(guard.check("9800.01"))
        self.assertTrue(guard.check(9800))
        self.assertTrue(guard.check(10010))
        guard.begin_day(1, 10010)
        self.assertTrue(guard.halted)
        guard.begin_day(2, 9900)
        self.assertFalse(guard.halted)
        self.assertEqual(guard.anchor, D(9900))

    def test_adverse_slippage_and_tick_rounding_both_sides(self):
        cfg = BacktestConfig(slippage_rate=".001")
        self.assertEqual(fill_price(100, True, SPEC, cfg), D("100.10"))
        self.assertEqual(fill_price(101, False, SPEC, cfg), D("100.89"))
        self.assertEqual(fill_price(99, True, SPEC, cfg), D("99.10"))

    def test_no_martingale_risk_follows_equity_not_loss_streak(self):
        cfg = BacktestConfig(fee_rate=0, slippage_rate=0, funding_reserve_rate=0)
        before, _ = size_position(10000, 100, 1, "LONG", SPEC, cfg)
        after, _ = size_position(9950, 100, 1, "LONG", SPEC, cfg)
        self.assertLess(after.quantity, before.quantity)
        self.assertEqual(after.budget, D("49.75"))
