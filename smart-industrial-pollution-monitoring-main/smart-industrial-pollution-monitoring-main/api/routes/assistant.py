"""
Natural-language assistant backed by IBM Granite.
POST /assistant/query
"""
from fastapi import APIRouter
from pydantic import BaseModel
from ai.granite_client import granite_client
from orchestration.orchestrator import orchestrator

router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    unit_id: str = None


@router.post("/query")
async def nl_query(request: QueryRequest):
    """Answer a natural-language pollution query using system data + Granite."""

    # Build compact context from live orchestrator state
    context = _build_context(request.unit_id)

    answer = await granite_client.answer_nl_query(request.question, context)

    return {
        "question": request.question,
        "answer": answer,
        "context_units": list(context.get("units", {}).keys()),
        "granite_available": granite_client.is_available(),
        "note": "Answers are based solely on current system data. Not a legal finding.",
    }


def _build_context(unit_id=None):
    """Build a compact context dict for Granite."""
    from database.db_models import AsyncSessionLocal
    units = {}
    keys = [unit_id] if unit_id else list(orchestrator._unit_evidence.keys())

    for uid in keys[:6]:   # cap context size
        ev = orchestrator.get_unit_evidence(uid)
        if not ev:
            continue
        risk = ev.get("risk")
        preds = ev.get("predictions", [])
        breaches = ev.get("breaches", [])
        units[uid] = {
            "risk_score": risk.risk_score if risk else None,
            "risk_level": risk.risk_level.value if risk else None,
            "dominant_pollutant": risk.dominant_pollutant.value if risk and risk.dominant_pollutant else None,
            "threshold_breaches": len(breaches),
            "breach_details": [
                {"pollutant": b.pollutant.value, "value": b.value, "excess_pct": b.excess_pct}
                for b in breaches[:3]
            ],
            "breach_predicted": sum(1 for p in preds if p.breach_predicted),
            "prediction_trends": [
                {"pollutant": p.pollutant.value, "trend": p.trend.value, "confidence": p.confidence}
                for p in preds[:5]
            ],
        }

    incidents = [
        {
            "id": str(i.id),
            "title": i.title,
            "zone": i.zone,
            "risk_level": i.risk_level.value,
            "status": i.status.value,
        }
        for i in orchestrator.get_active_incidents()[:5]
    ]

    return {
        "timestamp": __import__("utils.helpers", fromlist=["utcnow"]).utcnow().isoformat(),
        "active_incidents": len(incidents),
        "incidents": incidents,
        "units": units,
    }
