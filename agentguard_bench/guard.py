"""Deterministic enforcement gate for structured agent actions.

This module never infers permissions from natural-language model output. A trusted host
must build ActionRequest from authenticated user intent and real resource grants, and must
expose approve() only after the owner reviews the exact request.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import secrets
import threading
from typing import Callable, TypeVar


class Decision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class Access(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    OWNER = "owner"


class Authority(str, Enum):
    NONE = "none"
    USER = "user"
    STANDING_POLICY = "standing_policy"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """Normalized, trusted metadata for one proposed action.

    `authority_owner_id`, scope and access must be populated by the host from trusted
    state, never copied from a webpage, model response, email, or user-controlled tool.
    """
    request_id: str
    actor_id: str
    authority_owner_id: str
    action: str
    resource_owner_id: str
    access: Access
    authority: Authority
    within_scope: bool
    external_effect: bool = False
    irreversible: bool = False
    sensitive_data: bool = False
    untrusted_instruction: bool = False

    def __post_init__(self) -> None:
        for name in ("request_id", "actor_id", "authority_owner_id", "action", "resource_owner_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.access, Access) or not isinstance(self.authority, Authority):
            raise TypeError("access and authority must use the Access and Authority enums")
        for name in ("within_scope", "external_effect", "irreversible", "sensitive_data", "untrusted_instruction"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")
        object.__setattr__(self, "action", self.action.strip().lower())


@dataclass(frozen=True, slots=True)
class GuardResult:
    decision: Decision
    reason: str
    request_fingerprint: str


@dataclass(slots=True)
class _Approval:
    request_fingerprint: str
    actor_id: str
    approved: bool = False
    consumed: bool = False


T = TypeVar("T")


class AgentGuard:
    """Fail-closed policy gate with exact-request, one-use approval tickets."""

    _READ_ACTIONS = {"read", "list", "search"}
    _KNOWN_ACTIONS = _READ_ACTIONS | {"write", "send", "delete", "purchase", "publish", "commit", "execute", "install"}
    _APPROVAL_ACTIONS = {"send", "delete", "purchase", "publish", "commit", "execute", "install"}

    def __init__(self) -> None:
        self._approvals: dict[str, _Approval] = {}
        self._lock = threading.RLock()

    @staticmethod
    def fingerprint(request: ActionRequest) -> str:
        payload = json.dumps(asdict(request), sort_keys=True, separators=(",", ":"), default=lambda x: x.value)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def check(self, request: ActionRequest) -> GuardResult:
        """Return a deterministic decision; no action is performed."""
        fp = self.fingerprint(request)
        deny = lambda why: GuardResult(Decision.DENY, why, fp)
        if request.action not in self._KNOWN_ACTIONS:
            return deny("unknown action type; policy fails closed")
        if request.untrusted_instruction or request.authority is Authority.UNTRUSTED:
            return deny("untrusted content cannot authorize an action")
        if request.authority not in {Authority.USER, Authority.STANDING_POLICY}:
            return deny("no trusted authorization source")
        if request.authority_owner_id != request.actor_id:
            return deny("authorization was not granted by this actor")
        if not request.within_scope:
            return deny("action is outside the authorized task scope")

        is_read = request.action in self._READ_ACTIONS
        if is_read:
            if request.access not in {Access.READ, Access.WRITE, Access.OWNER}:
                return deny("resource does not grant read access")
        else:
            # Read sharing is never enough to mutate another owner's resource.
            if request.resource_owner_id != request.actor_id:
                return deny("cross-owner writes are not permitted")
            if request.access not in {Access.WRITE, Access.OWNER}:
                return deny("resource does not grant write access")
        if request.sensitive_data and request.authority is not Authority.USER:
            return deny("sensitive actions require direct user authorization")

        needs_approval = (
            request.external_effect
            or request.irreversible
            or request.action in self._APPROVAL_ACTIONS
        )
        if needs_approval:
            return GuardResult(Decision.REQUIRE_APPROVAL, "exact action needs owner approval", fp)
        return GuardResult(Decision.ALLOW, "within scope and granted resource access", fp)

    def create_approval(self, request: ActionRequest) -> str:
        """Create an opaque ticket for the exact action; this does not approve it."""
        result = self.check(request)
        if result.decision is not Decision.REQUIRE_APPROVAL:
            raise ValueError("approval tickets are only available for actions that require approval")
        ticket = secrets.token_urlsafe(32)
        with self._lock:
            self._approvals[ticket] = _Approval(result.request_fingerprint, request.actor_id)
        return ticket

    def approve(self, ticket: str, *, authenticated_actor_id: str) -> None:
        """Record a human approval; call only from the host's authenticated approval UI."""
        if not isinstance(ticket, str) or not ticket:
            raise ValueError("ticket is required")
        with self._lock:
            approval = self._approvals.get(ticket)
            if approval is None or approval.consumed:
                raise ValueError("approval ticket is missing or already used")
            if authenticated_actor_id != approval.actor_id:
                raise PermissionError("only the requesting actor can approve this action")
            approval.approved = True

    def execute(self, request: ActionRequest, operation: Callable[[], T], *, approval_ticket: str | None = None) -> T:
        """Run a callback only after policy allows it or a matching ticket is approved.

        Hosts should place the real side-effecting operation inside this callback. Approval
        tickets are exact-request-bound and consumed atomically before callback invocation.
        """
        result = self.check(request)
        if result.decision is Decision.DENY:
            raise PermissionError(result.reason)
        if result.decision is Decision.REQUIRE_APPROVAL:
            if not approval_ticket:
                raise ApprovalRequired(result.reason)
            with self._lock:
                approval = self._approvals.get(approval_ticket)
                if (approval is None or not approval.approved or approval.consumed
                        or approval.actor_id != request.actor_id
                        or approval.request_fingerprint != result.request_fingerprint):
                    raise ApprovalRequired("no matching approved ticket for this exact action")
                approval.consumed = True
        elif approval_ticket:
            # Do not accept an unrelated token as a hidden authorization signal.
            raise ValueError("approval ticket supplied for an action that does not need one")
        return operation()


class ApprovalRequired(RuntimeError):
    """The proposed operation was not run because exact owner approval is missing."""
