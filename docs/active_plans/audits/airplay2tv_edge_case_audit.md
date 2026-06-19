# Airplay2tv edge case audit

Date: 2026-06-17
Auditor: Claude (read-only; no code changed)
Scope: eight seams identified in the audit prompt; 919 tests green at audit time.

## Summary table

Severity scale: HIGH = data loss or silent wrong behavior; MEDIUM = user-visible
wrong result or hang; LOW = degraded experience, misleading message, or
hard-to-reproduce race.

| # | Sev | Seam | Gap | Suggested test or fix |
| --- | --- | --- | --- | --- |
| 1 | HIGH | app.run_stream - Ctrl+C during prepare | cancel_event is never set; KeyboardInterrupt during prepare_media leaves ffmpeg running and partial output unclean | Set cancel_event in the KeyboardInterrupt handler; test: monkeypatch _run_ffmpeg to block then raise KeyboardInterrupt; assert temp dir removed |
| 2 | HIGH | credentials.save_record - concurrent save | Two callers both load(), merge, and write back; the second silently discards the first writer's record (load-merge-save race) | Add fcntl.flock around the load+write window; test: two threads calling save_record concurrently; assert both records survive |
| 3 | HIGH | airplay.pair - wrong PIN with failing close | PairingRequiredError raised inside try; if pairing.close() also raises, the original error is swallowed by the close exception | Extract the has_paired check before the finally; test: mock close() to raise; assert PairingRequiredError surfaces not the close error |
| 4 | HIGH | media.inspect - missing audio or video stream | _first_stream_codec returns empty string for a missing stream; decide treats empty string as supported; video-only file served without question | Add unit test: MediaInfo with empty audio_codec against a profile listing audio codecs; verify decide returns passthrough and document the design choice or tighten it |
| 5 | MEDIUM | app.run_stream - Ctrl+C during ensure_paired | Temp dir is created before the try; if KeyboardInterrupt fires during ensure_paired the finally removes the dir correctly but no test covers this specific pre-server window | Test: ensure_paired raises KeyboardInterrupt; assert temp dir removed and no server shutdown attempted |
| 6 | MEDIUM | aggregate.discover_all - shared-timeout starvation | asyncio.wait_for wraps the entire gather; if AirPlay 5 s scan equals DISCOVERY_TIMEOUT minus network overhead, a slow mDNS round cancels the Roku SSDP gather mid-flight | Fix option: use asyncio.wait with per-backend timeouts so a fast backend is not cancelled when a slow backend times out; document the cancel behavior |
| 7 | MEDIUM | roku_ecp - launch param casing ASSUMPTION | contentId/mediaType casing unverified on hardware; test locks in unverified casing; if device requires contentID/MediaType every Roku play returns HTTP 200 but nothing plays | Run devel/proof_roku.py on hardware; add a TODO comment in _build_launch_params naming the alternative casing to try on playback failure |
| 8 | MEDIUM | roku_ecp._status_from_media - None position or duration | float(media.position) and float(media.duration) called unconditionally; a live stream or device omitting these fields raises TypeError | Test: mock MediaState with paused=False position=None duration=None; assert TypeError or after fix PlaybackStatus with None fields; fix: guard with float(v) if v is not None else None |
| 9 | MEDIUM | app.select_device - unreachable default + no TTY | When --default-device is absent select_device falls back to devicepick.select(devices, None); in headless mode that raises ValueError but the prior stderr notice about the unreachable device obscures the real reason | Test: --default-device set to absent identifier no TTY; assert ValueError propagates; or wrap it in Airplay2tvError with a clear headless message |
| 10 | LOW | pairing._find_backend vs app.backend_for_device inconsistency | _find_backend has a single-backend fallback; backend_for_device raises on any key mismatch; a device whose backend field disagrees with the one active backend behaves differently depending on which code path runs | Test: one backend active; device with mismatched backend field; verify _find_backend returns the backend; verify backend_for_device raises; then align the two |
| 11 | LOW | credentials.load - non-list YAML | If credentials.yaml contains valid YAML that is not a list (e.g. manually edited to a dict), iterating raw raises KeyError on entry["identifier"] rather than a clear error | Test: write a dict to credentials.yaml; call load(); assert a typed error rather than a bare KeyError |
| 12 | LOW | httpserver - multi-range request returns 416 not 200 | parse_range_header returns None for a comma-containing multi-range triggering 416; RFC 9110 says the server SHOULD return the whole entity for unsupported multi-range | Document the choice in a comment; no behavior change needed unless a real client breaks on 416 |
| 13 | LOW | media._consume_progress - cancel latency | cancel_event is checked at the top of the for-line loop; cancellation latency is one full ffmpeg progress-update interval (~0.5-1 s) | Document the latency bound in the docstring; test: set cancel_event before the loop starts; assert process.terminate() is called on the first iteration |
| 14 | LOW | media._check_disk_space - remux skips disk check | Disk space is checked only before transcode; a large-file remux can require similar space | Add _check_disk_space call before remux too; test: mock shutil.disk_usage to return insufficient space; call prepare with a remux-destined file; assert PreparationError |

