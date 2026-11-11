import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN, localcontext

from demo_futures.demo_safety_mock import (
    Event, IntentKind, Inventory, OperatorDecision, Outcome, PartialAck, Position, ProtectiveOrder,
    RecoveryChoice, Resolution, ReviewStatus, Signal, State, checkpoint,
    create_snapshot, demonstration, restore, transition,
)


DAY = date(2000, 1, 1)


class DemoSafetyMockTests(unittest.TestCase):
    def setUp(self):
        self.state = State()

    def send(self, payload):
        step = transition(self.state, Event(self.state.sequence + 1, payload))
        self.state = step.state
        return step

    def observation(self, **changes):
        self.send(Signal.RECONCILE)
        request = self.state.reconciliation
        positions = changes.get("positions") or ()
        protection = tuple(ProtectiveOrder(100 + position.entry_id, position.entry_id)
                           for position in positions if position.protected)
        view = Inventory(request, request.cutoff, request.prior_version + 1, True, (), (), protection,
                         DAY, Decimal("100"), Decimal("100"))
        return replace(view, **changes)

    def reconcile(self, **changes):
        return self.send(self.observation(**changes))

    def decide(self, choice, target=None):
        view = self.state.inventory
        return self.send(OperatorDecision(view.request, view.account_version, choice, target))

    def reboot(self):
        step = restore(create_snapshot(self.state), checkpoint(self.state))
        self.state = step.state
        return step

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
        restarted = self.reboot()
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
                reply = self.observation()
                self.send(signal)
                self.send(Signal.CONNECT)
                self.assertEqual(self.send(reply).reason, "UNBOUND_RECONCILIATION")
                self.assertIsNone(self.send(Signal.ENTRY).intent)
                self.reconcile()
                self.assertEqual(self.state.mode, "ACTIVE")

    def test_duplicate_replay_does_not_emit_intent_or_restore_trust(self):
        self.start()
        snapshot_event = self.state.journal[-1]
        entry = self.send(Signal.ENTRY).intent
        entry_event = self.state.journal[-1]
        self.reboot()
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
                self.assertIsNone(self.decide(RecoveryChoice.CLOSE_POSITION, 3).intent)

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
        self.assertEqual(self.decide(RecoveryChoice.RESUME).reason, "RESUME_BLOCKED")
        self.assertIsNone(self.send(Signal.ENTRY).intent)

    def test_rejected_protection_persists_across_reconciliation_and_restart(self):
        positions = (Position(7, False),)
        self.start(positions=positions)
        protect = self.send(Signal.PROTECT).intent
        result = self.reconcile(positions=positions,
                                resolution=Resolution(protect.request, Outcome.REJECTED))
        self.assertEqual(result.reason, "SAFETY_ACTION_REJECTED_OPERATOR_REQUIRED")
        self.reboot()
        self.start(positions=positions)
        self.assertEqual(self.state.inventory.positions, positions)
        self.assertEqual(self.send(Signal.PROTECT).reason, "REJECTED_ACTION_REQUIRES_OPERATOR")
        self.assertIsNone(self.send(Signal.ENTRY).intent)

    def test_daily_loss_equality_is_sticky_until_later_day_and_operator_resume(self):
        self.start(equity=Decimal("98.01"))
        self.assertEqual(self.state.mode, "ACTIVE")
        self.reconcile(equity=Decimal("98"))
        self.assertEqual(self.state.mode, "DAILY_HALT")
        self.reboot()
        self.start(equity=Decimal("101"))
        self.assertEqual(self.decide(RecoveryChoice.RESUME).reason, "RESUME_BLOCKED")
        self.reconcile(utc_day=DAY + timedelta(days=1))
        self.assertEqual(self.state.mode, "OPERATOR_HOLD")
        self.assertIsNone(self.send(Signal.ENTRY).intent)
        self.decide(RecoveryChoice.RESUME)
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
        self.assertIsNone(self.decide(RecoveryChoice.CLOSE_POSITION, 3).intent)
        self.reconcile(open_entries=(4,), positions=positions)
        cancel = self.decide(RecoveryChoice.CANCEL_ENTRY, 4).intent
        self.assertEqual((cancel.kind, cancel.target), (IntentKind.CANCEL_ENTRY, 4))
        self.assertIsNone(self.decide(RecoveryChoice.CLOSE_POSITION, 3).intent)
        self.reconcile(positions=positions)
        self.assertEqual(self.state.pending, cancel)
        self.reconcile(positions=positions, resolution=Resolution(cancel.request, Outcome.CANCELLED))
        close = self.decide(RecoveryChoice.CLOSE_POSITION, 3).intent
        self.assertEqual((close.kind, close.target), (IntentKind.CLOSE_POSITION, 3))
        self.assertTrue(close.reduce_only)
        self.assertFalse(self.state.emergency_flat_verified)
        self.reconcile(resolution=Resolution(close.request, Outcome.CLOSED))
        self.assertTrue(self.state.emergency_flat_verified)
        self.assertEqual(self.decide(RecoveryChoice.RESUME).reason, "RESUME_BLOCKED")
        self.reboot()
        self.assertTrue(self.state.kill_latched)
        self.assertFalse(self.state.emergency_flat_verified)

    def test_cancel_fill_race_uses_exposure_from_new_snapshot(self):
        self.start(open_entries=(4,))
        self.send(Signal.KILL)
        self.reconcile(open_entries=(4,))
        cancel = self.decide(RecoveryChoice.CANCEL_ENTRY, 4).intent
        self.reconcile(positions=(Position(4, False),),
                       resolution=Resolution(cancel.request, Outcome.FILLED))
        close = self.decide(RecoveryChoice.CLOSE_POSITION, 4).intent
        self.assertEqual((close.kind, close.target), (IntentKind.CLOSE_POSITION, 4))

    def test_kill_during_disconnected_pending_state_does_not_guess_outcome(self):
        self.start()
        entry = self.send(Signal.ENTRY).intent
        self.send(Signal.DISCONNECT)
        self.send(Signal.KILL)
        self.assertEqual(self.state.mode, "KILLED")
        self.assertIsNone(self.decide(RecoveryChoice.CLOSE_POSITION, 3).intent)
        self.start()
        self.assertEqual(self.state.pending, entry)
        self.assertFalse(self.state.emergency_flat_verified)
        self.assertIsNone(self.decide(RecoveryChoice.CLOSE_POSITION, 3).intent)

    def test_demo_replay_and_rejected_emergency_close_never_retry(self):
        steps = demonstration()
        self.assertEqual(steps, demonstration())
        self.state = next(step.state for step in steps if step.reason == "OPERATOR_HELD")
        self.assertEqual(self.state.mode, "KILLED")
        self.assertEqual(self.state.inventory.positions, (Position(5, False),))
        self.assertFalse(self.state.emergency_flat_verified)
        self.reboot()
        self.start(positions=(Position(5, False),))
        self.assertEqual(self.decide(RecoveryChoice.CLOSE_POSITION, 5).reason, "REJECTED_ACTION_REQUIRES_OPERATOR")

    def test_same_sequence_from_different_fixture_or_history_is_not_a_match(self):
        self.start()
        before = self.state
        for fixture, signal in (("other-fixture", Signal.STALE), (before.fixture_id, Signal.CONNECT)):
            with self.subTest(fixture=fixture, signal=signal):
                self.state = State(fixture_id=fixture)
                self.start()
                self.send(signal)
                reply = self.observation()
                self.state = before
                self.send(Signal.STALE)
                self.send(Signal.RECONCILE)
                self.assertEqual(reply.request.cutoff, self.state.reconciliation.cutoff)
                self.assertEqual(self.send(reply).reason, "UNBOUND_RECONCILIATION")

    def test_pending_identity_and_exact_cutoff_must_match(self):
        self.start()
        pending = self.send(Signal.ENTRY).intent
        view = self.observation(resolution=Resolution(pending.request, Outcome.REJECTED))
        self.assertEqual(view.request.pending, pending)
        forged = replace(view, request=replace(view.request, pending=None))
        self.assertEqual(self.send(forged).reason, "UNBOUND_RECONCILIATION")
        for offset in (-1, 1):
            with self.subTest(offset=offset):
                view = self.observation()
                shifted = replace(view, observed_through=view.request.cutoff + offset)
                self.assertEqual(self.send(shifted).reason, "STALE_OR_CONFLICTING_OBSERVATION")
                self.assertEqual(self.state.pending, pending)
                self.assertFalse(self.state.trusted)

    def test_observation_version_cannot_be_reused_even_after_partial_reply(self):
        self.start()
        partial = self.observation(open_entries=None)
        self.send(partial)
        self.reboot()
        self.send(Signal.CONNECT)
        for version in (partial.account_version - 1, partial.account_version):
            with self.subTest(version=version):
                self.assertEqual(self.reconcile(account_version=version).reason,
                                 "STALE_OR_CONFLICTING_OBSERVATION")
                self.assertFalse(self.state.trusted)
        self.assertEqual(self.reconcile().reason, "RECONCILED")

    def test_snapshot_requires_pinned_current_identity_and_unchanged_content(self):
        self.start()
        older = create_snapshot(self.state)
        self.send(Signal.KILL)
        latest = create_snapshot(self.state)
        expected = checkpoint(self.state)
        changed = replace(latest, journal=(*latest.journal[:-1], Event(self.state.sequence, Signal.STALE)))
        for supplied in (older, changed, replace(latest, checkpoint=replace(expected, schema_version=2))):
            with self.subTest(supplied=supplied):
                with self.assertRaises(ValueError):
                    restore(supplied, expected)
        unsupported = replace(expected, schema_version=2)
        with self.assertRaises(ValueError):
            restore(replace(latest, checkpoint=unsupported), unsupported)
        self.assertTrue(restore(latest, expected).state.kill_latched)

    def test_even_a_matching_digest_cannot_validate_a_discontinuous_journal(self):
        self.start()
        records = self.state.journal
        for journal in (records[1:], (*records, records[-1]), (records[1], records[0], *records[2:])):
            with self.subTest(journal=journal):
                supplied = create_snapshot(replace(self.state, journal=journal))
                with self.assertRaisesRegex(ValueError, "discontinuous"):
                    restore(supplied, supplied.checkpoint)

    def test_snapshot_cannot_silently_omit_state_not_supported_by_its_journal(self):
        self.start()
        for changes in ({"kill_latched": True}, {"observed_version": 1000},
                        {"daily_halt": True}, {"operator_hold": True}):
            with self.subTest(changes=changes):
                supplied = create_snapshot(replace(self.state, **changes))
                with self.assertRaises(ValueError):
                    restore(supplied, supplied.checkpoint)

    def test_fault_snapshot_recovery_retains_kill_and_is_idempotent(self):
        self.start()
        gap = Event(self.state.sequence + 2, Signal.KILL)
        self.state = transition(self.state, gap).state
        self.assertEqual(transition(self.state, gap).state, self.state)
        expected = checkpoint(self.state)
        supplied = create_snapshot(self.state)
        resumed = self.reboot()
        self.assertEqual(resumed, restore(supplied, expected))
        self.assertIsNone(resumed.intent)
        self.assertTrue(self.state.kill_latched and self.state.integrity_fault)
        self.send(Signal.CONNECT)
        self.assertEqual(self.reconcile().reason, "JOURNAL_REVIEW_REQUIRED")
        self.assertFalse(self.state.trusted)
        self.assertFalse(self.state.emergency_flat_verified)

    def test_operator_decisions_require_current_review_and_exact_targets(self):
        positions = (Position(7, True),)
        self.start(positions=positions)
        old = self.state.inventory
        self.assertIsNone(self.decide(RecoveryChoice.CLOSE_POSITION, 7).intent)
        self.send(Signal.KILL)
        self.reconcile(positions=positions, open_entries=(8,))
        stale = OperatorDecision(old.request, old.account_version, RecoveryChoice.CLOSE_POSITION, 7)
        self.assertEqual(self.send(stale).reason, "STALE_OPERATOR_REVIEW")
        self.assertIsNone(self.decide(RecoveryChoice.CLOSE_POSITION, 7).intent)
        self.assertIsNone(self.decide(RecoveryChoice.CANCEL_ENTRY, 7).intent)
        cancel = self.decide(RecoveryChoice.CANCEL_ENTRY, 8).intent
        cancel_event = self.state.journal[-1]
        self.assertEqual(cancel.target, 8)
        self.reboot()
        replay = transition(self.state, cancel_event)
        self.assertIsNone(replay.intent)
        self.assertEqual(replay.state, self.state)
        self.assertEqual(self.state.pending, cancel)

    def test_next_day_partial_observation_cannot_release_daily_latch(self):
        positions = (Position(7, False),)
        self.start(positions=positions, equity=Decimal("98"))
        protect = self.send(Signal.PROTECT).intent
        next_day = DAY + timedelta(days=1)
        self.reconcile(utc_day=next_day, positions=None)
        self.assertTrue(self.state.daily_halt)
        self.assertEqual(self.reconcile(utc_day=next_day, positions=positions).reason,
                         "ACTION_OUTCOME_UNKNOWN")
        self.assertTrue(self.state.daily_halt)
        self.assertEqual(self.state.day, DAY)
        self.assertEqual(self.state.pending, protect)

    def test_new_day_loss_with_unknown_outcome_pins_the_new_daily_latch(self):
        self.start()
        entry = self.send(Signal.ENTRY).intent
        next_day = DAY + timedelta(days=1)
        self.reconcile(utc_day=next_day, equity=Decimal("98"))
        self.reconcile(utc_day=next_day, resolution=Resolution(entry.request, Outcome.REJECTED))
        self.assertEqual(self.state.day, next_day)
        self.assertTrue(self.state.daily_halt)
        self.assertEqual(self.decide(RecoveryChoice.RESUME).reason, "RESUME_BLOCKED")

    def test_rejected_close_cannot_become_flat_from_disappearing_position(self):
        positions = (Position(7, True),)
        self.start(positions=positions)
        self.send(Signal.KILL)
        self.reconcile(positions=positions)
        close = self.decide(RecoveryChoice.CLOSE_POSITION, 7).intent
        self.reconcile(positions=positions, resolution=Resolution(close.request, Outcome.REJECTED))
        self.assertEqual(self.state.review_status, ReviewStatus.REJECTED_SAFETY_ACTION)
        self.assertEqual(self.reconcile().reason, "UNCONFIRMED_EXPOSURE_CHANGE")
        self.assertFalse(self.state.emergency_flat_verified)
        self.assertEqual(self.state.inventory.positions, positions)

    def test_daily_boundary_is_stable_under_caller_decimal_rounding(self):
        with localcontext() as ctx:
            ctx.prec = 1
            ctx.rounding = ROUND_DOWN
            self.start(equity=Decimal("98"))
        self.assertTrue(self.state.daily_halt)

    def test_missing_or_conflicting_protective_orders_cannot_prove_flat(self):
        self.start()
        self.send(Signal.KILL)
        for protection in (None, (ProtectiveOrder(9, 7),)):
            with self.subTest(protection=protection):
                self.reconcile(protective_orders=protection)
                self.assertFalse(self.state.trusted)
                self.assertFalse(self.state.emergency_flat_verified)
        positions = (Position(7, True),)
        for protection in ((), (ProtectiveOrder(8, 7), ProtectiveOrder(8, 7))):
            with self.subTest(protection=protection):
                result = self.reconcile(positions=positions, protective_orders=protection)
                self.assertEqual(result.reason, "CONFLICTING_INVENTORY")
        result = self.reconcile(positions=positions, open_entries=(107,))
        self.assertEqual(result.reason, "CONFLICTING_INVENTORY")
        self.assertEqual(self.reconcile(positions=positions).state.review_status, ReviewStatus.EXPOSURE_PRESENT)

    def test_operator_can_hold_while_pending_but_only_resumes_after_bound_confirmation(self):
        self.start()
        pending = self.send(Signal.ENTRY).intent
        self.assertEqual(self.decide(RecoveryChoice.HOLD).reason, "OPERATOR_HELD")
        self.assertIsNone(self.decide(RecoveryChoice.RESUME).intent)
        self.reboot()
        self.start(resolution=Resolution(pending.request, Outcome.REJECTED))
        self.assertEqual(self.state.review_status, ReviewStatus.HALTED_FLAT)
        self.assertIsNone(self.send(Signal.ENTRY).intent)
        self.assertEqual(self.decide(RecoveryChoice.RESUME).reason, "OPERATOR_RESUMED")
