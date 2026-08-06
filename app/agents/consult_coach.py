from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.llm import deepseek
from app.state.schema import CareerState, SharedState


CoachTrigger = Literal["deepen_entry", "stagnation", "finalizable"]
CoachTerminalStatus = Literal["succeeded", "unavailable"]
CoachChatFunction = Callable[..., Awaitable[str]]

CONSULT_COACH_TIMEOUT_SECONDS = 8.0

CONSULT_COACH_PROMPT = """CONSULT_PM_COACH
You are the supervising PM in a career-consultation group chat. Review the
deterministic progress facts and the current consultation turn. Intervene only
with evidence grounded in the supplied state. Do not invent user facts and do
not ask more than one concise question. Return strict JSON:
{
  "text": string (Chinese, non-empty, max 300 characters),
  "verdict": "pass" | "advise"
}
"""


class CoachReservationConflict(ValueError):
    pass


class _CoachLLMResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1, max_length=300)
    verdict: Literal["pass", "advise"]

    @field_validator("text")
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("coach text must not be blank")
        return stripped


@dataclass(frozen=True)
class CoachAttemptOutcome:
    status: CoachTerminalStatus
    note: dict[str, Any] | None = None
    error_code: str | None = None


def evaluate_consult_l1(
    state: SharedState,
    *,
    round_number: int,
    phase: str,
    completeness_before: float,
    completeness: float,
    can_finalize: bool,
    clarification_turn_active: bool,
    clarification_progress: dict[str, Any],
    coach_max: int,
) -> dict[str, Any]:
    """Build the zero-cost per-turn facts persisted by the first CAS."""
    delta = round(float(completeness) - float(completeness_before), 6)
    previous_streak = 0
    for entry in reversed(state.supervisor_log):
        if not isinstance(entry, dict) or entry.get("stage") != "consult_coach_l1":
            continue
        try:
            if int(entry.get("round") or 0) < int(round_number):
                previous_streak = max(int(entry.get("stagnation_streak") or 0), 0)
                break
        except (TypeError, ValueError):
            continue
    if (
        abs(delta) < 1e-9
        and not can_finalize
        and not clarification_turn_active
    ):
        stagnation_streak = previous_streak + 1
    else:
        stagnation_streak = 0

    progress = {
        key: _nonnegative_int(clarification_progress.get(key))
        for key in ("answered", "skipped", "total", "questions_used")
    }
    return {
        "stage": "consult_coach_l1",
        "round": int(round_number),
        "phase": str(phase),
        "slot_gaps": _required_slot_gaps(state.career_state),
        "completeness_before": round(float(completeness_before), 6),
        "completeness": round(float(completeness), 6),
        "completeness_delta": delta,
        "stagnation_streak": stagnation_streak,
        "clarification_progress": progress,
        "clarification_turn_active": bool(clarification_turn_active),
        "can_finalize": bool(can_finalize),
        "coach_budget_remaining": max(
            int(coach_max) - len(state.coach_reservations),
            0,
        ),
    }


def select_coach_trigger(
    state: SharedState,
    l1_facts: dict[str, Any],
    *,
    coach_max: int,
) -> CoachTrigger | None:
    reservations = state.coach_reservations
    if len(reservations) >= int(coach_max):
        return None
    round_number = _nonnegative_int(l1_facts.get("round"))
    if any(
        isinstance(item, dict)
        and _nonnegative_int(item.get("round")) == round_number
        for item in reservations
    ):
        return None
    consumed = {
        str(item.get("trigger") or "")
        for item in reservations
        if isinstance(item, dict)
    }

    candidates: list[CoachTrigger] = []
    if bool(l1_facts.get("can_finalize")) and _targets_are_exhausted(state):
        candidates.append("finalizable")
    if (
        _nonnegative_int(l1_facts.get("stagnation_streak")) >= 2
        and not bool(l1_facts.get("can_finalize"))
        and not bool(l1_facts.get("clarification_turn_active"))
    ):
        candidates.append("stagnation")
    if str(l1_facts.get("phase") or "") == "deepen":
        candidates.append("deepen_entry")

    return next((trigger for trigger in candidates if trigger not in consumed), None)


