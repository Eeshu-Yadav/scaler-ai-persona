import json

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from shared import calcom
from .chat_engine import stream_chat


class BurstThrottle(AnonRateThrottle):
    rate = "120/hour"


@require_GET
def health(request):
    from shared.rag import get_store
    try:
        n = len(get_store().chunks)
        return JsonResponse({"status": "ok", "corpus_chunks": n})
    except Exception as exc:
        return JsonResponse({"status": "degraded", "error": str(exc)[:200]}, status=503)


@csrf_exempt
@require_POST
def chat(request):
    """SSE streaming chat. Body: {"messages": [{role, content}, ...]}"""
    try:
        body = json.loads(request.body)
        history = body.get("messages", [])
        assert isinstance(history, list) and history
    except Exception:
        return JsonResponse({"error": "messages array required"}, status=400)

    def event_stream():
        for event in stream_chat(history):
            yield f"data: {json.dumps(event)}\n\n"

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@api_view(["GET"])
@throttle_classes([BurstThrottle])
def slots(request):
    tz = request.GET.get("timezone", calcom.DEFAULT_TZ)
    try:
        days = min(int(request.GET.get("days", 7)), 14)
    except ValueError:
        days = 7
    return Response({"slots": calcom.get_available_slots(days, tz), "timezone": tz})


@api_view(["POST"])
@throttle_classes([BurstThrottle])
def book(request):
    data = request.data
    missing = [k for k in ("start_iso", "name", "email") if not data.get(k)]
    if missing:
        return Response({"error": f"missing fields: {missing}"}, status=400)
    result = calcom.create_booking(
        start_iso=data["start_iso"],
        attendee_name=data["name"],
        attendee_email=data["email"],
        timezone_name=data.get("timezone", calcom.DEFAULT_TZ),
        notes=data.get("notes", ""),
    )
    return Response(result, status=200 if result.get("success") else 502)
