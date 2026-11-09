import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from demo_futures.demo_safety_mock import (
    Event, IntentKind, Inventory, Outcome, PartialAck, Position, Resolution,
    Signal, State, demonstration, transition,
)


DAY = date(2000, 1, 1)


class DemoSafetyMockTests(unittest.TestCase):
    def setUp(self):
        self.state = State()

    def send(self, payload):
        step = transition(self.state, Event(len(self.state.journal) + 1, payload))
        self.state = step.state
        return step

    def reconcile(self, **changes):
        request = self.send(Signal.RECONCILE).intent.request
        view = Inventory(request, True, (), (), DAY, Decimal("100"), Decimal("100"))
        return self.send(replace(view, **changes))

    def start(self, **changes):
        self.send(Signal.CONNECT)
        self.reconcile(**changes)

    def test_startup_blocks_entry_until_fresh_complete_inventory(self):
        self.assertIsNone(self.send(Signal.ENTRY).intent)
        self.start(open_entries=None)
        self.assertEqual(self.state.mode, "RECONCILIATION_REQUIRED")
        self.assertIsNone(self.send(Signal.ENTRY).intent)
        self.reconcile(positions=None)
        self.assertIsNone(self.send(Signal.ENTRY).intent)
        self.reconcile(fresh=False)
        self.assertIsNone(self.send(Signal.ENTRY).intent)
        self.reconcile()
        self.assertEqual(self.state.mode, "ACTIVE")
        self.assertEqual(self.send(Signal.ENTRY).intent.kind, IntentKind.ENTRY)

    def test_entry_reserves_capacity_and_explicit_open_outcome_occupies_slot(self):
        self.start()
        entry = self.send(Signal.ENTRY).intent
        self.assertIsNone(self.send(Signal.ENTRY).intent)
        self.reconcile(open_entries=(entry.target,), resolution=Resolution(entry.request, Outcome.OPEN))
        self.assertIsNone(self.state.pending)
        self.assertEqual(self.send(Signal.ENTRY).reason, "ENTRY_BLOCKED")

    def test_missing_outcome_stays_pending_after_partial_ack_and_restart(self):
        self.start()
        entry = self.send(Signal.ENTRY).intent
        self.assertEqual(self.send(PartialAck(entry.request)).reason, "PARTIAL_ACKNOWLEDGMENT")
        self.send(Signal.DISCONNECT)
        checkpoint = self.state
        restarted = self.send(Signal.RESTART)
        self.assertEqual(restarted, transition(checkpoint, self.state.journal[-1]))
        self.start()
        self.assertEqual(self.state.pending, entry)
        self.assertIsNone(self.send(Signal.ENTRY).intent)
        self.reconcile(resolution=Resolution(entry.request, Outcome.REJECTED))
        self.assertIsNone(self.state.pending)
        self.assertEqual(self.state.mode, "ACTIVE")

    def test_stale_and_disconnect_invalidate_outstanding_snapshot_tokens(self):
        for signal in (Signal.STALE, Signal.DISCONNECT, Signal.RESTART):
            with self.subTest(signal=signal):
                self.state = State()
                self.start()
                old = self.send(Signal.RECONCILE).intent.request
                self.send(signal)
                self.send(Signal.CONNECT)
                reply = replace(self.state.inventory, request=old)
                self.assertEqual(self.send(reply).reason, "UNBOUND_RECONCILIATION")
                self.assertIsNone(self.send(Signal.ENTRY).intent)
                self.reconcile()
                self.assertEqual(self.state.mode, "ACTIVE")

    def test_duplicate_replay_does_not_emit_intent_or_restore_trust(self):
        self.start()
        snapshot_event = self.state.journal[-1]
        entry = self.send(Signal.ENTRY).intent
        entry_event = self.state.journal[-1]
        self.send(Signal.RESTART)
        for event in (snapshot_event, entry_event):
            replay = transition(self.state, event)
            self.assertEqual(replay.state, self.state)
            self.assertIsNone(replay.intent)
            self.assertEqual(replay.reason, "DUPLICATE_IGNORED")
        self.assertEqual(self.state.pending, entry)
        self.assertFalse(self.state.trusted)

    def test_conflicting_or_skipped_events_latch_integrity_and_kill_wins(self):
        for sequence in (1, 50):
            with self.subTest(sequence=sequence):
                self.state = State()
                self.start()
                conflict = transition(self.state, Event(sequence, Signal.KILL))
                self.state = conflict.state
                self.assertTrue(self.state.integrity_fault)
                self.assertTrue(self.state.kill_latched)
                self.assertEqual(self.state.mode, "KILLED")
                self.reconcile()
                self.assertFalse(self.state.emergency_flat_verified)
                self.assertIsNone(self.send(Signal.EMERGENCY_STEP).intent)

    def test_conflicting_resolution_or_unknown_ack_cannot_clear_pending(self):
        self.start()
        entry = self.send(Signal.ENTRY).intent
        self.assertEqual(self.send(PartialAck(entry.request + 1)).reason, "UNBOUND_ACKNOWLEDGMENT")
        for resolution in (Resolution(entry.request + 1, Outcome.REJECTED),
                           Resolution(entry.request, Outcome.FILLED)):
            with self.subTest(resolution=resolution):
                step = self.reconcile(resolution=resolution)
                self.assertEqual(step.reason, "CONFLICTING_ACTION_RESOLUTION")
                self.assertEqual(self.state.pending, entry)
                self.assertIsNone(self.send(Signal.ENTRY).intent)

    def test_conflicting_and_malformed_inventory_fail_closed(self):
        self.start(open_entries=(1, 1))
        self.assertFalse(self.state.trusted)
        self.reconcile(open_entries=(1,), positions=(Position(1, True),))
        self.assertFalse(self.state.trusted)
        self.reconcile(equity=Decimal("sNaN"))
        self.assertTrue(self.state.integrity_fault)
        self.assertIsNone(self.send(Signal.ENTRY).intent)

    def test_protection_intent_is_reduce_only_and_success_preserves_exposure(self):
        self.start(positions=(Position(7, False),))
        self.assertEqual(self.state.mode, "OPERATOR_HOLD")
        protect = self.send(Signal.PROTECT).intent
        self.assertEqual((protect.kind, protect.target), (IntentKind.PROTECT, 7))
        self.assertTrue(protect.reduce_only)
        self.reconcile(positions=(Position(7, True),),
                       resolution=Resolution(protect.request, Outcome.PROTECTED))
        self.assertEqual(self.state.inventory.positions, (Position(7, True),))
        self.assertEqual(self.send(Signal.OPERATOR_RESUME).reason, "RESUME_BLOCKED")
        self.assertIsNone(self.send(Signal.ENTRY).intent)

    def test_rejected_protection_persists_across_reconciliation_and_restart(self):
        positions = (Position(7, False),)
        self.start(positions=positions)
        protect = self.send(Signal.PROTECT).intent
        result = self.reconcile(positions=positions,
                                resolution=Resolution(protect.request, Outcome.REJECTED))
        self.assertEqual(result.reason, "SAFETY_ACTION_REJECTED_OPERATOR_REQUIRED")
        self.send(Signal.RESTART)
        self.start(positions=positions)
        self.assertEqual(self.state.inventory.positions, positions)
        self.assertEqual(self.send(Signal.PROTECT).reason, "REJECTED_ACTION_REQUIRES_OPERATOR")
        self.assertIsNone(self.send(Signal.ENTRY).intent)

    def test_daily_loss_equality_is_sticky_until_later_day_and_operator_resume(self):
        self.start(equity=Decimal("98.01"))
        self.assertEqual(self.state.mode, "ACTIVE")
        self.reconcile(equity=Decimal("98"))
        self.assertEqual(self.state.mode, "DAILY_HALT")
        self.send(Signal.RESTART)
        self.start(equity=Decimal("101"))
        self.assertEqual(self.send(Signal.OPERATOR_RESUME).reason, "RESUME_BLOCKED")
        self.reconcile(utc_day=DAY + timedelta(days=1))
        self.assertEqual(self.state.mode, "OPERATOR_HOLD")
        self.assertIsNone(self.send(Signal.ENTRY).intent)
        self.send(Signal.OPERATOR_RESUME)
        self.assertEqual(self.state.mode, "ACTIVE")

    def test_changed_anchor_or_older_day_cannot_clear_halt(self):
        self.start(equity=Decimal("98"))
        for changes in ({"opening_equity": Decimal("90")}, {"utc_day": DAY - timedelta(days=1)}):
            with self.subTest(changes=changes):
                self.assertEqual(self.reconcile(**changes).reason, "CONFLICTING_DAILY_ANCHOR")
                self.assertEqual(self.state.mode, "DAILY_HALT")
                self.assertEqual(self.state.anchor, Decimal("100"))

    def test_known_daily_loss_latches_while_pending_outcome_is_unknown(self):
        self.start()
        pending = self.send(Signal.ENTRY).intent
        self.assertEqual(self.reconcile(equity=Decimal("98")).reason, "ACTION_OUTCOME_UNKNOWN")
        self.assertEqual(self.state.mode, "DAILY_HALT")
        self.assertEqual(self.state.pending, pending)

    def test_kill_cancels_only_entry_then_requires_reconciliation_before_close(self):
        positions = (Position(3, True),)
        self.start(open_entries=(4,), positions=positions)
        self.assertEqual(self.state.mode, "OPERATOR_HOLD")
        self.assertIsNone(self.send(Signal.KILL).intent)
        self.assertIsNone(self.send(Signal.EMERGENCY_STEP).intent)
        self.reconcile(open_entries=(4,), positions=positions)
        cancel = self.send(Signal.EMERGENCY_STEP).intent
        self.assertEqual((cancel.kind, cancel.target), (IntentKind.CANCEL_ENTRY, 4))
        self.assertIsNone(self.send(Signal.EMERGENCY_STEP).intent)
        self.reconcile(positions=positions)
        self.assertEqual(self.state.pending, cancel)
        self.reconcile(positions=positions, resolution=Resolution(cancel.request, Outcome.CANCELLED))
        close = self.send(Signal.EMERGENCY_STEP).intent
        self.assertEqual((close.kind, close.target), (IntentKind.CLOSE_POSITION, 3))
        self.assertTrue(close.reduce_only)
        self.assertFalse(self.state.emergency_flat_verified)
        self.reconcile(resolution=Resolution(close.request, Outcome.CLOSED))
        self.assertTrue(self.state.emergency_flat_verified)
        self.assertEqual(self.send(Signal.OPERATOR_RESUME).reason, "RESUME_BLOCKED")
        self.send(Signal.RESTART)
        self.assertTrue(self.state.kill_latched)
        self.assertFalse(self.state.emergency_flat_verified)

    def test_cancel_fill_race_uses_exposure_from_new_snapshot(self):
        self.start(open_entries=(4,))
        self.send(Signal.KILL)
        self.reconcile(open_entries=(4,))
        cancel = self.send(Signal.EMERGENCY_STEP).intent
        self.reconcile(positions=(Position(4, False),),
                       resolution=Resolution(cancel.request, Outcome.FILLED))
        close = self.send(Signal.EMERGENCY_STEP).intent
        self.assertEqual((close.kind, close.target), (IntentKind.CLOSE_POSITION, 4))

    def test_kill_during_disconnected_pending_state_does_not_guess_outcome(self):
        self.start()
        entry = self.send(Signal.ENTRY).intent
        self.send(Signal.DISCONNECT)
        self.send(Signal.KILL)
        self.assertEqual(self.state.mode, "KILLED")
        self.assertIsNone(self.send(Signal.EMERGENCY_STEP).intent)
        self.start()
        self.assertEqual(self.state.pending, entry)
        self.assertFalse(self.state.emergency_flat_verified)
        self.assertIsNone(self.send(Signal.EMERGENCY_STEP).intent)

    def test_demo_replay_and_rejected_emergency_close_never_retry(self):
        steps = demonstration()
        self.assertEqual(steps, demonstration())
        self.state = steps[-1].state
        self.assertEqual(self.state.mode, "KILLED")
        self.assertEqual(self.state.inventory.positions, (Position(5, False),))
        self.assertFalse(self.state.emergency_flat_verified)
        self.send(Signal.RESTART)
        self.start(positions=(Position(5, False),))
        self.assertEqual(self.send(Signal.EMERGENCY_STEP).reason, "REJECTED_ACTION_REQUIRES_OPERATOR")
