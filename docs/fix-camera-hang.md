# The camera freezing after a video is stopped

**Symptom.** Video recorded, but pressing "stop" froze the camera app solid:
"Could not take a photo" on screen, dead buttons. The only cure was killing the
app.

**This also turned out to be why video had no sound.** Fixing it produced a
working audio track, which contradicts the earlier conclusion that recording
audio is impossible on modern Halium ports. It is not.

## Cause

Taken as a native stack from the device — `debuggerd` on the 32-bit
`/system/bin/camera_service`, thread `Binder:_4`:

```
MediaRecorderClient::release()            libmedia_compat_layer.so
└ StagefrightRecorder::~StagefrightRecorder()
  └ AudioSource::~AudioSource()
    └ AudioRecord::~AudioRecord()
      └ AudioSystem::releaseAudioSessionId()      libaudioclient.so
        └ AudioSystem::get_audio_flinger()        ← never returns
```

`get_audio_flinger()` runs `while (true) { getService("media.audio_flinger");
usleep(500000); }`. There is no `media.audio_flinger` service in Halium and
there cannot be: `audioserver` is not even in the GSI, because audio goes
through PulseAudio. The thread never leaves the loop, so the binder transaction
from the app never completes.

In the log it looks like this, every 5.5 seconds, forever:

```
ServiceManager: Waiting for service 'media.audio_flinger' on '/dev/binder'
ServiceManager: Service media.audio_flinger didn't start. Returning NULL
AudioSystem: AudioFlinger not published, waiting...
```

## This is a gap in Halium itself, not in this port

Halium's own patch,
`hybris-patches/frameworks/av/0004-halium-get-rid-of-using-AudioFlinger-for-recording.patch`,
is fully applied in the image. You can verify that from the exported symbols
rather than from sources you think you have:

* `libaudioclient.so` — 147 `RecordThread` / `RecordTrack` /
  `CameraRecordService` symbols;
* `libstagefright.so` — `AudioSource::setReadAudioCb` and `triggerReadAudio`;
* `libmediaplayerservice.so` — `StagefrightRecorder::onReadAudio`;
* `android.media.ICameraRecordService` is registered (`service list`).

`createRecord_l()`, `getInputBufferSize()`, `getInputFramesLost()` and
`newAudioUniqueId()` are all cut loose from AudioFlinger. The one that was
missed is `releaseAudioSessionId()`, which `~AudioRecord()` calls on teardown.
Recording works; releasing hangs.

## The fix

In both `libaudioclient.so` libraries, the bodies of `releaseAudioSessionId()`
and `acquireAudioSessionId()` are replaced with an immediate return — the first
halfword becomes `4770` (`bx lr`) on arm, the first word `d65f03c0` (`ret`) on
arm64. Both functions return `void`, and with no AudioFlinger there is nothing
to release or acquire. `acquireAudioSessionId()` is done for symmetry: it is
built the same way and would hang the device the same way.

The patch is binary because we do not build the GSI — it is downloaded ready-made
from UBports CI. `scripts/patch-libaudioclient.py` regenerates both libraries
from a stock GSI, resolving the offsets from the symbol table so it keeps working
across GSI rebuilds:

```bash
scripts/patch-libaudioclient.py /android/system/lib/libaudioclient.so \
    overlay/usr/lib/halium-audioflinger-fix/libaudioclient32.so
scripts/patch-libaudioclient.py /android/system/lib64/libaudioclient.so \
    overlay/usr/lib/halium-audioflinger-fix/libaudioclient64.so
```

The equivalent source change, if the GSI is ever built locally, belongs in
`frameworks/av/media/libaudioclient/AudioSystem.cpp` and follows what Halium's
patch 0004 already does to `getInputFramesLost()`:

```c
void AudioSystem::acquireAudioSessionId(audio_session_t, pid_t, uid_t) {
    /* no AudioFlinger in Halium — nothing to acquire */
}
void AudioSystem::releaseAudioSessionId(audio_session_t, pid_t) {
    /* no AudioFlinger in Halium — nothing to release */
}
```

## Delivery

`overlay/usr/lib/halium-audioflinger-fix/` holds the two patched libraries and
the `apply` script; `overlay/etc/systemd/system/halium-audioflinger-fix.service`
plus a link in `sysinit.target.wants` runs it.

**The unit has to run before the container starts**, which is why it is in
`sysinit.target.wants` and not `multi-user.target.wants`:
`lxc-android-config.service` lives in `sysinit.target` with
`DefaultDependencies=no`, and `camera_service` loads the library once, when the
container comes up.

The `apply` script checks the md5 of the library it is about to shadow against
the GSI revision the patch was made for, and quietly does nothing if they
differ. Otherwise an old library would be laid over a newer GSI after a CI
rebuild. The expected checksums are in
`overlay/usr/lib/halium-audioflinger-fix/ORIGINALS.md5`; regenerate the patched
libraries after a GSI update.

## Result, measured on the device

| | before | after |
|---|---|---|
| AudioFlinger waits in the log | endless | **0** |
| stuck threads in `camera_service` | yes | none |
| stopping a recording | hung | MOOV written, tracks closed with `Status:0` |
| audio track | empty | **81 AAC frames, 112–177 bytes, varying** |

Varying frame sizes are what tells you it is a real microphone rather than
digital silence.

That last row overturns the earlier conclusion that "video recording has no
sound on any modern Halium port". Halium's mechanism — `AudioRecord` on top of
`CameraRecordService` and `RecordThread`, reading `/dev/socket/micshm` — is
present and works. One call on the teardown path was all that stood in the way.
A 183-line `libmedia` patch written earlier to read `/dev/socket/micshm` from
the AOSP side is not needed.

## Techniques worth remembering

* The diagnosis came from `debuggerd <pid>` inside the container, not from the
  log. It prints the stacks of every thread. `wchan` is useless here — the
  thread sits in `nanosleep`.
* `camera_service` is **32-bit**: disassemble `/system/lib`, not
  `/system/lib64`. (The wrong libraries were pulled first.)
* Check whether a Halium patch is applied by looking at exported symbols
  (`nm -DC --defined-only`), not at the sources.
* To test a change without rebuilding the rootfs: put the file in
  `/android/data/local/tmp`, `mount --bind` it over the file in
  `/android/system` — a read-only mount does not prevent this — and then
  `setprop ctl.restart camera_service`. The bind mount **is** visible inside the
  container; verify by inode in `/proc/PID/maps`.

## Still open

The video bitrate is absurd: 32 frames of 1920×1440 took 27 MB, about 848 KB
per frame, roughly 130 Mbit/s. The encoder barely compresses. The app also asks
for an impossible audio rate — *"Intended audio sample rate (96000) is too large
and will be set to (48000)"*.