def reserve_coach_attempt(
    state: SharedState,
    l1_facts: dict[str, Any],
    *,
    coach_max: int,
    coach_attempt_id: str | None = None,
) -> dict[str, Any] | None:
    trigger = select_coach_trigger(state, l1_facts, coach_max=coach_max)
    if trigger is None:
        return None
    reservation = {
        "coach_attempt_id": coach_attempt_id or str(uuid.uuid4()),
        "round": _nonnegative_int(l1_facts.get("round")),
        "trigger": trigger,
        "status": "reserved",
    }
    state.coach_reservations.append(reservation)
    l1_facts["coach_budget_remaining"] = max(
        int(coach_max) - len(state.coach_reservations),
        0,
    )
    return reservation


def merge_consult_transcript(
    latest: list[dict],
    incoming: list[dict],
) -> list[dict]:
    """Merge turns by round while unioning nested notes by attempt id."""
    merged = [deepcopy(item) for item in latest if isinstance(item, dict)]
    positions = {
        _nonnegative_int(item.get("round")): index
        for index, item in enumerate(merged)
        if _nonnegative_int(item.get("round")) > 0
    }
    for incoming_item in incoming:
        if not isinstance(incoming_item, dict):
            continue
        round_number = _nonnegative_int(incoming_item.get("round"))
        if round_number <= 0 or round_number not in positions:
            merged.append(deepcopy(incoming_item))
            if round_number > 0:
                positions[round_number] = len(merged) - 1
            continue
        position = positions[round_number]
        latest_item = merged[position]
        replacement = deepcopy(incoming_item)
        notes = _merge_notes(
            latest_item.get("supervisor_notes"),
            incoming_item.get("supervisor_notes"),
        )
        if notes:
            replacement["supervisor_notes"] = notes
        else:
            replacement.pop("supervisor_notes", None)
        merged[position] = replacement
    return merged


def merge_coach_reservations(
    latest: list[dict],
    incoming: list[dict],
) -> list[dict]:
    """Union attempts and prevent terminal statuses from moving backwards."""
    merged = [deepcopy(item) for item in latest if isinstance(item, dict)]
    positions = {
        str(item.get("coach_attempt_id") or ""): index
        for index, item in enumerate(merged)
        if str(item.get("coach_attempt_id") or "")
    }
    terminal = {"succeeded", "unavailable"}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        attempt_id = str(item.get("coach_attempt_id") or "")
        if not attempt_id:
            continue
        if attempt_id not in positions:
            positions[attempt_id] = len(merged)
            merged.append(deepcopy(item))
            continue
        position = positions[attempt_id]
        current = merged[position]
        current_status = str(current.get("status") or "")
        incoming_status = str(item.get("status") or "")
        if current_status in terminal:
            continue
        if current_status == "reserved" and incoming_status in terminal:
            merged[position] = deepcopy(item)
    return merged


