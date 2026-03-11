"""MailSlurper data extractor for dev/test email polling."""

import logging
from typing import Any

import httpx

from . import ExtractionResult, register_extractor

logger = logging.getLogger(__name__)


class MailSlurperExtractor:
    """Extract emails from MailSlurper API.

    MailSlurper is a lightweight SMTP server for development.
    API docs: https://github.com/mailslurper/mailslurper

    Config:
        api_url: MailSlurper API URL (e.g., "http://localhost:8085")

    State:
        last_seen_id: ID of the last processed email.
    """

    async def extract(
        self, config: dict[str, Any], state: dict[str, Any] | None
    ) -> ExtractionResult:
        """Fetch new emails from MailSlurper since last checkpoint."""
        api_url = config.get("api_url", "http://localhost:8085")
        last_seen_id = (state or {}).get("last_seen_id")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{api_url}/mail")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.error("MailSlurper fetch failed: %s", e)
            return ExtractionResult(
                has_new_data=False,
                updated_state=state or {},
            )

        # MailSlurper returns {"mailItems": [...], "totalPages": N, ...}
        mail_items = data.get("mailItems", [])
        if not mail_items:
            return ExtractionResult(
                has_new_data=False,
                updated_state=state or {},
            )

        # Filter to only new emails
        new_emails = []
        newest_id = last_seen_id
        for item in mail_items:
            item_id = item.get("id", "")
            if last_seen_id and item_id <= last_seen_id:
                continue
            new_emails.append(item)
            if not newest_id or item_id > newest_id:
                newest_id = item_id

        if not new_emails:
            return ExtractionResult(
                has_new_data=False,
                updated_state={"last_seen_id": newest_id},
            )

        # Convert to normalized events
        events = []
        for email in new_emails:
            events.append(
                {
                    "type": "email",
                    "subject": email.get("subject", ""),
                    "from": email.get("fromAddress", ""),
                    "to": list(email.get("toAddresses", [])),
                    "body": email.get("body", ""),
                    "date": email.get("dateSent", ""),
                    "id": email.get("id", ""),
                }
            )

        # Build channel origin for reply routing
        first_email = new_emails[0]
        channel_origin = {
            "type": "email",
            "reply_to": first_email.get("fromAddress", ""),
            "subject": f"Re: {first_email.get('subject', '')}",
            "presentation": "summary",
        }

        return ExtractionResult(
            has_new_data=True,
            events=events,
            updated_state={"last_seen_id": newest_id},
            channel_origin=channel_origin,
        )


register_extractor("mailslurper", MailSlurperExtractor)
