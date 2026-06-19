# Milestone 1 hardware-proof findings

Working report for milestone M1 of the plan `i-am-thinking-of-eager-dolphin.md`
(work packages WP-PROOF-AIRPLAY and WP-PROOF-ROKU). These findings are required
inputs to the M3 backends.

The report is based only on the captured proof output in `/tmp/proof_airplay_out.txt`
and `/tmp/proof_roku_ip_out.txt`. No results are inferred beyond that evidence.

## Test environment

- Runner: a Mac on subnet 192.168.2.x. The AirPlay proof reported the runner
  interface as 192.168.2.75 when it served the sample file.
- Target device: "65in Sharp Roku TV" at 192.168.2.61, identifier
  07:75:9D:2B:21:26. It advertises both AirPlay 2 and Roku ECP.
- Device facts from `/query/device-info`: model 4T-C65DL7UR (Sharp Roku TV),
  software 15.2.4, `grandcentral-version` 26.24.14, `developer-enabled=false`,
  `supports-airplay=true`, `has-play-on-roku=false`, `ecp-setting-mode=limited`.

## AirPlay result

- Scan found the device by identifier and resolved address 192.168.2.61.
- The AirPlay service is on port 7000 with `pairing=Mandatory` and
  `has_credentials=False`. The proof chose AirPlay as the streaming protocol and
  flagged pairing-required as True.
- The runner served the sample file at
  `http://192.168.2.75:56811/airplay2tv_sample.mp4` and called
  `atv.stream.play_url(media_url)`.
- The call raised `pyatv.exceptions.AuthenticationError: not authenticated`,
  surfaced from the RTSP SETUP exchange inside pyatv
  (`pyatv/support/http.py` `send_and_receive`).

Conclusion: AirPlay streaming requires the pyatv pairing PIN handshake first.
This is a required input confirming the inline-pairing design for the M3
AirPlay backend.

## Roku ECP result

- ECP was reachable on port 8060. `GET /query/device-info` returned the full
  device-info XML (captured in the evidence file).
- `GET /query/apps` returned HTTP 403 Forbidden.
- SSDP discovery (`ST roku:ecp`) found nothing; the proof started from the
  supplied IP rather than a discovered location.

Conclusion: ECP responds but some endpoints are gated (403). The cause of the
403s is UNRESOLVED; `ecp-setting-mode=limited` is consistent with (but not proof
of) the "Control by mobile apps" setting being off. SSDP discovery being silent
is a separate DISCOVERY issue, independent from ECP control reachability. Roku
Media Player launch and the launch param casing are unconfirmed. See the
Direct-IP ECP re-probe (2026-06-18) section below for the corrected,
three-status framing that supersedes this paragraph.

## rokuecp API

- The `rokuecp` package is confirmed available; the proof imported and used
  `rokuecp.Roku` and its `launch` method.
- The exact launch params and casing (for example `contentId`/`mediaType` versus
  `contentID`/`MediaType`) remain to be confirmed on a live launch, because the
  403 blocked the proof before any launch was exercised.

## Proof-script bugs found

These are being fixed separately and are not part of this report's scope:

- `proof_airplay.py`: `await atv.close()` fails with
  `TypeError: object set can't be used in 'await' expression`. `atv.close()` is
  synchronous and must not be awaited.
- `proof_roku.py`: the HTTP 403 from `/query/apps` is unhandled and crashes the
  proof with `urllib.error.HTTPError: HTTP Error 403: Forbidden`.

## Required user actions before M3 backend playback can be verified

1. Enter the AirPlay pairing PIN shown on the TV. Run the AirPlay pair flow with
   the user present so the PIN handshake completes and credentials are stored.
2. Enable "Control by mobile apps" on the Roku TV, then re-run the Roku proof to
   confirm Media Player URL playback and capture the exact launch param casing.

## Implications for M3

- AirPlay backend: can be built now against the confirmed pyatv API
  (scan, connect, `play_url`, synchronous close) along the pairing-required
  path. The Mandatory pairing requirement and the `AuthenticationError` on an
  unpaired `play_url` are the confirmed preconditions.
- Roku backend: the launch path stays unverified until "Control by mobile apps"
  is enabled. Build can proceed against the confirmed `rokuecp.Roku.launch`
  surface, but the launch param casing and live playback confirmation are
  deferred to the re-run.

## Direct-IP ECP re-probe (2026-06-18)

This section corrects and extends the earlier Roku interpretation with a direct
re-probe captured this session. It hits the TV IP over the LAN with no SSDP
discovery step. Earlier text in this report attributed the 403s to the "Control
by mobile apps" setting being off; that cause is now treated as unresolved (see
the corrected interpretation below).

### Probe environment

- Source: 192.168.2.75 (the Mac on the LAN).
- Target: 192.168.2.61:8060 (the Sharp Roku TV ECP port), addressed directly by
  IP, no SSDP.
- Timestamp: 2026-06-18T02:16Z.

### Command shapes

Raw curl to the device IP, one request per endpoint:

```
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.2.61:8060/query/device-info
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.2.61:8060/query/active-app
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.2.61:8060/query/apps
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.2.61:8060/query/media-player
curl -s -X POST -o /dev/null -w '%{http_code}\n' http://192.168.2.61:8060/keypress/Home
```

### Endpoint status table

| Endpoint | Method | Status | Class |
| --- | --- | --- | --- |
| `/query/device-info` | GET | 200 | allowed |
| `/query/active-app` | GET | 200 | allowed (active app: Home, idle) |
| `/query/apps` | GET | 403 | gated |
| `/query/media-player` | GET | 403 | gated |
| `/keypress/Home` | POST | 403 | gated |

`launch` (the endpoint needed for casting) is in the same gated class as the
403 endpoints and was NOT exercised here, so it remains UNVERIFIED.

### device-info fields

- `friendly-device-name`: "65in Sharp Roku TV"
- `ecp-setting-mode`: "limited"
- `developer-enabled`: false

### SSDP discovery re-check

- SSDP `roku:ecp` discovery from the same machine returned 0 valid responses
  (SILENT).

### Corrected interpretation

Three statuses are tracked SEPARATELY. Do not collapse them into one cause.

- AirPlay (separate from Roku): unchanged from the AirPlay result above.
  Pairing is Mandatory and an unpaired `play_url` raises `AuthenticationError`.
- Roku direct ECP control: REACHABLE over the LAN by direct IP. `device-info`
  and `active-app` are allowed (200). `apps`, `media-player`, and `keypress` are
  gated (403). `launch` is in the gated class and is UNVERIFIED.
- Roku SSDP discovery: SILENT (0 valid responses). This is a DISCOVERY issue and
  is INDEPENDENT from ECP control reachability. A known IP can still be used via
  the direct-IP / `--device` path even when SSDP finds nothing.

Cause of the 403s is UNRESOLVED. `ecp-setting-mode=limited` is evidence of a
limited ECP mode and is consistent with (but not proof of) the "Control by
mobile apps" setting being off. The user's working Roku mobile app shows a
control path exists, so this report does NOT claim mobile-app control is off.
