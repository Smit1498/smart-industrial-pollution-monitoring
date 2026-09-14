"""
IBM Granite / watsonx.ai Client.

Design principles:
  1. Critical alerts are NEVER blocked waiting for Granite.
  2. Granite is called only when risk >= ELEVATED (configurable).
  3. Context sent is compact and structured — never raw sensor dumps.
  4. If Granite fails the system continues deterministic monitoring.
  5. Responses are used for explanations / NL answers only —
     they NEVER override deterministic safety rules.

Authentication: IBM Cloud IAM (api key → bearer token, cached).
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.models import Incident, RiskAssessment, RootCauseAnalysis
from utils.helpers import get_logger, truncate_str

logger = get_logger(__name__)
settings = get_settings()

_IAM_URL = "https://iam.cloud.ibm.com/identity/token"
_INFERENCE_PATH = "/ml/v1/text/generation?version=2023-05-29"


class GraniteClient:
    """
    Thin async client for IBM watsonx.ai Granite text generation.
    """

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._available: bool = bool(settings.IBM_CLOUD_API_KEY)
        self._degraded: bool = False
        self._lock = asyncio.Lock()

    def is_available(self) -> bool:
        return self._available and not self._degraded and bool(settings.IBM_CLOUD_API_KEY)

    # ── IAM token management ──────────────────────────────────────────────────

    async def _get_token(self) -> Optional[str]:
        if not settings.IBM_CLOUD_API_KEY:
            return None
        async with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        _IAM_URL,
                        data={
                            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                            "apikey": settings.IBM_CLOUD_API_KEY,
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    self._token = data["access_token"]
                    self._token_expiry = time.time() + data.get("expires_in", 3600)
                    self._degraded = False
                    return self._token
            except Exception as exc:
                logger.warning("Granite IAM token refresh failed: %s", exc)
                self._degraded = True
                return None

    # ── Core generation ───────────────────────────────────────────────────────

    async def _generate(self, prompt: str, max_tokens: int = 600) -> Optional[str]:
        token = await self._get_token()
        if not token:
            return None

        payload = {
            "model_id": settings.IBM_GRANITE_MODEL,
            "input": prompt,
            "parameters": {
                "decoding_method": "greedy",
                "max_new_tokens": max_tokens,
                "min_new_tokens": 30,
                "stop_sequences": ["<|end|>"],
                "temperature": 0.1,
            },
            "project_id": settings.IBM_PROJECT_ID,
        }

        url = settings.IBM_WATSONX_URL.rstrip("/") + _INFERENCE_PATH
        try:
            async with httpx.AsyncClient(
                timeout=settings.GRANITE_TIMEOUT_SECONDS
            ) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["results"][0]["generated_text"]
                self._degraded = False
                return text.strip()
        except Exception as exc:
            logger.warning("Granite generation failed: %s", exc)
            self._degraded = True
            return None

    # ── Prompt builders ───────────────────────────────────────────────────────

    def _build_incident_prompt(
        self,
        risk: RiskAssessment,
        rca: RootCauseAnalysis,
        incident: Incident,
    ) -> str:
        factors = json.dumps(risk.contributing_factors[:5], indent=2, default=str)
        causes = json.dumps(rca.possible_causes[:3], indent=2, default=str)
        return f"""You are an industrial pollution analysis AI assistant.
Analyze the following pollution incident and provide a concise, factual explanation.
Do not fabricate data. Use only the evidence provided.

INCIDENT:
Title: {incident.title}
Zone: {incident.zone}
Risk Level: {risk.risk_level.value} (Score: {risk.risk_score:.1f}/100)
Dominant Pollutant: {risk.dominant_pollutant.value if risk.dominant_pollutant else 'Unknown'}
Threshold Breaches: {risk.threshold_breaches}
Anomalies: {risk.anomaly_count}
Confidence: {risk.confidence:.0%}

RISK FACTORS:
{factors}

ROOT CAUSE HYPOTHESES:
{causes}

OBSERVED EVIDENCE:
{chr(10).join('- ' + e for e in rca.observed_evidence[:5])}

CONTRADICTING EVIDENCE:
{chr(10).join('- ' + e for e in rca.contradicting_evidence[:3]) or 'None identified'}

Provide a structured explanation covering:
1. WHAT happened
2. WHY it was classified this risk level
3. WHAT evidence supports this
4. HOW confident we are and WHY
5. WHAT could happen next if no action is taken
6. WHAT immediate actions are recommended
7. WHAT additional data would improve confidence

Keep response under 400 words. Be factual and cautious — avoid claiming confirmed violations without official evidence.
<|end|>"""

    def _build_nl_query_prompt(
        self, question: str, context: Dict[str, Any]
    ) -> str:
        ctx_str = json.dumps(context, indent=2, default=str)
        # Truncate to stay within token budget
        ctx_str = truncate_str(ctx_str, settings.GRANITE_MAX_CONTEXT_TOKENS * 3)
        return f"""You are an industrial pollution monitoring assistant for the Gujarat Golden Corridor (India).
Answer the following question using ONLY the provided system data.
Do not fabricate values, sensor readings, or regulatory findings.
If the answer cannot be determined from the data, say so clearly.

SYSTEM DATA:
{ctx_str}

QUESTION: {question}

Provide a clear, concise answer based solely on the data above.
<|end|>"""

    def _build_prediction_explanation_prompt(
        self, context: Dict[str, Any]
    ) -> str:
        return f"""You are analyzing a pollution trend prediction.
Based solely on the data below, explain what is happening and what may occur next.
Do not fabricate readings or thresholds.

PREDICTION CONTEXT:
{json.dumps(context, indent=2, default=str)}

Explain:
1. Current situation
2. Predicted trend and confidence
3. Risk if the trend continues
4. Recommended monitoring actions
<|end|>"""

    # ── Public methods ────────────────────────────────────────────────────────

    async def explain_incident(
        self,
        risk: RiskAssessment,
        rca: RootCauseAnalysis,
        incident: Incident,
    ) -> Optional[str]:
        """Generate a natural-language explanation for an incident."""
        if not self.is_available():
            return None
        prompt = self._build_incident_prompt(risk, rca, incident)
        return await self._generate(prompt, max_tokens=600)

    async def answer_nl_query(
        self, question: str, context: Dict[str, Any]
    ) -> Optional[str]:
        """Answer a natural-language query about the system's current state."""
        if not self.is_available():
            return (
                "IBM Granite AI is not configured or unavailable. "
                "Please check IBM_CLOUD_API_KEY in your .env file."
            )
        prompt = self._build_nl_query_prompt(question, context)
        result = await self._generate(prompt, max_tokens=400)
        if result is None:
            return "AI assistant temporarily unavailable. Deterministic monitoring continues."
        return result

    async def explain_prediction(
        self, context: Dict[str, Any]
    ) -> Optional[str]:
        """Explain a pollution prediction trend."""
        if not self.is_available():
            return None
        prompt = self._build_prediction_explanation_prompt(context)
        return await self._generate(prompt, max_tokens=300)

    def status(self) -> Dict[str, Any]:
        return {
            "available": self.is_available(),
            "degraded": self._degraded,
            "model": settings.IBM_GRANITE_MODEL,
            "endpoint": settings.IBM_WATSONX_URL,
            "configured": bool(settings.IBM_CLOUD_API_KEY),
        }


# Module-level singleton
granite_client = GraniteClient()
