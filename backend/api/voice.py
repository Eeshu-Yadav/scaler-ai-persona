"""Browser voice access — mints a LiveKit join token and dispatches the persona
agent into a fresh room, so anyone can voice-call the agent from the chat site
over WebRTC (no phone, no international dialing, works from anywhere).

Needs LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET in the backend env.
"""

import os
import uuid

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

AGENT_NAME = "eeshu-persona"


@csrf_exempt
@require_POST
def voice_token(request):
    url = os.environ.get("LIVEKIT_URL")
    key = os.environ.get("LIVEKIT_API_KEY")
    secret = os.environ.get("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        return JsonResponse({"error": "voice not configured"}, status=503)

    from livekit import api

    room = f"web-{uuid.uuid4().hex[:10]}"

    # Mint a short-lived join token for the browser participant.
    token = (
        api.AccessToken(key, secret)
        .with_identity(f"caller-{uuid.uuid4().hex[:6]}")
        .with_name("Web caller")
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )

    # Dispatch the persona agent into that room (it scales up on demand).
    async def _dispatch():
        lk = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
        try:
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room)
            )
        finally:
            await lk.aclose()

    import asyncio

    try:
        asyncio.run(_dispatch())
    except Exception as exc:  # token still usable; dispatch rule may cover it
        return JsonResponse(
            {"url": url, "token": token, "room": room, "dispatch_warning": str(exc)[:160]}
        )

    return JsonResponse({"url": url, "token": token, "room": room})
