"""Central policy and confirmation authority for task plans.

Risk is derived only from executor capabilities, never from labels such as
"发送" or "Delete".  Ambiguous UI actions therefore fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import secrets
from typing import Callable, Iterable

from .plan import TaskPlan, TaskStep


class RiskLevel(str, Enum):
    SAFE_NAVIGATION = "SAFE_NAVIGATION"
    SAFE_READ = "SAFE_READ"
    USER_CONFIRM_REQUIRED = "USER_CONFIRM_REQUIRED"
    DESTRUCTIVE = "DESTRUCTIVE"


class AuthorizationError(PermissionError):
    """Raised when a plan or step lacks valid human authorization."""


@dataclass(frozen=True)
class ConfirmationRequest:
    plan_digest: str
    step_id: str
    risk: RiskLevel
    prompt: str
    step: TaskStep


@dataclass(frozen=True)
class ConfirmationToken:
    plan_digest: str
    step_id: str
    risk: RiskLevel
    nonce: str
    signature: str


@dataclass(frozen=True)
class Authorization:
    plan_digest: str
    tokens: tuple[ConfirmationToken, ...]


Confirmer = Callable[[ConfirmationRequest], bool]


_RISK_BY_TYPE = {
    "open_app": RiskLevel.SAFE_NAVIGATION,
    "home": RiskLevel.SAFE_NAVIGATION,
    "back": RiskLevel.SAFE_NAVIGATION,
    "swipe": RiskLevel.SAFE_NAVIGATION,
    "wait": RiskLevel.SAFE_NAVIGATION,
    "read_ui": RiskLevel.SAFE_READ,
    # A label/resource does not prove the effect of a click.  Generic taps and
    # typing are ambiguous and require confirmation regardless of target text.
    "tap": RiskLevel.USER_CONFIRM_REQUIRED,
    "tap_resource": RiskLevel.USER_CONFIRM_REQUIRED,
    "tap_coordinates": RiskLevel.USER_CONFIRM_REQUIRED,
    "long_press": RiskLevel.USER_CONFIRM_REQUIRED,
    "type_text": RiskLevel.USER_CONFIRM_REQUIRED,
    "type_unicode": RiskLevel.USER_CONFIRM_REQUIRED,
    "swipe_coordinates": RiskLevel.SAFE_NAVIGATION,
    "send": RiskLevel.USER_CONFIRM_REQUIRED,
    "purchase": RiskLevel.USER_CONFIRM_REQUIRED,
    "ask": RiskLevel.USER_CONFIRM_REQUIRED,
    "delete": RiskLevel.DESTRUCTIVE,
    "install": RiskLevel.DESTRUCTIVE,
    "change_settings": RiskLevel.DESTRUCTIVE,
}


class PolicyEngine:
    """Validate plans, classify risk, and issue plan-bound authorizations."""

    def __init__(self, secret: bytes | None = None) -> None:
        self.__secret = secret or secrets.token_bytes(32)

    def validate(self, plan: TaskPlan) -> TaskPlan:
        if not isinstance(plan, TaskPlan):
            raise TypeError("policy accepts only a validated TaskPlan")
        # Reparse the serialized form so manually constructed dataclasses do
        # not bypass schema validation.
        return TaskPlan.from_dict(plan.to_dict())

    def risk_classify(self, step: TaskStep) -> RiskLevel:
        try:
            return _RISK_BY_TYPE[step.type]
        except KeyError as exc:
            raise AuthorizationError(
                f"no policy rule for step type {step.type!r}") from exc

    def authorize(
        self,
        plan: TaskPlan,
        *,
        confirmer: Confirmer | None = None,
        tokens: Iterable[ConfirmationToken] = (),
    ) -> Authorization:
        plan = self.validate(plan)
        digest = plan.digest()
        accepted = [token for token in tokens if self._valid_token(token, digest)]
        by_step = {token.step_id: token for token in accepted}
        pending_prompt: str | None = None

        for step in plan.steps:
            if step.type == "ask":
                pending_prompt = str(step.arguments["prompt"])
                continue
            risk = self.risk_classify(step)
            if risk in {RiskLevel.SAFE_NAVIGATION, RiskLevel.SAFE_READ}:
                pending_prompt = None
                continue
            if step.id in by_step:
                pending_prompt = None
                continue
            prompt = pending_prompt or self._default_prompt(step, risk)
            request = ConfirmationRequest(digest, step.id, risk, prompt, step)
            if confirmer is None or confirmer(request) is not True:
                raise AuthorizationError(
                    f"{risk.value} step {step.id!r} requires human confirmation")
            token = self._mint(request)
            accepted.append(token)
            by_step[step.id] = token
            pending_prompt = None
        return Authorization(digest, tuple(accepted))

    def assert_authorized(
        self, plan: TaskPlan, step: TaskStep, authorization: Authorization
    ) -> None:
        if authorization.plan_digest != plan.digest():
            raise AuthorizationError("authorization does not match this plan")
        risk = self.risk_classify(step)
        if risk in {RiskLevel.SAFE_NAVIGATION, RiskLevel.SAFE_READ}:
            return
        if not any(token.step_id == step.id and
                   self._valid_token(token, authorization.plan_digest)
                   for token in authorization.tokens):
            raise AuthorizationError(
                f"{risk.value} step {step.id!r} has no valid confirmation token")

    def _mint(self, request: ConfirmationRequest) -> ConfirmationToken:
        nonce = secrets.token_hex(16)
        signature = self._sign(
            request.plan_digest, request.step_id, request.risk, nonce)
        return ConfirmationToken(
            request.plan_digest, request.step_id, request.risk, nonce, signature)

    def _valid_token(self, token: ConfirmationToken, digest: str) -> bool:
        if not isinstance(token, ConfirmationToken) or token.plan_digest != digest:
            return False
        expected = self._sign(
            token.plan_digest, token.step_id, token.risk, token.nonce)
        return hmac.compare_digest(token.signature, expected)

    def _sign(self, digest: str, step_id: str, risk: RiskLevel, nonce: str) -> str:
        payload = "\0".join((digest, step_id, risk.value, nonce)).encode("utf-8")
        return hmac.new(self.__secret, payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _default_prompt(step: TaskStep, risk: RiskLevel) -> str:
        return f"Confirm {risk.value} step {step.id}: {step.type}"


_DEFAULT_POLICY = PolicyEngine()


def validate(plan: TaskPlan) -> TaskPlan:
    return _DEFAULT_POLICY.validate(plan)


def risk_classify(step: TaskStep) -> RiskLevel:
    return _DEFAULT_POLICY.risk_classify(step)


def authorize(
    plan: TaskPlan, *, confirmer: Confirmer | None = None,
    tokens: Iterable[ConfirmationToken] = (),
) -> Authorization:
    return _DEFAULT_POLICY.authorize(plan, confirmer=confirmer, tokens=tokens)
