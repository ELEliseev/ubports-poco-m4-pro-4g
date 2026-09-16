/*
 * A shim for media-hub on the fleur port.
 *
 * On every playback session media-hub asks D-Bus for the caller's security
 * label (GetConnectionCredentials -> LinuxSecurityLabel) and requires it to be
 * the name of an AppArmor profile. AppArmor is not active on this kernel: 4.14
 * runs only one major security module at a time and that is SELinux. So
 * SO_PEERSEC returns the SELinux label, the string "kernel", the constructor of
 * apparmor::lomiri::Context decides it is invalid, throws, and the service dies
 * with SIGSEGV. The stock player then plays nothing at all.
 *
 * The shim tells the constructor the client is unconfined - exactly what it
 * would see on a system without AppArmor. Nothing is weakened: there is no
 * confinement in the first place, because AppArmor is off.
 *
 * Build: aarch64-linux-gnu-gcc -shared -fPIC -O2 -o libfleur-aa-shim.so fleur-aa-shim.c
 */
#define _GNU_SOURCE
#include <stdlib.h>
#include <string.h>

/* lomiri::MediaHubService::apparmor::lomiri::Context::is_unconfined() const */
int _ZNK6lomiri15MediaHubService8apparmor6lomiri7Context13is_unconfinedEv(void *self)
{
	(void) self;
	return 1;
}

/* In case the label is parsed through libapparmor instead. */
char *aa_splitcon(char *con, char **mode)
{
	(void) con;
	if (mode)
		*mode = NULL;
	return strdup("unconfined");
}
