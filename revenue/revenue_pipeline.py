"""Governed revenue-signal pipeline from structural evidence to CRM projection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from .accounts import Account
from .activecampaign_projection import ActiveCampaignProjection, project_activecampaign
from .activecampaign_projection_sync import sync_account_projection
from .intent import IntentEvaluation, evaluate_intent
from .lifecycle import (
    LifecycleError,
    PaymentProof,
    RevenueState,
    allowed_next_states,
    transition,
)
from .lifecycle_store import (
    LifecycleRecord,
    LifecycleStateStore,
    LifecycleStoreError,
)
from .marketing_profiles import MarketingProfile
from .revenue_events import EventStatus, RevenueEvent, RevenueEventStore
from .signals import (
    RevenueSignal,
    SignalContractError,
    SignalRoute,
    authorize_signal_source,
    route_signal,
)

ProjectionSync = Callable[..., Awaitable[dict[str, Any]]]

_FACT_SIGNALS = frozenset(
    {
        "demo_requested",
        "trial_started",
        "checkout_started",
        "checkout_abandoned",
        "payment_confirmed",
        "expansion_signal",
    }
)

_STAGE_RANK = {
    RevenueState.LEAD: 0,
    RevenueState.ENGAGED: 1,
    RevenueState.QUALIFIED: 2,
    RevenueState.TRIAL_OR_DEMO: 3,
    RevenueState.CHECKOUT_STARTED: 4,
    RevenueState.ABANDONED: 4,
    RevenueState.CUSTOMER: 5,
    RevenueState.ONBOARDING: 6,
    RevenueState.ACTIVE_CUSTOMER: 7,
    RevenueState.EXPANSION: 8,
}


class RevenuePipelineError(RuntimeError):
    """Raised when deterministic signal processing cannot be completed."""


@dataclass(frozen=True)
class RevenuePipelineSnapshot:
    lifecycle: LifecycleRecord
    intent: IntentEvaluation
    projection: ActiveCampaignProjection

    def public_view(self) -> dict[str, Any]:
        return {
            "lifecycle": self.lifecycle.public_view(),
            "intent": self.intent.public_view(),
            "projection": self.projection.public_view(),
        }


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _shortest_path(
    current: RevenueState,
    target: RevenueState,
) -> tuple[RevenueState, ...] | None:
    if current == target:
        return ()
    queue: deque[tuple[RevenueState, tuple[RevenueState, ...]]] = deque(
        [(current, ())]
    )
    seen = {current}
    while queue:
        state, path = queue.popleft()
        for next_state in allowed_next_states(state):
            if next_state in seen:
                continue
            next_path = path + (next_state,)
            if next_state == target:
                return next_path
            seen.add(next_state)
            queue.append((next_state, next_path))
    return None


class RevenueSignalPipeline:
    """Persist DSG truth first; project/mutate downstream CRM only afterwards."""

    def __init__(
        self,
        *,
        event_store: Optional[RevenueEventStore] = None,
        lifecycle_store: Optional[LifecycleStateStore] = None,
        projection_sync: ProjectionSync = sync_account_projection,
    ) -> None:
        self.events = event_store or RevenueEventStore()
        self.lifecycle = lifecycle_store or LifecycleStateStore()
        self._projection_sync = projection_sync

    def _account_signal_events(
        self,
        account_id: str,
        *,
        include_received_event_id: Optional[str] = None,
    ) -> list[RevenueEvent]:
        selected = []
        for event in self.events.list_events():
            if event.account_id != account_id:
                continue
            if event.status == EventStatus.PROCESSED:
                selected.append(event)
            elif (
                event.status == EventStatus.RECEIVED
                and event.event_id == include_received_event_id
            ):
                selected.append(event)
        selected.sort(key=lambda item: (item.received_at, item.event_id))
        return selected

    @staticmethod
    def _intent_and_facts(
        events: Iterable[RevenueEvent],
    ) -> tuple[IntentEvaluation, frozenset[str]]:
        intent_events: list[str] = []
        seen_intent: set[str] = set()
        facts: set[str] = set()
        for event in events:
            try:
                route = route_signal(event.event_type)
            except SignalContractError:
                continue
            if route.intent_event and route.intent_event not in seen_intent:
                seen_intent.add(route.intent_event)
                intent_events.append(route.intent_event)
            if route.signal.value in _FACT_SIGNALS:
                facts.add(route.signal.value)
        return evaluate_intent(intent_events), frozenset(facts)

    def _snapshot(
        self,
        *,
        account_id: str,
        marketing_consent: bool,
        include_received_event_id: Optional[str] = None,
    ) -> RevenuePipelineSnapshot:
        lifecycle = self.lifecycle.get(account_id)
        if lifecycle is None:
            raise RevenuePipelineError("revenue lifecycle is not initialized")
        intent, facts = self._intent_and_facts(
            self._account_signal_events(
                account_id,
                include_received_event_id=include_received_event_id,
            )
        )
        projection = project_activecampaign(
            state=lifecycle.state,
            intent=intent,
            marketing_consent=marketing_consent,
            lifecycle_facts=facts,
        )
        return RevenuePipelineSnapshot(
            lifecycle=lifecycle,
            intent=intent,
            projection=projection,
        )

    def _initialize_if_needed(
        self,
        *,
        account_id: str,
        event: RevenueEvent,
    ) -> LifecycleRecord:
        current = self.lifecycle.get(account_id)
        if current is not None:
            return current
        initialized, _ = self.lifecycle.initialize(
            account_id=account_id,
            evidence_ref=f"revenue-event:{event.event_id}:initialize",
            state=RevenueState.LEAD,
        )
        return initialized

    def _advance_lifecycle(
        self,
        *,
        account_id: str,
        event: RevenueEvent,
        route: SignalRoute,
        payment_proof: Optional[PaymentProof],
    ) -> LifecycleRecord:
        record = self._initialize_if_needed(account_id=account_id, event=event)
        target = route.lifecycle_target
        if target is None:
            return record

        if target == record.state:
            return record

        if (
            route.signal == RevenueSignal.CHECKOUT_ABANDONED
            and record.state != RevenueState.CHECKOUT_STARTED
        ):
            raise RevenuePipelineError(
                "checkout_abandoned requires CHECKOUT_STARTED lifecycle truth"
            )

        # Never regress lifecycle truth just because an earlier-funnel signal
        # arrives late. Explicit graph edges such as ABANDONED -> CHECKOUT_STARTED
        # remain eligible because they are checked before the rank fallback.
        direct = target in allowed_next_states(record.state)
        path = (target,) if direct else _shortest_path(record.state, target)
        if path is None:
            if _STAGE_RANK[target] <= _STAGE_RANK[record.state]:
                return record
            raise RevenuePipelineError(
                f"no legal lifecycle path: {record.state.value} -> {target.value}"
            )

        current = record
        for next_state in path:
            proof_for_step = payment_proof if next_state == RevenueState.CUSTOMER else None
            edge_ref = (
                f"revenue-event:{event.event_id}:"
                f"{current.state.value}->{next_state.value}"
            )
            approved = transition(
                account_id=account_id,
                current=current.state,
                target=next_state,
                reason=f"canonical signal {route.signal.value}",
                evidence_ref=edge_ref,
                payment_proof=proof_for_step,
            )
            current, _ = self.lifecycle.apply(
                approved,
                payment_proof=proof_for_step,
            )
        return current

    async def process_signal(
        self,
        *,
        account: Account,
        profile: Optional[MarketingProfile],
        signal: RevenueSignal | str,
        source: str,
        source_event_id: str,
        payload: Optional[Mapping[str, Any]] = None,
        occurred_at: Optional[str] = None,
        trusted_source: bool = False,
        payment_proof: Optional[PaymentProof] = None,
    ) -> dict[str, Any]:
        """Record, govern, persist and project one canonical revenue signal."""

        route = authorize_signal_source(signal, trusted_source=trusted_source)
        if route.requires_payment_proof and (
            payment_proof is None
            or not payment_proof.is_authoritative_for(account.account_id)
        ):
            raise RevenuePipelineError(
                f"{route.signal.value} requires authoritative payment proof"
            )
        if (
            route.signal == RevenueSignal.PAYMENT_CONFIRMED
            and payment_proof is not None
            and payment_proof.source != "stripe_paid_invoice"
        ):
            raise RevenuePipelineError(
                "payment_confirmed accepts only verified Stripe paid-invoice proof"
            )

        event = self.events.record(
            account_id=account.account_id,
            event_type=route.signal.value,
            source=source,
            source_event_id=source_event_id,
            payload=payload,
            occurred_at=occurred_at,
        )
        if event.status == EventStatus.PROCESSED:
            return {
                "duplicate": True,
                "event": event.public_view(),
                "marketing_sync": {"sync_state": "SKIPPED_EVENT_ALREADY_PROCESSED"},
            }
        if event.status == EventStatus.FAILED:
            raise RevenuePipelineError("revenue event is terminal FAILED")

        try:
            self._advance_lifecycle(
                account_id=account.account_id,
                event=event,
                route=route,
                payment_proof=payment_proof,
            )
            snapshot = self._snapshot(
                account_id=account.account_id,
                marketing_consent=bool(profile and profile.marketing_consent),
                include_received_event_id=event.event_id,
            )
            evidence_hash = _canonical_hash(
                {
                    "event_id": event.event_id,
                    "payload_hash": event.payload_hash,
                    "route": route.public_view(),
                    "snapshot": snapshot.public_view(),
                }
            )
            processed = self.events.mark_processed(
                source=event.source,
                source_event_id=event.source_event_id,
                evidence_ref=f"revenue-pipeline:{evidence_hash}",
            )
        except (
            LifecycleError,
            LifecycleStoreError,
            RevenuePipelineError,
            SignalContractError,
            ValueError,
        ) as exc:
            try:
                self.events.mark_failed(
                    source=event.source,
                    source_event_id=event.source_event_id,
                    failure_reason=type(exc).__name__,
                )
            except Exception:
                pass
            if isinstance(exc, RevenuePipelineError):
                raise
            raise RevenuePipelineError(str(exc)) from exc

        # CRM is deliberately after durable DSG truth. A network failure is
        # returned for retry/reconciliation and cannot rewrite event/lifecycle.
        marketing_sync = await self._projection_sync(
            account,
            profile,
            projection=snapshot.projection,
            source=source,
            signal=route.signal.value,
        )
        return {
            "duplicate": False,
            "event": processed.public_view(),
            **snapshot.public_view(),
            "marketing_sync": marketing_sync,
        }

    async def sync_current_projection(
        self,
        *,
        account: Account,
        profile: Optional[MarketingProfile],
        source: Optional[str] = None,
    ) -> dict[str, Any]:
        """Retry downstream CRM projection without changing DSG lifecycle truth."""

        lifecycle = self.lifecycle.get(account.account_id)
        if lifecycle is None:
            return {
                "sync_state": "PENDING_NO_LIFECYCLE",
                "account_id": account.account_id,
            }
        snapshot = self._snapshot(
            account_id=account.account_id,
            marketing_consent=bool(profile and profile.marketing_consent),
        )
        sync = await self._projection_sync(
            account,
            profile,
            projection=snapshot.projection,
            source=source or (profile.source if profile else account.channel),
            signal=None,
        )
        return {
            "account_id": account.account_id,
            **snapshot.public_view(),
            "marketing_sync": sync,
        }


_pipeline: Optional[RevenueSignalPipeline] = None
_pipeline_paths: tuple[Optional[str], Optional[str]] | None = None


def _env_path(name: str) -> Optional[str]:
    return (os.getenv(name) or "").strip() or None


def get_revenue_pipeline() -> RevenueSignalPipeline:
    global _pipeline, _pipeline_paths
    paths = (
        _env_path("DSG_REVENUE_EVENT_STORE"),
        _env_path("DSG_REVENUE_LIFECYCLE_STORE"),
    )
    if _pipeline is None or _pipeline_paths != paths:
        _pipeline = RevenueSignalPipeline(
            event_store=RevenueEventStore(paths[0]),
            lifecycle_store=LifecycleStateStore(paths[1]),
        )
        _pipeline_paths = paths
    return _pipeline


def reset_revenue_pipeline(
    pipeline: Optional[RevenueSignalPipeline] = None,
) -> RevenueSignalPipeline:
    global _pipeline, _pipeline_paths
    if pipeline is None:
        _pipeline = None
        _pipeline_paths = None
        return get_revenue_pipeline()
    _pipeline = pipeline
    _pipeline_paths = (
        _env_path("DSG_REVENUE_EVENT_STORE"),
        _env_path("DSG_REVENUE_LIFECYCLE_STORE"),
    )
    return pipeline


__all__ = [
    "RevenuePipelineError",
    "RevenuePipelineSnapshot",
    "RevenueSignalPipeline",
    "get_revenue_pipeline",
    "reset_revenue_pipeline",
]
