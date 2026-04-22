"""
dialogs/slot_filling.py

Slot-filling engine for the Teams Help Bot.

State is stored directly in the Bot Framework conversation_data dict
(prefixed with "sf_") so it persists across turns automatically.

Usage in main_dialog.py:
    from dialogs.slot_filling import is_active, handle_slot_turn, start_slot_filling
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from services import connectwise_service as cw


# ─────────────────────────────────────────────────────────
#  SLOT DEFINITIONS
# ─────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""
    normalized: str = ""


@dataclass
class SlotDefinition:
    key: str
    label: str
    required: bool
    question: str
    hint: str
    validator: Callable[[str], ValidationResult]
    default: Optional[str] = None


def _validate_subject(value: str) -> ValidationResult:
    if not value or len(value.strip()) < 5:
        return ValidationResult(
            valid=False,
            reason="Please give a brief description (at least 5 characters)."
        )
    return ValidationResult(valid=True)


def _validate_company(value: str) -> ValidationResult:
    if not value or len(value.strip()) < 2:
        return ValidationResult(
            valid=False,
            reason="Please provide a company name."
        )
    return ValidationResult(valid=True)


def _validate_priority(value: str) -> ValidationResult:
    allowed = ["low", "medium", "high", "urgent"]
    normalized = value.strip().lower()
    if normalized not in allowed:
        return ValidationResult(
            valid=False,
            reason=f"Priority must be one of: {', '.join(allowed)}."
        )
    return ValidationResult(valid=True, normalized=normalized)


TICKET_SLOTS: List[SlotDefinition] = [
    SlotDefinition(
        key="subject",
        label="Subject",
        required=True,
        question="What's the issue or subject of this ticket?",
        hint="e.g. 'Outlook keeps crashing' or 'VPN won't connect'",
        validator=_validate_subject,
    ),
    SlotDefinition(
        key="company",
        label="Company",
        required=True,
        question="Which company or client is this ticket for?",
        hint="e.g. 'IT By Design' or 'TeamGPS'",
        validator=_validate_company,
    ),
    SlotDefinition(
        key="priority",
        label="Priority",
        required=False,
        default="medium",
        question="What priority should this be? (low / medium / high / urgent)",
        hint="If you're unsure, I'll set it to medium.",
        validator=_validate_priority,
    ),
]


# ─────────────────────────────────────────────────────────
#  STATE HELPERS  (stored as sf_* keys in conversation_data)
# ─────────────────────────────────────────────────────────

def is_active(conversation_data: dict) -> bool:
    """True when a slot-filling session is in progress."""
    return bool(conversation_data.get("sf_intent"))


def _clear(conversation_data: dict) -> None:
    for key in ["sf_intent", "sf_slots", "sf_awaiting_slot",
                "sf_awaiting_confirm", "sf_last_question"]:
        conversation_data.pop(key, None)


# ─────────────────────────────────────────────────────────
#  PRE-FILL FROM OPENING MESSAGE
# ─────────────────────────────────────────────────────────

_SUBJECT_PATTERNS = [
    re.compile(r'\babout\s+(.{5,80}?)(?:\.|,|$)', re.IGNORECASE),
    re.compile(r'\bregarding\s+(.{5,80}?)(?:\.|,|$)', re.IGNORECASE),
    re.compile(r'issue[:\s]+(.{5,80}?)(?:\.|,|$)', re.IGNORECASE),
    re.compile(r'problem[:\s]+(.{5,80}?)(?:\.|,|$)', re.IGNORECASE),
    re.compile(r'error[:\s]+(.{5,80}?)(?:\.|,|$)', re.IGNORECASE),
]
_COMPANY_PATTERN  = re.compile(
    r'\bfor\s+([A-Z][A-Za-z\s&.\'-]{1,30}?)(?:\s+about|\s+regarding|[,.]|$)'
)
_PRIORITY_PATTERN = re.compile(
    r'\b(low|medium|normal|high|urgent)\b(?:\s+priority)?', re.IGNORECASE
)


def _pre_fill(message: str) -> Dict[str, str]:
    extracted: Dict[str, str] = {}
    lower = message.lower()

    match = _PRIORITY_PATTERN.search(lower)
    if match:
        raw = match.group(1).lower()
        extracted["priority"] = "medium" if raw == "normal" else raw
    if "priority" not in extracted:
        if any(w in lower for w in ("asap", "critical", "urgent")):
            extracted["priority"] = "high"

    match = _COMPANY_PATTERN.search(message)
    if match:
        extracted["company"] = match.group(1).strip()

    for pattern in _SUBJECT_PATTERNS:
        match = pattern.search(message)
        if match:
            extracted["subject"] = match.group(1).strip()
            break

    return extracted


# ─────────────────────────────────────────────────────────
#  SLOT UTILITIES
# ─────────────────────────────────────────────────────────

def _find_next_missing(slots: dict) -> Optional[SlotDefinition]:
    for slot_def in TICKET_SLOTS:
        if slot_def.required and slot_def.key not in slots:
            return slot_def
    return None


def _apply_defaults(slots: dict) -> dict:
    filled = dict(slots)
    for slot_def in TICKET_SLOTS:
        if slot_def.key not in filled and slot_def.default is not None:
            filled[slot_def.key] = slot_def.default
    return filled


def _validate(slot_key: str, value: str) -> ValidationResult:
    slot_def = next((s for s in TICKET_SLOTS if s.key == slot_key), None)
    if not slot_def:
        return ValidationResult(valid=True)
    return slot_def.validator(value)


def _build_confirmation(slots: dict) -> str:
    return "\n".join([
        "Here's what I'll create:",
        "",
        f"📋  **Subject:** {slots.get('subject', '—')}",
        f"🏢  **Company:** {slots.get('company', '—')}",
        f"⚡  **Priority:** {slots.get('priority', '—')}",
        "",
        "Reply **yes** to confirm, or tell me what to change.",
    ])


# ─────────────────────────────────────────────────────────
#  INLINE CORRECTION (during confirmation step)
# ─────────────────────────────────────────────────────────

_PRIORITY_CORRECTION = re.compile(
    r'priority\s+(?:is|to|=)\s*(low|medium|high|urgent)', re.IGNORECASE
)
_COMPANY_CORRECTION = re.compile(
    r'(?:company\s+is|for)\s+([A-Z][A-Za-z\s&.\'-]{1,30}?)(?:\.|,|$)', re.IGNORECASE
)
_SUBJECT_CORRECTION = re.compile(
    r'(?:subject\s+is|change\s+to)\s+(.{5,80}?)(?:\.|,|$)', re.IGNORECASE
)


def _try_correction(slots: dict, message: str) -> Tuple[bool, dict]:
    match = _PRIORITY_CORRECTION.search(message)
    if match:
        vr = _validate("priority", match.group(1))
        if vr.valid:
            slots["priority"] = vr.normalized or match.group(1).lower()
            return True, slots

    match = _COMPANY_CORRECTION.search(message)
    if match:
        slots["company"] = match.group(1).strip()
        return True, slots

    match = _SUBJECT_CORRECTION.search(message)
    if match:
        slots["subject"] = match.group(1).strip()
        return True, slots

    return False, slots


# ─────────────────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────────────────

_CONFIRM_YES = {"yes", "confirm", "ok", "go ahead", "do it", "yep", "yeah"}
_CONFIRM_NO  = {"no", "cancel", "stop", "abort"}


def start_slot_filling(conversation_data: dict, opening_message: str) -> str:
    """
    Begin a new slot-filling session.
    Call this when CREATE_TICKET intent is detected.
    Returns the bot's first reply.
    """
    _clear(conversation_data)
    conversation_data["sf_intent"] = "create_ticket"
    conversation_data["sf_slots"]  = _pre_fill(opening_message)
    return _next_reply(conversation_data)


async def handle_slot_turn(conversation_data: dict, user_message: str) -> str:
    """
    Process one turn of an active slot-filling session.
    Returns the bot's reply for this turn.
    """
    trimmed = user_message.strip()
    slots   = conversation_data.get("sf_slots", {})

    # ── A) Confirmation step ──────────────────────────────
    if conversation_data.get("sf_awaiting_confirm"):
        lower = trimmed.lower()

        if lower in _CONFIRM_YES:
            try:
                board, ticket_type, _ = _triage(slots.get("subject", ""))
                ticket = cw.create_ticket(
                    summary=slots["subject"],
                    priority=slots["priority"],
                    board=board,
                    ticket_type=ticket_type,
                    user_name=slots.get("company", ""),
                )
                subject = slots.get("subject", "")
                _clear(conversation_data)
                return "\n".join([
                    f"✅ Ticket **#{ticket.get('id')}** created successfully!",
                    "",
                    f"_Subject: {subject}_",
                    f"_Board: {board} — {ticket_type}_",
                    "",
                    "What would you like to do next?",
                    "• Add a note to this ticket",
                    "• Create another ticket",
                    "• Check ticket status",
                ])
            except Exception as e:
                _clear(conversation_data)
                return (
                    f"⚠️ Could not create the ticket: {e}\n\n"
                    "Please contact your helpdesk directly."
                )

        if lower in _CONFIRM_NO:
            _clear(conversation_data)
            return "Cancelled. Let me know if you need anything else."

        # Inline correction
        applied, updated_slots = _try_correction(slots, trimmed)
        if applied:
            conversation_data["sf_slots"] = _apply_defaults(updated_slots)
            return f"Updated. {_build_confirmation(conversation_data['sf_slots'])}"

        return "\n".join([
            "I'm not sure what to change. You can say things like:",
            '• "change priority to high"',
            '• "company is IT By Design"',
            '• "subject is Outlook not opening"',
            "",
            "Or reply **yes** to confirm or **no** to cancel.",
        ])

    # ── B) Answering a slot question ──────────────────────
    if conversation_data.get("sf_awaiting_slot"):
        slot_key = conversation_data["sf_awaiting_slot"]
        vr = _validate(slot_key, trimmed)

        if not vr.valid:
            return f"{vr.reason}\n\n{conversation_data.get('sf_last_question', '')}"

        slots[slot_key] = vr.normalized or trimmed
        conversation_data["sf_slots"]        = slots
        conversation_data["sf_awaiting_slot"] = None

    return _next_reply(conversation_data)


def _next_reply(conversation_data: dict) -> str:
    """Check for missing slots; if all filled show confirmation."""
    slots   = conversation_data.get("sf_slots", {})
    missing = _find_next_missing(slots)

    if missing:
        question = f"{missing.question}\n_{missing.hint}_"
        conversation_data["sf_awaiting_slot"] = missing.key
        conversation_data["sf_last_question"] = question
        return question

    # All required slots filled
    conversation_data["sf_slots"]          = _apply_defaults(slots)
    conversation_data["sf_awaiting_confirm"] = True
    return _build_confirmation(conversation_data["sf_slots"])


# ─────────────────────────────────────────────────────────
#  TRIAGE (mirrors main_dialog.py)
# ─────────────────────────────────────────────────────────

_TRIAGE_RULES = [
    (["outlook", "email", "calendar", "ost", "mail"],      "Professional Services", "Email Issue",          "Medium"),
    (["slow", "freeze", "crash", "blue screen", "bsod"],   "Professional Services", "Performance",          "High"),
    (["printer", "print", "scan"],                         "Professional Services", "Hardware",             "Medium"),
    (["vpn", "remote", "rdp"],                             "Professional Services", "Network/Connectivity", "High"),
    (["password", "locked out", "login", "access denied"], "Professional Services", "Account Access",       "High"),
    (["wifi", "internet", "network", "no connection"],     "Professional Services", "Network/Connectivity", "High"),
    (["install", "software", "application"],               "Professional Services", "Software Request",     "Low"),
]


def _triage(summary: str) -> tuple:
    lower = (summary or "").lower()
    for keywords, board, ticket_type, priority in _TRIAGE_RULES:
        if any(k in lower for k in keywords):
            return board, ticket_type, priority
    return "Professional Services", "General Request", "Medium"
