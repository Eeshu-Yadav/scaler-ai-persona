# Getting a phone number in front of the agent (Twilio → LiveKit SIP)

The voice agent is a LiveKit worker; inbound phone calls reach it through a SIP
trunk. One-time setup, ~20 minutes.

## 1. Twilio: buy a number + create an Elastic SIP Trunk

1. Twilio Console → Phone Numbers → Buy a Number (a US local number works; trial
   credit covers it).
2. Console → Elastic SIP Trunking → Trunks → **Create trunk** (name: `livekit`).
3. In the trunk's **Origination** settings, add an Origination URI pointing at
   your LiveKit SIP endpoint:
   `sip:<YOUR-LIVEKIT-SIP-URI>;transport=tcp` — you get this URI in step 2 below
   (LiveKit Cloud → Settings → Project → SIP, looks like `xxxxxxx.sip.livekit.cloud`).
4. Phone Numbers → your number → Voice Configuration → **Configure with: SIP Trunk**,
   select the `livekit` trunk. Save.

## 2. LiveKit: inbound trunk + dispatch rule

Install CLI: `curl -sSL https://get.livekit.io/cli | bash`, then
`lk cloud auth`.

Create `inbound-trunk.json`:
```json
{
  "trunk": {
    "name": "twilio-inbound",
    "numbers": ["+1XXXXXXXXXX"]
  }
}
```

Create `dispatch-rule.json` (routes every inbound call to a fresh room and
dispatches our named agent into it):
```json
{
  "dispatch_rule": {
    "rule": { "dispatchRuleIndividual": { "roomPrefix": "call-" } },
    "roomConfig": { "agents": [ { "agentName": "eeshu-persona" } ] }
  }
}
```

Apply:
```bash
lk sip inbound create inbound-trunk.json
lk sip dispatch create dispatch-rule.json
```

## 3. Deploy the worker

Option A — **LiveKit Cloud agent hosting** (recommended; stays live 24/7, scales to zero is disabled for agents):
```bash
cd <repo-root>
lk agent create        # first time; uses voice-agent/Dockerfile via livekit.toml
lk agent deploy
```
Create `livekit.toml` at repo root:
```toml
[agent]
id = "eeshu-persona"

[build]
dockerfile = "voice-agent/Dockerfile"
```

Option B — any Docker host (Railway/Render/VPS):
```bash
docker build -f voice-agent/Dockerfile -t persona-voice .
docker run --env-file voice-agent/.env persona-voice
```
The worker dials out to LiveKit Cloud over WebSocket — no inbound ports needed.

## 4. Test

- `python agent.py console` — local mic/speaker sanity check (no telephony).
- Call the Twilio number — you should hear the greeting in under ~2s after pickup.

## Latency notes

- Twilio trial plays a "press any key to execute" preamble on inbound calls —
  **upgrade the account (~$20)** to remove it, or evaluators will hear it.
- Choose the LiveKit Cloud region closest to your callers (India → `ap-south`
  if offered, else Singapore) when creating the project.
