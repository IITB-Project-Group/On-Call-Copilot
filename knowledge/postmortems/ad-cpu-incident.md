---
id: pm-006
service: ad
symptom: "Ad service CPU saturated and page loads slowed substantially"
root_cause: "adHighCpu enabled"
fix: "Disabled adHighCpu flag after approval"
preconditions:
  - "Ad service CPU is above threshold for sustained time"
  - "Latency spikes are concentrated in ad rendering or ad fetches"
  - "Feature flag adHighCpu is enabled"
lesson: "High ad CPU is usually a direct consequence of the adHighCpu flag when resource saturation and ad request latency line up."
---

# Ad CPU incident

## Summary
The ad service was overloaded and page latency increased due to a high CPU injection. Once the flag was disabled, the ad tier recovered.

## Timeline
- CPU usage stayed high across the ad service.
- Request latency and timeout rates increased around ad fetches.
- The active flag review confirmed `adHighCpu`.
- Recovery followed the approved disable action.

## Root cause
The `adHighCpu` flag caused the service to saturate.

## Fix
Set `adHighCpu` to false and confirm CPU and latency recover to baseline.
