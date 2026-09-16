#!/usr/bin/env python3
"""Stop libaudioclient from waiting forever for an AudioFlinger that cannot exist.

Halium's own patch, 0004-halium-get-rid-of-using-AudioFlinger-for-recording,
replaces AudioFlinger with a local RecordThread reached through
android.media.ICameraRecordService, and cuts AudioFlinger out of
createRecord_l(), getInputBufferSize(), getInputFramesLost() and
newAudioUniqueId(). It misses AudioSystem::releaseAudioSessionId(), which
~AudioRecord() calls on teardown. There is no media.audio_flinger service in
Halium at all -- audioserver is not even in the GSI -- and get_audio_flinger()
loops on getService() forever, half a second at a time.

The result: MediaRecorderClient::release() never returns after a video
recording is stopped, the binder transaction from the camera app never
completes, and the app freezes. Stack taken from the device:

    MediaRecorderClient::release()            libmedia_compat_layer.so
    -> StagefrightRecorder::~StagefrightRecorder()
       -> AudioSource::~AudioSource()
          -> AudioRecord::~AudioRecord()
             -> AudioSystem::releaseAudioSessionId()
                -> AudioSystem::get_audio_flinger()      <-- never returns

Both releaseAudioSessionId() and acquireAudioSessionId() return void and have
nothing to release or acquire without an AudioFlinger, so this rewrites each
function's first instruction into a return.

Offsets are resolved from the symbol table, so this keeps working when the GSI
is rebuilt.

    scripts/patch-libaudioclient.py /android/system/lib/libaudioclient.so \
        overlay/usr/lib/halium-audioflinger-fix/libaudioclient32.so
"""
import struct
import sys

RET = {
    #  EM_ARM: thumb "bx lr"        EM_AARCH64: "ret"
    40: (b"\x70\x47", "bx lr"),
    183: (b"\xc0\x03\x5f\xd6", "ret"),
}
WANTED = ("releaseAudioSessionId", "acquireAudioSessionId")


def parse(data):
    """Return (machine, [(name, vaddr)], [(vaddr, offset, size)])."""
    if data[:4] != b"\x7fELF":
        sys.exit("not an ELF file")
    bits64 = data[4] == 2
    machine = struct.unpack_from("<H", data, 18)[0]
    fmt = "<HHIQQQIHHHHHH" if bits64 else "<HHIIIIIHHHHHH"
    (_, _, _, _, e_phoff, e_shoff, _, _, e_phentsize, e_phnum,
     e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from(fmt, data, 16)

    segments = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        if bits64:
            p_type, _, p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<IIQQQQ", data, o)
        else:
            p_type, p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<IIIII", data, o)
        if p_type == 1:  # PT_LOAD
            segments.append((p_vaddr, p_offset, p_filesz))

    sections = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        if bits64:
            sh_name, sh_type, _, _, sh_offset, sh_size, sh_link, _, _, sh_entsize = \
                struct.unpack_from("<IIQQQQIIQQ", data, o)
        else:
            sh_name, sh_type, _, _, sh_offset, sh_size, sh_link, _, _, sh_entsize = \
                struct.unpack_from("<IIIIIIIIII", data, o)
        sections.append((sh_name, sh_type, sh_offset, sh_size, sh_link, sh_entsize))

    syms = []
    for sh_name, sh_type, sh_offset, sh_size, sh_link, sh_entsize in sections:
        if sh_type not in (2, 11) or not sh_entsize:  # SYMTAB, DYNSYM
            continue
        stroff = sections[sh_link][2]
        for k in range(sh_size // sh_entsize):
            o = sh_offset + k * sh_entsize
            if bits64:
                st_name, _, _, _, st_value, _ = struct.unpack_from("<IBBHQQ", data, o)
            else:
                st_name, st_value, _, _, _, _ = struct.unpack_from("<IIIBBH", data, o)
            if not st_name or not st_value:
                continue
            end = data.index(b"\0", stroff + st_name)
            syms.append((data[stroff + st_name:end].decode("latin1"), st_value))
    return machine, syms, segments


def to_offset(vaddr, segments):
    for p_vaddr, p_offset, p_filesz in segments:
        if p_vaddr <= vaddr < p_vaddr + p_filesz:
            return vaddr - p_vaddr + p_offset
    sys.exit(f"vaddr {vaddr:#x} is in no PT_LOAD segment")


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    data = bytearray(open(argv[1], "rb").read())
    machine, syms, segments = parse(bytes(data))
    if machine not in RET:
        sys.exit(f"unsupported machine {machine}")
    insn, mnemonic = RET[machine]

    done = 0
    for want in WANTED:
        hits = [(n, v) for n, v in syms
                if want in n and n.startswith("_ZN7android11AudioSystem")]
        if not hits:
            sys.exit(f"no symbol for {want}; is this libaudioclient.so?")
        name, vaddr = hits[0]
        vaddr &= ~1                      # thumb symbols carry the low bit
        off = to_offset(vaddr, segments)
        if bytes(data[off:off + len(insn)]) == insn:
            print(f"  {want}: already returns immediately")
        else:
            data[off:off + len(insn)] = insn
            print(f"  {want}: {name} at {vaddr:#x} (file {off:#x}) -> {mnemonic}")
        done += 1

    open(argv[2], "wb").write(bytes(data))
    print(f"wrote {argv[2]} ({done} functions neutralised)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
