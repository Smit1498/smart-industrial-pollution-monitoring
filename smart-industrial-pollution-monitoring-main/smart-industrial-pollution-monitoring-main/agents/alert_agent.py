"""
Alert & Escalation Agent.

Sends alerts via:
  - WebSocket (real-time dashboard push)
  - Email (SMTP, optional)
  - Webhook (Slack / Teams / custom, optional)
  - In-memory queue (always available)

Escalation rules:
  - CRITICAL: immediate, all channels
  - HIGH: immediate, configured channels
  - WARNING: queued, batched email
  - INFO: log only

Rate-limiting prevents alert storms (per unit per severity).
"""
from __future__ import annotations

import asyncio
import json
import smtplib
import ssl
from collections import defaultdict, deque
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional, Set

import httpx

from app.config import get_settings
from app.models import Alert, AlertSeverity, AlertStatus
from utils.helpers import get_logger, seconds_since, utcnow

logger = get_logger(__name__)
settings = get_settings()

_RATE_LIMIT_WINDOW_SECS = 300   # 5 min: max 1 alert per severity per unit
_WS_QUEUE_MAX = 500


class AlertAgent:
    """
    Handles alert routing, deduplication, rate-limiting, and escalation.
    """

    def __init__(self) -> None:
        # In-memory store
        self._alert_history: deque = deque(maxlen=1000)
        self._websocket_queue: deque = deque(maxlen=_WS_QUEUE_MAX)
        self._ws_connections: Set = set()

        # Rate-limit tracking: (unit_id, severity) → last sent time
        self._last_sent: Dict[tuple, datetime] = {}

        # Pending email queue (batched)
        self._email_queue: deque = deque(maxlen=200)

    # ── WebSocket management ──────────────────────────────────────────────────

    def register_ws(self, ws) -> None:
        self._ws_connections.add(ws)

    def unregister_ws(self, ws) -> None:
        self._ws_connections.discard(ws)

    # ── Public: dispatch ──────────────────────────────────────────────────────

    async def dispatch(self, alert: Alert) -> None:
        """Route an alert through all configured channels."""

        # Always add to history
        self._alert_history.appendleft(alert)

        # Rate-limit check (skip for CRITICAL)
        if alert.severity != AlertSeverity.CRITICAL:
            if self._is_rate_limited(alert):
                logger.debug(
                    "Alert rate-limited: %s / %s", alert.industrial_unit_id, alert.severity
                )
                return

        self._last_sent[(alert.industrial_unit_id, alert.severity.value)] = utcnow()

        # ── 1. WebSocket push (always) ─────────────────────────────────────
        self._websocket_queue.appendleft(alert)
        await self._push_ws(alert)

        # ── 2. Webhook (WARNING+) ──────────────────────────────────────────
        if (settings.ALERT_WEBHOOK_URL
                and alert.severity in (AlertSeverity.WARNING, AlertSeverity.HIGH, AlertSeverity.CRITICAL)):
            asyncio.create_task(self._send_webhook(alert))

        # ── 3. Email (HIGH / CRITICAL) ─────────────────────────────────────
        if (settings.ALERT_EMAIL_ENABLED
                and alert.severity in (AlertSeverity.HIGH, AlertSeverity.CRITICAL)
                and settings.alert_recipient_list):
            asyncio.create_task(self._send_email(alert))

    # ── WebSocket ─────────────────────────────────────────────────────────────

    async def _push_ws(self, alert: Alert) -> None:
        if not self._ws_connections:
            return
        payload = json.dumps({
            "type": "alert",
            "id": str(alert.id),
            "severity": alert.severity.value,
            "title": alert.title,
            "message": alert.message,
            "unit_id": alert.industrial_unit_id,
            "zone": alert.zone,
            "risk_score": alert.risk_score,
            "risk_level": alert.risk_level.value if alert.risk_level else None,
            "created_at": alert.created_at.isoformat(),
        })
        dead = set()
        for ws in list(self._ws_connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._ws_connections -= dead

    # ── Webhook ───────────────────────────────────────────────────────────────

    async def _send_webhook(self, alert: Alert) -> None:
        try:
            payload = {
                "text": (
                    f"*[{alert.severity.value}]* {alert.title}\n"
                    f"Zone: {alert.zone} | Risk: {alert.risk_score:.1f}\n"
                    f"{alert.message[:300]}"
                )
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(settings.ALERT_WEBHOOK_URL, json=payload)
                resp.raise_for_status()
                logger.info("Webhook alert sent for %s", alert.industrial_unit_id)
        except Exception as exc:
            logger.warning("Webhook send failed: %s", exc)

    # ── Email ─────────────────────────────────────────────────────────────────

    async def _send_email(self, alert: Alert) -> None:
        if not settings.ALERT_SMTP_HOST:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_send_email, alert)

    def _sync_send_email(self, alert: Alert) -> None:
        try:
            subject = f"[POLLUTION ALERT — {alert.severity.value}] {alert.title}"
            body = self._format_email_body(alert)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.ALERT_SMTP_USER
            msg["To"] = ", ".join(settings.alert_recipient_list)
            msg.attach(MIMEText(body, "plain"))

            context = ssl.create_default_context()
            with smtplib.SMTP(settings.ALERT_SMTP_HOST, settings.ALERT_SMTP_PORT) as srv:
                srv.ehlo()
                srv.starttls(context=context)
                srv.login(settings.ALERT_SMTP_USER, settings.ALERT_SMTP_PASSWORD)
                srv.sendmail(
                    settings.ALERT_SMTP_USER,
                    settings.alert_recipient_list,
                    msg.as_string(),
                )
            logger.info("Email alert sent to %d recipients", len(settings.alert_recipient_list))
        except Exception as exc:
            logger.warning("Email send failed: %s", exc)

    def _format_email_body(self, alert: Alert) -> str:
        lines = [
            f"INDUSTRIAL POLLUTION ALERT — Gujarat Golden Corridor",
            f"=" * 50,
            f"Severity  : {alert.severity.value}",
            f"Zone      : {alert.zone}",
            f"Unit ID   : {alert.industrial_unit_id}",
            f"Risk Score: {alert.risk_score:.1f} / 100 ({alert.risk_level.value if alert.risk_level else 'N/A'})",
            f"Generated : {alert.created_at.isoformat()}",
            f"",
            f"MESSAGE:",
            alert.message,
            f"",
            f"EVIDENCE:",
            *[f"  • {e}" for e in alert.evidence],
            f"",
            f"NOTE: This is a system-generated AI alert. Official regulatory action",
            f"requires independent verification by authorized personnel.",
        ]
        return "\n".join(lines)

    # ── Rate-limiting ─────────────────────────────────────────────────────────

    def _is_rate_limited(self, alert: Alert) -> bool:
        key = (alert.industrial_unit_id, alert.severity.value)
        last = self._last_sent.get(key)
        if last is None:
            return False
        return seconds_since(last) < _RATE_LIMIT_WINDOW_SECS

    # ── Query helpers ─────────────────────────────────────────────────────────

    def recent_alerts(self, limit: int = 50) -> List[Alert]:
        return list(self._alert_history)[:limit]

    def get_ws_queue(self, limit: int = 50) -> List[Alert]:
        return list(self._websocket_queue)[:limit]

    async def test_alert(self, unit_id: str, zone: str) -> Alert:
        """Send a test alert to verify the pipeline."""
        from app.models import RiskLevel
        from uuid import uuid4
        alert = Alert(
            id=uuid4(),
            industrial_unit_id=unit_id,
            zone=zone,
            severity=AlertSeverity.WARNING,
            title="[TEST] Alert pipeline test",
            message="This is a test alert generated by the system. No real pollution event.",
            risk_score=0.0,
            risk_level=RiskLevel.LOW,
            source_type="SIMULATED",
            evidence=["Test alert — no real data"],
        )
        await self.dispatch(alert)
        return alert


# Module-level singleton
alert_agent = AlertAgent()
