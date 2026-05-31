#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFA3 MAX - Native 16:9 widescreen patcher (PATTERN-SCAN, multi-region)
======================================================================

Locates everything by INSTRUCTION PATTERNS (not fixed addresses), so it works
on EU and US (and JP once validated) decrypted EBOOTs regardless of build
offsets. Applies viewport opener + BG FULL widescreen prepend.

Input: a DECRYPTED EBOOT.BIN (ELF). For an encrypted EBOOT, decrypt it first
with an external tool (e.g. PRXDecrypter); PPSSPP runs decrypted EBOOTs.

Usage:
    python sfa3_ws_patternpatcher.py  <EBOOT.BIN>  [output]

Conventions: EBOOT image base VA0 -> file 0x74. Runtime load base 0x08804000
(hand-injected jumps use runtime targets, since the loader does not relocate
them).
"""
import os, sys, struct

RUNBASE = 0x08804000
def J(va):
    return 0x08000000 | (((va + RUNBASE) >> 2) & 0x03FFFFFF)

# ============================================================================
# Pattern engine
# ============================================================================
def find_all(buf, sig, start=0, end=None):
    """Return all 4-aligned offsets where bytes 'sig' occur."""
    if end is None: end = len(buf)
    out, i = [], start
    while True:
        i = buf.find(sig, i, end)
        if i < 0: break
        if i % 4 == 0: out.append(i)
        i += 4
    return out

def w32(x): return struct.pack("<I", x)

# ============================================================================
# VIEWPORT patches (pattern-based)
# ============================================================================
# VP1: 'ori a2/a3,zero,0x180' used as render-width near 'ori a3,zero,0x90/0xa8/
#      0xe0/0xac' or '8fb00010'. We reuse the 8-byte windows that uniquely hit
#      exactly the 8 width sites (validated EU+US). Patch the 0x180->0x1E0.
VP_WIDTH_WINDOWS = [
    bytes.fromhex("8001063490000734"),
    bytes.fromhex("80010634a8000734"),
    bytes.fromhex("80010634e0000734"),
    bytes.fromhex("80010634ac000734"),
    bytes.fromhex("80010634e229000c"),   # appears twice
    bytes.fromhex("800106341000b08f"),   # appears twice
]
# the 0x180 ori is the FIRST word of each window: 34 06 01 80 (LE: 80 01 06 34)
# patch low imm byte 0x80->0xE0 (0x180->0x1E0) at window+0.

# VP2: camera left bound 'li t0,-192' (addiu t0,zero,-0xC0 = 0x3408FF40) -> -240
#      (0x3408FF10). 11 consecutive sites. Patch ALL occurrences of that exact
#      word that fall in the camera table (we patch every occurrence; validated
#      that the word only appears as this table, 11x EU & US).
VP_CAM_OLD = 0x3408FF40   # li t0,-192
VP_CAM_NEW = 0x3408FF10   # li t0,-240

# VP3: the FUN_b160 viewport scaler. In EU it was a scanned 0x180->0x1E0 plus a
#      pillarbox kill. We fold those into VP_WIDTH (covers the 0x180 width) and
#      a pillarbox pattern below.
# Pillarbox: a small leaf 'jr ra; nop' replacement at the function that draws the
#      side bars. We detect it by its unique prologue window and neutralize.
#      (Pattern captured from EU @ B390-ish; validated to exist in US too.)
#      To stay safe across regions we DETECT by a distinctive instruction window
#      rather than address; if not found we warn (viewport still opens via width).

# ============================================================================
# BG FULL prepend (signatures are byte-identical EU & US at same VAs, but we
# still locate by unique signature words to be region-proof)
# ============================================================================
SIG_HOOKA = 0xA6090008   # FUN_17268: sh t1,8(s0)   (unique)
SIG_HOOKB = 0xA6280008   # FUN_16B28: sh t0,8(s1)   (unique)
SIG_CNT16 = 0x28C40019   # FUN_17268: slti a0,a2,25 (unique)
# 32px count gates: two 'slti X,13' that belong to FUN_16B28. We disambiguate by
# proximity to HOOKB.
SIG_CNT32_A = 0x28C7000D # slti a3,a2,13
SIG_CNT32_B = 0x28C4000D # slti a0,a2,13

NEW_CNT16   = 0x28C4001F # ->31
NEW_CNT32_A = 0x28C70011 # ->17
NEW_CNT32_B = 0x28C40011 # ->17

# code caves in proven-safe exec padding hole. We locate the hole dynamically:
# a run of >=0x40 zero bytes within the exec segment, near end of .text.
def find_exec_zero_hole(buf, need_words):
    """Find a 4-aligned zero run of at least need_words*4 bytes in the code
    region (file < ~0x2d5000). Returns the VA of the hole start."""
    # parse ELF phdr to get exec filesz
    e_phoff = struct.unpack_from("<I", buf, 0x1C)[0]
    e_phnum = struct.unpack_from("<H", buf, 0x2C)[0]
    e_phentsz = struct.unpack_from("<H", buf, 0x2A)[0]
    exec_end = None
    for i in range(e_phnum):
        b = e_phoff + i*e_phentsz
        p_off, p_vaddr, p_filesz, p_flags = (
            struct.unpack_from("<I", buf, b+4)[0],
            struct.unpack_from("<I", buf, b+8)[0],
            struct.unpack_from("<I", buf, b+16)[0],
            struct.unpack_from("<I", buf, b+24)[0],
        )
        if p_flags & 1:  # exec
            exec_end = p_off + p_filesz
    if exec_end is None:
        exec_end = 0x2d4fa4
    need = need_words*4
    # scan from a safe point; prefer the known-good 0x1FF1B4 area first.
    j = 0x74
    best = None
    while j < exec_end:
        if buf[j] == 0:
            k = j
            while k < exec_end and buf[k] == 0:
                k += 1
            if k - j >= need:
                va = j - 0x74
                # align to 4
                if va % 4: va += 4 - (va % 4)
                return va  # first suitable hole
            j = k
        else:
            j += 1
    return None

# ============================================================================
VP1_PREWIN = bytes.fromhex("3200a5a72400a4a7")   # unique; next word = ori a0,0x180
VP2_SIG    = bytes.fromhex("90ffbd276000b0af2000103c")  # pillarbox fn prologue (12B, unique)
JR_RA_NOP  = bytes.fromhex("0800e00300000000")          # jr ra ; nop

def patch(buf, log):
    err = 0
    # ---------- VP1: ori a0,zero,0x180 -> 0x1E0 (FUN_b160 scaler) ----------
    p = buf.find(VP1_PREWIN)
    if p >= 0 and buf.count(VP1_PREWIN) == 1:
        wpos = p + 8
        if buf[wpos:wpos+4] == bytes.fromhex("80010434"):
            buf[wpos] = 0xE0
            log.append("VP1 scaler 0x180->0x1E0: [ok]")
        elif buf[wpos:wpos+4] == bytes.fromhex("e0010434"):
            log.append("VP1 scaler: [skip]")
        else:
            log.append(f"  [WARN] VP1 mot inattendu {buf[wpos:wpos+4].hex()}")
    else:
        log.append(f"  [WARN] VP1 prewin trouve {buf.count(VP1_PREWIN)}x (attendu 1)")

    # ---------- VP2: neutralize pillarbox function (jr ra; nop) ----------
    q = buf.find(VP2_SIG)
    if q >= 0 and buf.count(VP2_SIG) == 1:
        if buf[q:q+8] != JR_RA_NOP:
            buf[q:q+8] = JR_RA_NOP
            log.append("VP2 pillarbox kill: [ok]")
        else:
            log.append("VP2 pillarbox: [skip]")
    elif buf.find(JR_RA_NOP) >= 0 and buf.count(VP2_SIG) == 0:
        log.append("VP2 pillarbox: [skip] (deja neutralise)")
    else:
        log.append(f"  [WARN] VP2 signature trouvee {buf.count(VP2_SIG)}x (attendu 1)")

    # ---------- VP width 0x180 -> 0x1E0 ----------
    width_hits = 0
    for win in VP_WIDTH_WINDOWS:
        for off in find_all(buf, win):
            # the 0x180 ori is window+0: low byte at off+0 is 0x80 -> 0xE0
            if buf[off] == 0x80 and buf[off+1] == 0x01 and buf[off+2] == 0x06 and buf[off+3] == 0x34:
                buf[off] = 0xE0
                width_hits += 1
    log.append(f"VP width 0x180->0x1E0: {width_hits} site(s)")
    if width_hits < 8:
        log.append(f"  [WARN] attendu >=8 sites largeur, trouve {width_hits}")

    # ---------- VP camera left -192 -> -240 ----------
    cam_hits = 0
    for off in find_all(buf, w32(VP_CAM_OLD)):
        struct.pack_into("<I", buf, off, VP_CAM_NEW); cam_hits += 1
    log.append(f"VP camera -192->-240: {cam_hits} site(s)")
    if cam_hits < 11:
        log.append(f"  [WARN] attendu 11 sites camera, trouve {cam_hits}")

    # ---------- locate BG hooks by signature ----------
    def uniq(sig, name):
        h = find_all(buf, w32(sig))
        if len(h) != 1:
            log.append(f"  [ERR] {name}: {len(h)} sites (attendu 1)")
            return None
        return h[0]

    hookA = uniq(SIG_HOOKA, "hookA sh t1,8(s0)")
    hookB = uniq(SIG_HOOKB, "hookB sh t0,8(s1)")
    cnt16 = uniq(SIG_CNT16, "count16 slti a0,a2,25")
    if None in (hookA, hookB, cnt16):
        err += 1

    # 32px counts: pick the ones nearest to hookB (FUN_16B28 body)
    def nearest(sig, ref, name):
        h = find_all(buf, w32(sig))
        if not h:
            log.append(f"  [ERR] {name}: introuvable"); return None
        # within +/- 0x400 bytes of ref
        cand = [x for x in h if abs(x - ref) < 0x600]
        if len(cand) != 1:
            log.append(f"  [ERR] {name}: {len(cand)} candidats pres de hookB")
            return None
        return cand[0]

    cnt32a = nearest(SIG_CNT32_A, hookB, "count32a slti a3,a2,13") if hookB else None
    cnt32b = nearest(SIG_CNT32_B, hookB, "count32b slti a0,a2,13") if hookB else None
    if None in (cnt32a, cnt32b):
        err += 1

    if err:
        log.append(f"\n!! {err} erreur(s) BG -> aucune ecriture BG.")
        return err

    # offsets (file) -> VA
    vaHookA = hookA - 0x74
    vaHookB = hookB - 0x74
    # caves: place in zero hole; need 7+7 = 14 words
    cave_va = find_exec_zero_hole(buf, 14)
    if cave_va is None:
        log.append("  [ERR] pas de trou exec pour les caves"); return 1
    caveA_va = cave_va
    caveB_va = cave_va + 7*4
    log.append(f"caves @ VA {caveA_va:#x} / {caveB_va:#x}")

    CAVE_A = [0x2529FFD0, 0xA6090008, 0x8E0C0010, 0x258CFFF4, 0xAE0C0010, J(vaHookA+8), 0]
    CAVE_B = [0x2508FFC0, 0xA6280008, 0x8E2C0010, 0x258CFFF8, 0xAE2C0010, J(vaHookB+8), 0]

    def wva(va, word): struct.pack_into("<I", buf, va + 0x74, word)
    # verify caves empty
    for cb, cave in [(caveA_va, CAVE_A), (caveB_va, CAVE_B)]:
        for i in range(len(cave)):
            if struct.unpack_from("<I", buf, cb + i*4 + 0x74)[0] != 0:
                log.append(f"  [ERR] cave {cb+i*4:#x} non vide"); return 1
    for cb, cave in [(caveA_va, CAVE_A), (caveB_va, CAVE_B)]:
        for i, wd in enumerate(cave): wva(cb + i*4, wd)
    # counts (right extension)
    struct.pack_into("<I", buf, cnt16,  NEW_CNT16)
    struct.pack_into("<I", buf, cnt32a, NEW_CNT32_A)
    struct.pack_into("<I", buf, cnt32b, NEW_CNT32_B)
    # hooks (last)
    struct.pack_into("<I", buf, hookA, J(caveA_va))
    struct.pack_into("<I", buf, hookB, J(caveB_va))
    log.append("BG FULL prepend: [ok]")
    return 0

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    src = sys.argv[1]
    if not os.path.isfile(src):
        print("Introuvable:", src); sys.exit(1)
    dst = sys.argv[2] if len(sys.argv) >= 3 else os.path.splitext(src)[0] + "_WS.BIN"
    with open(src, "rb") as f: buf = bytearray(f.read())
    if buf[:4] != b"\x7fELF":
        print("Pas un EBOOT decrypte (ELF). Dechiffre-le d'abord."); sys.exit(2)
    log = []
    err = patch(buf, log)
    print("\n".join(log))
    if err: print("\nABANDON."); sys.exit(3)
    with open(dst, "wb") as f: f.write(buf)
    print(f"\nOK -> {dst}")
    print("Regle l'affichage INTERNE du jeu sur 'Normal'.")

if __name__ == "__main__":
    main()
