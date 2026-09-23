"""Deterministic fake notification adapter. Captures sent emails/webhooks/messages for assertions
(docs/08_TESTING_STRATEGY.md §2) instead of hitting SMTP/webhooks for real.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.ids import new_id


@dataclass
class SentEmail:
    to: list[str]
    subject: str
    html: str
    text: str
    idempotency_key: str


@dataclass
class SentWebhook:
    url: str
    payload: dict[str, object]
    secret: str
    idempotency_key: str


@dataclass
class SentMessage:
    channel: Literal["sms", "whatsapp"]
    to_e164: str
    template_id: str
    variables: dict[str, object]


class FakeNotifier:
    def __init__(self) -> None:
        self.emails: list[SentEmail] = []
        self.webhooks: list[SentWebhook] = []
        self.messages: list[SentMessage] = []
        self._seen_idempotency_keys: set[str] = set()

    async def send_email(
        self, to: list[str], subject: str, html: str, text: str, idempotency_key: str
    ) -> str:
        if idempotency_key not in self._seen_idempotency_keys:
            self._seen_idempotency_keys.add(idempotency_key)
            self.emails.append(
                SentEmail(
                    to=to, subject=subject, html=html, text=text, idempotency_key=idempotency_key
                )
            )
        return new_id("req")

    async def send_webhook(
        self, url: str, payload: dict[str, object], secret: str, idempotency_key: str
    ) -> int:
        if idempotency_key not in self._seen_idempotency_keys:
            self._seen_idempotency_keys.add(idempotency_key)
            self.webhooks.append(
                SentWebhook(
                    url=url, payload=payload, secret=secret, idempotency_key=idempotency_key
                )
            )
        return 200

    async def send_message(
        self,
        channel: Literal["sms", "whatsapp"],
        to_e164: str,
        template_id: str,
        variables: dict[str, object],
    ) -> str:
        self.messages.append(
            SentMessage(
                channel=channel, to_e164=to_e164, template_id=template_id, variables=variables
            )
        )
        return new_id("req")
