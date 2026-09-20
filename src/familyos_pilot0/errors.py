"""Domain-specific errors for Pilot 0 M2/M3.

Explicit, typed failures rather than raw storage/provider exceptions leaking
out of the vertical slice -- consistent with preferring explicit failure
over silent corruption.
"""

from __future__ import annotations


class Pilot0Error(Exception):
    """Base class for all Pilot 0 domain errors."""


class DuplicateTimelineEntryError(Pilot0Error):
    """A timeline entry already exists for this correlation_id.

    Raised instead of allowing a second confirm/edit-then-confirm decision
    for the same correlation_id to silently overwrite or duplicate a
    timeline entry.
    """


class UnknownConfirmationTokenError(Pilot0Error):
    """No confirmation token exists with the given token id."""


class ReplayedConfirmationTokenError(Pilot0Error):
    """The confirmation token has already been redeemed once.

    Confirmation tokens are single-use. A second redemption attempt for the
    same token id is a replay and MUST be rejected, not silently accepted.
    """


class ExpiredConfirmationTokenError(Pilot0Error):
    """The confirmation token's validity window has passed."""


class ConfirmationScopeMismatchError(Pilot0Error):
    """The pieces of a confirmation decision do not actually belong together.

    Raised when either:

    - the token being redeemed was issued for a different correlation_id,
      family_id, or member_id than the decision/identity it is being used
      for, or
    - the ``ConfirmationDecision.correlation_id`` does not match the
      ``TimelineEventProposal.correlation_id`` it is supposedly deciding on.

    A token whose scope does not match is NOT consumed by a mismatched
    attempt (validate-then-consume) -- only a scope-matched, non-expired,
    not-yet-redeemed token is ever marked redeemed. This keeps a
    scope-mismatched attempt from silently burning a token that its
    legitimate holder could otherwise still use correctly.
    """


class ModelGatewayError(Pilot0Error):
    """Base class for all real-provider Model Gateway failures (M3).

    Error messages on all subclasses are metadata-only (exception type,
    field names, status categories) and MUST NOT embed the actual prompt or
    model output content -- the same "never log content" boundary applies
    to error messages, not only to logging calls.
    """


class ModelGatewayTimeoutError(ModelGatewayError):
    """The provider call did not complete within the configured timeout."""


class ModelGatewayRefusalError(ModelGatewayError):
    """The model explicitly refused to produce a structured extraction."""


class ModelGatewayResponseParseError(ModelGatewayError):
    """The provider's response could not be parsed into a
    ``GatewayExtractionResult`` (missing/malformed structured output)."""


class ModelGatewayProviderError(ModelGatewayError):
    """A provider/transport-level failure not covered by a more specific
    error above (connection failure, rate limit, server error, or any other
    provider API error), surfaced after the SDK's own bounded retry
    behavior for retryable failure classes has been exhausted."""

class PrivacyBoundaryError(Pilot0Error):
    """Base error for Pilot 0 privacy-boundary violations."""


class ConsentRequiredError(PrivacyBoundaryError):
    """Raised when active, purpose-bound adult consent is unavailable."""


class MinorDataRejectedError(PrivacyBoundaryError):
    """Raised when the first-slice input is known to contain minor data."""


class PrivacyPayloadError(PrivacyBoundaryError):
    """Raised when a bounded privacy payload cannot be constructed."""

class ProposalError(Pilot0Error):
    """Base error for non-authoritative event proposal handling."""


class ProposalValidationError(ProposalError):
    """Raised when a proposal or bounded provenance record is invalid."""


class ProposalDecisionError(ProposalError):
    """Raised when a human proposal decision is invalid."""


class ProposalTerminalStateError(ProposalDecisionError):
    """Raised when a terminal proposal decision is replayed or contradicted."""

class ControlledExecutionError(Exception):
    """Base error for controlled-execution readiness failures."""


class ControlledExecutionValidationError(ControlledExecutionError):
    """Raised when controlled-execution input is structurally invalid."""

class FirstRealDataSliceReadinessError(Exception):
    """Base error for M8 first-real-data-slice readiness failures."""


class FirstRealDataSliceValidationError(FirstRealDataSliceReadinessError):
    """Raised when an M8 readiness input is structurally invalid."""

class ExecutionAuthorizationReadinessError(Exception):
    """Base error for M9 execution-authorization readiness failures."""


class ExecutionAuthorizationValidationError(ExecutionAuthorizationReadinessError):
    """Raised when an M9 authorization-readiness input is invalid."""

class ControlledExecutionProviderError(ControlledExecutionError):
    """Reserved for a separately authorized M10 provider execution."""
