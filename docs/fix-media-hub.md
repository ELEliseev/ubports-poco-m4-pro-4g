# media-hub crashes on an SELinux security label

`overlay/usr/bin/media-hub-server` is the **stock** Ubuntu Touch binary with one
change. It is not shipped in this repository — see
`scripts/patch-media-hub.sh`, which reproduces it from your own copy.

## Why

Every time it creates a playback session, media-hub asks D-Bus for the caller's
security label (`GetConnectionCredentials` → `LinuxSecurityLabel`) and requires
it to be the name of an AppArmor profile.

AppArmor is not active on this port. A 4.14 kernel runs only one major LSM at a
time, and that slot is taken by SELinux, which the vendor HALs need. So
`SO_PEERSEC` returns the SELinux label — the string `"kernel"`. The constructor
of `apparmor::lomiri::Context` decides that is not a valid profile name, throws,
and the service dies with SIGSEGV.

From the outside this looks like "the player does not understand this file".

## The change

The string constant at offset 678928 — the name media-hub compares against when
deciding whether a client is unconfined — is changed from `"unconfined"` to
`"kernel"`, so `is_unconfined()` returns true and the client counts as
unconfined.

Nothing is weakened by this. There is no confinement to begin with: AppArmor is
off.

```bash
scripts/patch-media-hub.sh /usr/bin/media-hub-server \
                           overlay/usr/bin/media-hub-server
```

The script refuses to touch anything but the exact build it knows
(`media-hub 4.7~20251006100339.1~45d5f81+ubports20.04`, md5
`154f1b170b6c9c578fbf81646a171285`) and verifies the result.

## Checking it worked

In the media-hub log, instead of

```
is_unconfined(): false → Invalid profile name kernel → SIGSEGV
```

you should see

```
is_unconfined(): true
```

## Caveats

**This binary is tied to a package version.** If media-hub is updated, the
overlay copy will shadow the new one — re-run the script against the new binary.
Keep the untouched original next to it as `/usr/bin/media-hub-server.orig`.

**The proper fix would be to run AppArmor**, which requires SELinux to run
alongside it. Do not simply switch AppArmor on: without
`androidboot.selinux=permissive` you get a boot loop, and with it the screen
flickers while `lightdm` restarts six times in half a minute. AppArmor denies
nothing useful in the meantime — with `audit=1`, 45 seconds produced a single
denial, and it had nothing to do with graphics. The damage comes from giving up
SELinux, not from AppArmor itself.