## Coverage summary by seam

### app.py

- Cleanup on failure paths: covered by test_app_cleanup.py for prepare-fail and
  play-fail. GAP: Ctrl+C during prepare_media (finding 1) and during ensure_paired
  (finding 5) are not tested.
- backend_for_device zero/multiple match: covered by test_app_flow.py.
- --default-device unreachable fallback: covered for the picker-fallback case.
  GAP: headless fallback raises ValueError from the picker (finding 9).

### backends/airplay.py

- Connection-per-action: covered; each test creates a fresh connection.
- Credential round-trip: covered by test_play_loads_credentials_and_calls_play_url.
- Status mapping: covered for Playing/Paused states. GAP: no test for an unmapped
  DeviceState falling back to idle.
- Pairing handshake error paths: covered for wrong PIN and AuthenticationError. GAP:
  pairing.close() raising while has_paired is False can swallow the original error (finding 3).

### backends/roku_ecp.py

- Launch param casing ASSUMPTION: test locks in the unverified casing (finding 7).
- 403 handling: covered by test_play_403_raises_device_unreachable.
- Status when media is None: covered by test_status_maps_idle_when_no_session. GAP:
  media.position or media.duration being None on a non-None MediaState is not tested
  (finding 8).

### media.py

- decide logic: comprehensive in test_media_decision.py.
- inspect + ffprobe field-missing: no test for missing audio or video stream
  against decide (finding 4).
- Mid-transcode cancel: not tested for KeyboardInterrupt path (findings 1, 13).
- Disk-space heuristic: not tested (finding 14).
- mov/mp4/m4v content-type mapping: covered implicitly via e2e only.

### httpserver.py

- Multi-range 416: covered by unit test; behavior documented as low risk (finding 12).
- Thread lifecycle: test_shutdown_joins_serving_thread covers this.

### pairing.py vs app.py

- Single-backend fallback inconsistency: finding 10 is untested as a divergence check.

### credentials.py

- Loose-perms warning: covered by test_credentials.py.
- Concurrent save: no test; data-loss risk (finding 2).
- Non-list YAML: no test (finding 11).

### discovery/aggregate.py

- Shared-timeout starvation: current tests cover exception-tolerates and empty-list cases.
  GAP: no test documents behavior when a backend is mid-gather when the timeout fires
  (finding 6 -- behavior is correct but undocumented).

## Top 3 must-look items

1. Finding 1 (HIGH): cancel_event is never set on KeyboardInterrupt during
   prepare_media. If the user presses Ctrl+C during a long transcode, ffmpeg
   continues running until the process is killed. The temp dir is removed by the
   outer finally, but the partial output is not cleaned up because _run_ffmpeg is
   unaware of the interrupt.

2. Finding 2 (HIGH): Concurrent calls to save_record both call load(), merge
   independently, and write back. The second writer silently discards the first
   writer's record. This is realistic when run_stream persists a device credential
   at the same time another code path writes an updated record.

3. Finding 8 (MEDIUM): _status_from_media calls float(media.position) and
   float(media.duration) unconditionally on a non-None MediaState. If rokuecp
   returns a MediaState with None position or duration (live stream, or device
   firmware that omits these fields), the call raises TypeError with no recovery.

