from fastapi import APIRouter, HTTPException
from orchestration.orchestrator import orchestrator

router = APIRouter()


@router.get("/{unit_id}")
async def get_predictions(unit_id: str):
    evidence = orchestrator.get_unit_evidence(unit_id)
    if not evidence:
        raise HTTPException(404, f"No prediction data for unit '{unit_id}'")
    predictions = evidence.get("predictions", [])
    return {
        "unit_id": unit_id,
        "count": len(predictions),
        "source_type": "PREDICTED",
        "predictions": [
            {
                "id": str(p.id),
                "sensor_id": p.sensor_id,
                "pollutant": p.pollutant.value,
                "current_value": p.current_value,
                "predicted_value": p.predicted_value,
                "worst_case_value": p.worst_case_value,
                "unit": p.unit,
                "horizon_minutes": p.horizon_minutes,
                "trend": p.trend.value,
                "threshold_value": p.threshold_value,
                "breach_predicted": p.breach_predicted,
                "breach_eta_minutes": p.breach_eta_minutes,
                "confidence": p.confidence,
                "uncertainty_pct": p.uncertainty_pct,
                "model_used": p.model_used,
                "evidence": p.evidence,
                "created_at": p.created_at.isoformat(),
                "early_warning": (
                    {
                        "message": (
                            f"Current {p.pollutant.value}: {p.current_value} {p.unit}\n"
                            f"Threshold: {p.threshold_value}\n"
                            f"Trend: {p.trend.value}\n"
                            f"Predicted in {p.horizon_minutes} min: {p.predicted_value}\n\n"
                            f"⚠ EARLY WARNING: Potential threshold breach predicted."
                            + (f" ETA ~{p.breach_eta_minutes} min." if p.breach_eta_minutes else "")
                        )
                    }
                    if p.breach_predicted else None
                ),
            }
            for p in predictions
        ],
    }
