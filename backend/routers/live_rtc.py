"""/api/live/rtc/* — WebRTC signalling for the in-pipeline overlay bridge.

Two endpoints:
  POST /offer { sdp, type } -> { pc_id, sdp, type }
  POST /close { pc_id }     -> 204

The actual frame-by-frame work lives in :mod:`backend.routers.live_rtc_track`.
This router only sets up + tears down the ``RTCPeerConnection`` and stores
it on ``app.state.live.rtc_peers`` so the close handler — and the recorder
branch — can find it later.
"""

from __future__ import annotations

import uuid

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel


router = APIRouter(prefix="/api/live/rtc", tags=["live_rtc"])

# One relay per process so multiple peer connections — and the recorder
# branch — fan out cleanly without double-decoding the source track.
_relay = MediaRelay()


class OfferRequest(BaseModel):
    sdp: str
    type: str


class OfferResponse(BaseModel):
    pc_id: str
    sdp: str
    type: str


@router.post("/offer", response_model=OfferResponse)
async def offer(req: OfferRequest, request: Request) -> OfferResponse:
    live = request.app.state.live
    pc = RTCPeerConnection()
    pc_id = uuid.uuid4().hex
    live.rtc_peers[pc_id] = pc

    @pc.on("connectionstatechange")
    async def _on_state_change() -> None:
        if pc.connectionState in ("failed", "closed"):
            await _cleanup(live, pc_id)

    @pc.on("track")
    def _on_track(track):
        if track.kind != "video":
            return
        # Lazy import to avoid the cost when WebRTC isn't used.
        from backend.routers.live_rtc_track import DetectionTrack
        baked = DetectionTrack(_relay.subscribe(track), live)
        pc.addTrack(baked)
        # Recorder branch is wired by /api/live/recording/start when
        # the user actually clicks Record. Track is held on live for
        # that route to subscribe to.
        live.rtc_source_track = track

    try:
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=req.sdp, type=req.type)
        )
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
    except Exception as exc:
        # Malformed / empty SDP — clean up the half-built peer so we
        # don't leak it on app.state.live.
        await _cleanup(live, pc_id)
        raise HTTPException(400, f"invalid SDP: {exc}") from exc

    return OfferResponse(
        pc_id=pc_id,
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type,
    )


class CloseRequest(BaseModel):
    pc_id: str


@router.post("/close", status_code=204)
async def close(req: CloseRequest, request: Request) -> Response:
    live = request.app.state.live
    if req.pc_id not in live.rtc_peers:
        raise HTTPException(404, "pc_id not found")
    await _cleanup(live, req.pc_id)
    return Response(status_code=204)


async def _cleanup(live, pc_id: str) -> None:
    pc = live.rtc_peers.pop(pc_id, None)
    if pc is not None:
        try:
            await pc.close()
        except Exception:
            pass
    # Drop the source track ref so a subsequent /offer picks up a new one.
    live.rtc_source_track = None
