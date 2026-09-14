from fastapi import APIRouter, HTTPException
from orchestration.orchestrator import orchestrator

router = APIRouter()


@router.get("/{unit_id}")
async def get_risk(unit_id: str):
    evidence = orchestrator.get_unit_evidence(unit_id)
    if not evidence:
        raise HTTPException(404, f"No risk data found for unit '{unit_id}'")
    risk = evidence.get("risk")
    if risk is None:
        return {"unit_id": unit_id, "message": "No risk assessment yet — awaiting data"}
    return {
        "unit_id": unit_id,
        "risk_score": risk.risk_score,
        "risk_level": risk.risk_level.value,
        "dominant_pollutant": risk.dominant_pollutant.value if risk.dominant_pollutant else None,
        "threshold_breaches": risk.threshold_breaches,
        "anomaly_count": risk.anomaly_count,
        "sensor_reliability_avg": risk.sensor_reliability_avg,
        "prediction_risk_boost": risk.prediction_risk_boost,
        "confidence": risk.confidence,
        "contributing_factors": risk.contributing_factors,
        "assessed_at": risk.assessed_at.isoformat(),
        "source_type": risk.source_type.value,
        "classification": {
            "0-20": "LOW",
            "21-40": "MODERATE",
            "41-60": "ELEVATED",
            "61-80": "HIGH",
            "81-100": "CRITICAL",
        },
    }
