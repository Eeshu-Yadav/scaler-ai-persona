import { useRef, useState } from "react"
import { Room, RoomEvent, Track } from "livekit-client"
import { Loader2, Phone, PhoneOff } from "lucide-react"

import { Button } from "@/components/ui/button"

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000"

type Status = "idle" | "connecting" | "live" | "error"

export default function VoiceCall() {
  const [status, setStatus] = useState<Status>("idle")
  const [error, setError] = useState<string | null>(null)
  const roomRef = useRef<Room | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  async function start() {
    setStatus("connecting")
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/voice/token`, { method: "POST" })
      if (!res.ok) throw new Error(`token ${res.status}`)
      const { url, token } = await res.json()

      const room = new Room({ adaptiveStream: true })
      roomRef.current = room

      // Play the agent's audio as soon as it arrives.
      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio && audioRef.current) {
          track.attach(audioRef.current)
        }
      })
      room.on(RoomEvent.Disconnected, () => setStatus("idle"))

      await room.connect(url, token)
      await room.localParticipant.setMicrophoneEnabled(true)
      setStatus("live")
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus("error")
    }
  }

  async function stop() {
    await roomRef.current?.disconnect()
    roomRef.current = null
    setStatus("idle")
  }

  return (
    <>
      <audio ref={audioRef} autoPlay />
      {status === "idle" || status === "error" ? (
        <Button
          variant="outline"
          size="sm"
          onClick={start}
          className="gap-1.5 rounded-full"
        >
          <Phone className="h-3.5 w-3.5" />
          Talk to the agent
        </Button>
      ) : status === "connecting" ? (
        <Button variant="outline" size="sm" disabled className="gap-1.5 rounded-full">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Connecting…
        </Button>
      ) : (
        <Button
          variant="destructive"
          size="sm"
          onClick={stop}
          className="gap-1.5 rounded-full"
        >
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-70" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-white" />
          </span>
          <PhoneOff className="h-3.5 w-3.5" />
          End call
        </Button>
      )}
      {error && (
        <span className="text-destructive ml-2 text-[11px]">voice: {error}</span>
      )}
    </>
  )
}
