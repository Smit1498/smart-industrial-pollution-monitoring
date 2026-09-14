"""
/monitor endpoint — WebSocket for real-time push + POST /monitor to run a single cycle.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from agents.alert_agent import alert_agent
from orchestration.orchestrator import orchestrator

router = APIRouter()


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """WebSocket endpoint — pushes alerts in real-time to connected clients."""
    await websocket.accept()
    alert_agent.register_ws(websocket)
    try:
        while True:
            # Keep alive ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        alert_agent.unregister_ws(websocket)


@router.post("/monitor")
async def trigger_monitor_cycle():
    """Manually trigger one monitoring cycle (useful for testing)."""
    await orchestrator._cycle()
    status = orchestrator.get_status()
    return {
        "triggered": True,
        "status": {
            "active_incidents": status.active_incidents,
            "active_alerts": status.active_alerts,
            "online_sensors": status.online_sensors,
        },
    }
