"""The webhook types a stream source can be, served to the UI so it carries no catalog.

Each type names the credentials its verifier needs and the plain settings that
go with them. A required credential is the one the verifier cannot run without:
creating the source without it is refused, never accepted unsigned. An optional
one left out is issued by the platform, so no source is unsigned either way.
"""

from typing import Literal

from pydantic import BaseModel, Field

from ..webhook_verification import SIGNING_SECRET_KEYS
from .channel_events import CHANNEL_EVENTS

SourceVerification = Literal["signature", "secret_token", "api_lookup"]


class SourceField(BaseModel):
    key: str
    label: str
    placeholder: str = ""
    required: bool = True


class StreamSourceType(BaseModel):
    webhook_type: str
    name: str
    description: str
    icon: str
    verification: SourceVerification = Field(
        description=(
            "signature: the body is signed with the secret; secret_token: the sender "
            "repeats a token; api_lookup: the notified object is read back from the API."
        )
    )
    credentials: list[SourceField] = Field(
        description="Secret fields: write-only, held by reference, never returned."
    )
    config: list[SourceField] = Field(default_factory=list, description="Plain settings.")
    events: list[str] = Field(default_factory=list, description="Event kinds it can deliver.")


def _secret(webhook_type: str, label: str, placeholder: str, *, required: bool = True):
    return SourceField(
        key=SIGNING_SECRET_KEYS[webhook_type],
        label=label,
        placeholder=placeholder,
        required=required,
    )


SENTRY_EVENTS = [
    "installation.created",
    "installation.deleted",
    "issue.created",
    "issue.resolved",
    "issue.assigned",
    "issue.archived",
    "issue.unresolved",
    "error.created",
    "event_alert.triggered",
    "metric_alert.critical",
    "metric_alert.warning",
    "metric_alert.resolved",
    "comment.created",
]

YOOKASSA_EVENTS = [
    "payment.succeeded",
    "payment.waiting_for_capture",
    "payment.canceled",
    "refund.succeeded",
    "payout.succeeded",
    "payout.canceled",
    "deal.closed",
    "payment_method.active",
]

STREAM_SOURCE_TYPES: list[StreamSourceType] = [
    StreamSourceType(
        webhook_type="generic",
        name="Webhook",
        description="Any sender that signs the body with HMAC; a secret is issued if you give none",
        icon="webhook",
        verification="signature",
        credentials=[
            _secret("generic", "Signing Secret", "Leave empty to have one issued", required=False)
        ],
        config=[
            SourceField(
                key="signature_header",
                label="Signature Header",
                placeholder="X-Webhook-Signature",
                required=False,
            ),
            SourceField(
                key="signature_algorithm",
                label="HMAC Digest",
                placeholder="sha256",
                required=False,
            ),
            SourceField(
                key="signature_prefix",
                label="Signature Prefix",
                placeholder="e.g. sha256=",
                required=False,
            ),
        ],
    ),
    StreamSourceType(
        webhook_type="github",
        name="GitHub",
        description="Repository and organization webhooks: pushes, pull requests, issues",
        icon="github",
        verification="signature",
        credentials=[
            _secret("github", "Webhook Secret", "Secret configured on the GitHub webhook")
        ],
        events=CHANNEL_EVENTS["github"],
    ),
    StreamSourceType(
        webhook_type="sentry",
        name="Sentry",
        description="Issue, error and alert webhooks of a Sentry internal integration",
        icon="webhook",
        verification="signature",
        credentials=[_secret("sentry", "Client Secret", "Client secret of the integration")],
        events=SENTRY_EVENTS,
    ),
    StreamSourceType(
        webhook_type="yookassa",
        name="YooKassa",
        description="Payment, refund and payout notifications, checked against the YooKassa API",
        icon="webhook",
        verification="api_lookup",
        credentials=[_secret("yookassa", "Secret Key", "live_… or test_… API key of the shop")],
        config=[SourceField(key="shop_id", label="Shop ID", placeholder="123456")],
        events=YOOKASSA_EVENTS,
    ),
    StreamSourceType(
        webhook_type="stripe",
        name="Stripe",
        description="Payments, invoices and subscriptions",
        icon="webhook",
        verification="signature",
        credentials=[_secret("stripe", "Signing Secret", "whsec_… from the Stripe endpoint")],
        events=CHANNEL_EVENTS["stripe"],
    ),
    StreamSourceType(
        webhook_type="telegram",
        name="Telegram",
        description="Updates of a Telegram bot; the webhook is registered with the bot for you",
        icon="telegram",
        verification="secret_token",
        credentials=[
            SourceField(key="bot_token", label="Bot Token", placeholder="Token from @BotFather")
        ],
        events=CHANNEL_EVENTS["telegram"],
    ),
    StreamSourceType(
        webhook_type="slack",
        name="Slack",
        description="Events API deliveries of a Slack app",
        icon="slack",
        verification="signature",
        credentials=[_secret("slack", "Signing Secret", "Your Slack app's signing secret")],
        events=CHANNEL_EVENTS["slack"],
    ),
    StreamSourceType(
        webhook_type="email",
        name="Email",
        description="Mail posted by an inbound-parse provider",
        icon="gmail",
        verification="signature",
        credentials=[
            _secret(
                "email",
                "Signing Secret",
                "Leave empty to have one issued",
                required=False,
            )
        ],
        events=CHANNEL_EVENTS["email"],
    ),
]


def get_stream_source_type(webhook_type: str) -> StreamSourceType | None:
    return next((t for t in STREAM_SOURCE_TYPES if t.webhook_type == webhook_type), None)