def finalize_coach_reservation(
    state: SharedState,
    *,
    round_number: int,
    trigger: str,
    coach_attempt_id: str,
    status: CoachTerminalStatus,
    note: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> bool:
    """Apply CAS2 semantics directly to the latest locked state."""
    if status not in {"succeeded", "unavailable"}:
        raise CoachReservationConflict("coach terminal status is invalid")
    if state.career_state.consult_rounds_used < int(round_number):
        raise CoachReservationConflict("coach reservation round is not persisted")

    reservation = next(
        (
            item
            for item in state.coach_reservations
            if isinstance(item, dict)
            and str(item.get("coach_attempt_id") or "") == coach_attempt_id
        ),
        None,
    )
    if reservation is None:
        raise CoachReservationConflict("coach reservation not found")
    if (
        _nonnegative_int(reservation.get("round")) != int(round_number)
        or str(reservation.get("trigger") or "") != trigger
    ):
        raise CoachReservationConflict("coach reservation identity mismatch")

    current_status = str(reservation.get("status") or "")
    if current_status == status:
        return False
    if current_status != "reserved":
        raise CoachReservationConflict("coach reservation is already terminal")

    transcript_entry = next(
        (
            item
            for item in state.career_state.consult_transcript
            if isinstance(item, dict)
            and _nonnegative_int(item.get("round")) == int(round_number)
        ),
        None,
    )
    if transcript_entry is None:
        raise CoachReservationConflict("coach transcript round not found")
    if status == "succeeded":
        if not _note_matches_identity(
            note,
            trigger=trigger,
            coach_attempt_id=coach_attempt_id,
        ):
            raise CoachReservationConflict("coach note identity mismatch")
        notes = _merge_notes(transcript_entry.get("supervisor_notes"), [note])
        if notes:
            transcript_entry["supervisor_notes"] = notes

    reservation["status"] = status
    log_entry: dict[str, Any] = {
        "stage": "consult_coach",
        "round": int(round_number),
        "trigger": trigger,
        "coach_attempt_id": coach_attempt_id,
        "status": status,
    }
    if status == "succeeded" and note is not None:
        log_entry["verdict"] = note["verdict"]
        log_entry["text"] = note["text"]
    elif error_code:
        log_entry["error_code"] = str(error_code)
    if not any(
        isinstance(item, dict)
        and item.get("stage") == "consult_coach"
        and item.get("coach_attempt_id") == coach_attempt_id
        for item in state.supervisor_log
    ):
        state.supervisor_log.append(log_entry)
    return True


async def run_consult_coach(
    state: SharedState,
    *,
    reservation: dict[str, Any],
    l1_facts: dict[str, Any],
    chat: CoachChatFunction | None = None,
    timeout_seconds: float = CONSULT_COACH_TIMEOUT_SECONDS,
) -> CoachAttemptOutcome:
    chat_function = chat or deepseek.chat
    current_round = _nonnegative_int(reservation.get("round"))
    current_turn = next(
        (
            deepcopy(item)
            for item in reversed(state.career_state.consult_transcript)
            if isinstance(item, dict)
            and _nonnegative_int(item.get("round")) == current_round
        ),
        {},
    )
    current_turn.pop("supervisor_notes", None)
    user_prompt = json.dumps(
        {
            "trigger": reservation.get("trigger"),
            "progress_facts": l1_facts,
            "profile": {
                "current_goal": state.career_state.current_goal,
                "long_term_goal": state.career_state.long_term_goal,
                "hard_constraints": state.career_state.hard_constraints,
                "soft_preferences": state.career_state.soft_preferences,
                "avoid_roles": state.career_state.avoid_roles,
            },
            "current_turn": current_turn,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        raw = await asyncio.wait_for(
            chat_function(
                CONSULT_COACH_PROMPT,
                user_prompt,
                pro=False,
                json_mode=True,
            ),
            timeout=float(timeout_seconds),
        )
        parsed = _CoachLLMResponse.model_validate(
            deepseek.extract_json_response(raw)
        )
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        return CoachAttemptOutcome(status="unavailable", error_code="timeout")
    except (json.JSONDecodeError, TypeError, ValidationError):
        return CoachAttemptOutcome(status="unavailable", error_code="parse")
    except Exception:
        return CoachAttemptOutcome(status="unavailable", error_code="service")

    return CoachAttemptOutcome(
        status="succeeded",
        note={
            "kind": "coach",
            "trigger": str(reservation.get("trigger") or ""),
            "text": parsed.text,
            "verdict": parsed.verdict,
            "coach_attempt_id": str(
                reservation.get("coach_attempt_id") or ""
            ),
        },
    )


def _required_slot_gaps(career: CareerState) -> list[str]:
    gaps: list[str] = []
    if not any(str(item).strip() for item in career.current_goal):
        gaps.append("current_goal")
    hard = career.hard_constraints
    locations = hard.get("locations")
    has_location = isinstance(locations, list) and any(
        isinstance(item, str) and item.strip() for item in locations
    )
    if not has_location and hard.get("remote") is not True:
        gaps.append("locations_or_remote")
    if not isinstance(hard.get("need_visa_sponsor"), bool):
        gaps.append("need_visa_sponsor")
    return gaps


def _targets_are_exhausted(state: SharedState) -> bool:
    targets = [
        item
        for item in state.resume_state.clarification_targets
        if isinstance(item, dict)
    ]
    return not targets or all(
        item.get("status") in {"answered", "skipped"} for item in targets
    )


def _merge_notes(latest: Any, incoming: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for collection in (latest, incoming):
        if not isinstance(collection, list):
            continue
        for note in collection:
            if not isinstance(note, dict):
                continue
            attempt_id = str(note.get("coach_attempt_id") or "")
            if not attempt_id or attempt_id in seen:
                continue
            seen.add(attempt_id)
            merged.append(deepcopy(note))
    return merged


def _note_matches_identity(
    note: dict[str, Any] | None,
    *,
    trigger: str,
    coach_attempt_id: str,
) -> bool:
    return bool(
        isinstance(note, dict)
        and note.get("kind") == "coach"
        and note.get("trigger") == trigger
        and note.get("coach_attempt_id") == coach_attempt_id
        and note.get("verdict") in {"pass", "advise"}
        and isinstance(note.get("text"), str)
        and 0 < len(note["text"]) <= 300
    )


def _nonnegative_int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0
