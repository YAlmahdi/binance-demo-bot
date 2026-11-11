import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from demo_futures.demo_protocol_mock import Page, Row, StreamEvent, normalize
from demo_futures.demo_safety_mock import (
    Event, Inventory, Outcome, Position, Resolution, Signal, State,
    checkpoint, create_snapshot, restore, transition,
)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.state = transition(State(), Event(1, Signal.CONNECT)).state
        self.state = transition(self.state, Event(2, Signal.RECONCILE)).state
        request = self.state.reconciliation
        view = Inventory(request, 2, 1, True, (), (), (), date(2000, 1, 1),
                         Decimal("100"), Decimal("100"))
        self.page = Page(view, "ONE_WAY", 0, None, None, ())

    def run_view(self, pages=None, events=(), **options):
        config = dict(watermark=2, through=2, max_pages=3, max_rows=4)
        config.update(options)
        return normalize(self.state, (self.page,) if pages is None else pages, events, **config)

    def test_complete_pagination_and_replay(self):
        pages = (replace(self.page, next_token="second"),
                 replace(self.page, number=1, token="second"))
        result = self.run_view(pages)
        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(result, self.run_view(pages))
        self.state = result.state
        self.assertEqual(self.run_view(pages).verdict, "BLOCKED")

    def test_missing_duplicate_changed_and_reordered_pages(self):
        second = replace(self.page, number=1, token="next")
        first = replace(self.page, next_token="next")
        for pages in ((), (first,), (first, first), (second, first),
                      (first, replace(second, inventory=replace(second.inventory, account_version=2))),
                      (first, replace(second, next_token="next"))):
            with self.subTest(pages=pages):
                result = self.run_view(pages)
                self.assertEqual(result.verdict, "BLOCKED")
                self.assertFalse(result.state.trusted)
                self.assertEqual(result.state.pending, self.state.pending)

    def test_resource_limits(self):
        self.assertEqual(self.run_view(max_pages=0).verdict, "BLOCKED")
        self.assertEqual(self.run_view(max_rows=True).verdict, "BLOCKED")
        row = Row(7, "BTCUSDT", "BOTH", Decimal("1"))
        self.assertEqual(self.run_view((replace(self.page, rows=(row,)),), max_rows=0).verdict, "BLOCKED")

    def test_restart_during_pagination_requires_new_request(self):
        supplied = create_snapshot(self.state)
        resumed = restore(supplied, checkpoint(self.state))
        self.state = resumed.state
        self.state = transition(self.state, Event(self.state.sequence + 1, Signal.CONNECT)).state
        self.state = transition(self.state, Event(self.state.sequence + 1, Signal.RECONCILE)).state
        self.assertEqual(self.run_view().verdict, "BLOCKED")
        self.assertFalse(self.state.trusted)

    def test_side_modes_and_position_identity(self):
        for mode, side, quantity, verdict in (
            ("ONE_WAY", "BOTH", "-1", "PASS"), ("HEDGE", "LONG", "1", "PASS"),
            ("HEDGE", "SHORT", "1", "PASS"), ("HEDGE", "BOTH", "1", "BLOCKED"),
            ("ONE_WAY", "LONG", "1", "BLOCKED"), ("HEDGE", "SHORT", "-1", "BLOCKED"),
        ):
            with self.subTest(mode=mode, side=side):
                view = replace(self.page.inventory, positions=(Position(7, False),))
                page = replace(self.page, inventory=view, mode=mode,
                               rows=(Row(7, "BTCUSDT", side, Decimal(quantity)),))
                self.assertEqual(self.run_view((page,)).verdict, verdict)
                wrong = replace(page, rows=(replace(page.rows[0], position_id=8),))
                self.assertEqual(self.run_view((wrong,)).verdict, "BLOCKED")

    def test_event_permutations_missing_and_repeated_acknowledgments(self):
        self.page = replace(self.page, inventory=replace(self.page.inventory, open_entries=(9,)))
        ack = StreamEvent(1, 1, 9, "ACK", Decimal("0"), Decimal("1"), "BOTH")
        second = replace(ack, sequence=2)
        self.assertEqual(self.run_view(events=(ack, second), watermark=0).verdict, "PASS")
        for events in ((second, ack), (ack,), (ack, ack), (ack, replace(second, version=2))):
            with self.subTest(events=events):
                self.assertEqual(self.run_view(events=events, watermark=0).verdict, "BLOCKED")

    def test_partial_fill_cancel_and_conflicting_confirmation(self):
        first = StreamEvent(1, 1, 9, "FILLED", Decimal("1"), Decimal("1"), "BOTH")
        second = replace(first, sequence=2)
        for events in (
            (replace(first, status="PARTIAL", filled=Decimal(".5")), second),
            (first, replace(second, status="CANCELLED")),
            (replace(first, status="ACK", filled=Decimal("0")), replace(second, status="CANCELLED", filled=Decimal(".5"))),
            (first, replace(second, filled=Decimal(".5"))),
        ):
            self.assertEqual(self.run_view(events=events, watermark=0).verdict, "BLOCKED")
            self.assertFalse(self.state.trusted)

    def test_pending_outcome_requires_stream_confirmation(self):
        self.state = self.run_view().state
        self.state = transition(self.state, Event(4, Signal.ENTRY)).state
        pending = self.state.pending
        self.state = transition(self.state, Event(5, Signal.RECONCILE)).state
        view = replace(self.page.inventory, request=self.state.reconciliation, observed_through=5,
                       account_version=2, resolution=Resolution(pending.request, Outcome.REJECTED))
        page = replace(self.page, inventory=view)
        self.assertEqual(self.run_view((page,), watermark=5, through=5).verdict, "BLOCKED")
        event = StreamEvent(5, 2, pending.target, "REJECTED", Decimal("0"), Decimal("1"), "BOTH")
        result = self.run_view((page,), (event,), watermark=4, through=5)
        self.assertEqual(result.verdict, "PASS")
        self.assertIsNone(result.state.pending)

    def test_cutoff_race_and_stale_version(self):
        for view in (replace(self.page.inventory, observed_through=3),
                     replace(self.page.inventory, account_version=0)):
            self.assertEqual(self.run_view((replace(self.page, inventory=view),)).verdict, "BLOCKED")

    def test_failed_normalization_invalidates_previously_active_state(self):
        self.state = self.run_view().state
        self.assertTrue(self.state.trusted)
        result = self.run_view(())
        self.assertFalse(result.state.trusted)
        self.assertIsNone(transition(result.state, Event(result.state.sequence + 1, Signal.ENTRY)).intent)
