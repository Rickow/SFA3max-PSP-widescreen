#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFA3 MAX - Native 16:9 widescreen patcher (PATTERN-SCAN, multi-region)  v1.1
============================================================================

Locates everything by INSTRUCTION PATTERNS (not fixed addresses), so it works
on EU, US and JP decrypted EBOOTs regardless of build offsets.

v1.0 : viewport opener + BG FULL widescreen prepend (3 tilemap drawers hook).
v1.1 : + painted-decor cull widen (temple/trees/menus, the "8th pipeline"),
       + wrap-seam vertical-shift fix on all 3 tilemap drawers,
       + 3rd tilemap drawer (FUN_177c8) full treatment (count+hook+wrapfix).

Input: a DECRYPTED EBOOT.BIN (ELF). For an encrypted EBOOT, decrypt it first
with an external tool (e.g. PRXDecrypter); PPSSPP runs decrypted EBOOTs.

Usage:
    python sfa3_ws_patternpatcher.py  <EBOOT.BIN>  [output]

Conventions: EBOOT image base VA0 -> file 0x74. Runtime load base 0x08804000
(hand-injected jumps use runtime targets, since the loader does not relocate
them). After patching, set the game's INTERNAL display option to 'Normal'.
"""
import os, sys, struct

RUNBASE = 0x08804000
def J(va):
    return 0x08000000 | (((va + RUNBASE) >> 2) & 0x03FFFFFF)
def w32(x): return struct.pack("<I", x)

# ----------------------------------------------------------------------------
# Pattern engine
# ----------------------------------------------------------------------------
def find_all(buf, sig, start=0, end=None):
    if end is None: end = len(buf)
    out, i = [], start
    while True:
        i = buf.find(sig, i, end)
        if i < 0: break
        if i % 4 == 0: out.append(i)
        i += 4
    return out

# ----------------------------------------------------------------------------
# VIEWPORT patches (v1.0)
# ----------------------------------------------------------------------------
VP_WIDTH_WINDOWS = [
    bytes.fromhex("8001063490000734"),
    bytes.fromhex("80010634a8000734"),
    bytes.fromhex("80010634e0000734"),
    bytes.fromhex("80010634ac000734"),
    bytes.fromhex("80010634e229000c"),   # appears twice
    bytes.fromhex("800106341000b08f"),   # appears twice
]
VP_CAM_OLD = 0x3408FF40   # li t0,-192
VP_CAM_NEW = 0x3408FF10   # li t0,-240
VP1_PREWIN = bytes.fromhex("3200a5a72400a4a7")          # next word = ori a0,0x180
VP2_SIG    = bytes.fromhex("90ffbd276000b0af2000103c")  # pillarbox fn prologue
JR_RA_NOP  = bytes.fromhex("0800e00300000000")

# ----------------------------------------------------------------------------
# BG tilemap drawers (v1.0 hooks + counts)
# ----------------------------------------------------------------------------
SIG_HOOKA = 0xA6090008   # FUN_17268 (draw16): sh t1,8(s0)   (unique)
SIG_HOOKB = 0xA6280008   # FUN_16B28 (draw32): sh t0,8(s1)   (unique)
SIG_CNT16 = 0x28C40019   # FUN_17268: slti a0,a2,25 (unique)
SIG_CNT32_A = 0x28C7000D # slti a3,a2,13
SIG_CNT32_B = 0x28C4000D # slti a0,a2,13
NEW_CNT16   = 0x28C4001F # ->31
NEW_CNT32_A = 0x28C70011 # ->17
NEW_CNT32_B = 0x28C40011 # ->17

# ----------------------------------------------------------------------------
# v1.1 : painted-decor cull (FUN_dc00 / context init FUN_77bc)
# ----------------------------------------------------------------------------
SIG_PAINT_R = 0x3C0743C0          # lui a3,0x43c0 (384.0f) -> 0x43f0 (480.0f). unique.
NEW_PAINT_R = 0x3C0743F0
# left bound : window 'lh a0,0x10(s0); subu t0,zr,a0' ; patch the subu->addiu t0,zr,-96
PAINT_L_WIN = bytes.fromhex("1000048623400400")   # 86040010 00044023 (unique)
NEW_PAINT_L = 0x2408FFA0          # addiu t0,zr,-96

# v1.1 : wrap-seam fix. Each tilemap drawer stores its wrap trigger with a unique
# 'sh rt,0x22(rs)' right after 'lh rt,0x58(rs)'. The v1.0 hook shifts the layer
# start left (ptr-=N cols) without adjusting this trigger -> the wrap rewind lands
# N cols early -> reads the row above -> 1-tile vertical shift at the seam. Fix =
# add +N to the trigger (N = cols the hook shifts: 3 for the 16px drawers, 2 for 32px).
WRAP_DRAW16 = (0xA6090022, 3)   # sh t1,0x22(s0)  (FUN_17268)  +3
WRAP_DRAW32 = (0xA6280022, 2)   # sh t0,0x22(s1)  (FUN_16B28)  +2
WRAP_177C8  = (0xA6080022, 2)   # sh t0,0x22(s0)  (FUN_177C8)  +2

# v1.1 : 3rd tilemap drawer FUN_177c8 (never widened by v1.0). Hooked + counted by
# proximity to its unique wrap store (WRAP_177C8 site).
SIG_HOOK177 = 0xA6080008   # sh t0,0x8(s0) (unique) : Xstart store of FUN_177c8

# ----------------------------------------------------------------------------
# Cave allocation across exec zero-holes
# ----------------------------------------------------------------------------
def find_exec_zero_holes(buf, min_words=4):
    e_phoff = struct.unpack_from("<I", buf, 0x1C)[0]
    e_phnum = struct.unpack_from("<H", buf, 0x2C)[0]
    e_phentsz = struct.unpack_from("<H", buf, 0x2A)[0]
    exec_end = None
    for i in range(e_phnum):
        b = e_phoff + i*e_phentsz
        p_off  = struct.unpack_from("<I", buf, b+4)[0]
        p_filesz = struct.unpack_from("<I", buf, b+16)[0]
        p_flags  = struct.unpack_from("<I", buf, b+24)[0]
        if p_flags & 1:
            exec_end = p_off + p_filesz
    if exec_end is None: exec_end = 0x2d4fa4
    holes, j = [], 0x74
    while j < exec_end:
        if buf[j] == 0:
            k = j
            while k < exec_end and buf[k] == 0: k += 1
            va = j - 0x74
            if va % 4: va += 4 - (va % 4)
            words = (k - (va + 0x74)) // 4
            if words >= min_words: holes.append([va, words])
            j = k
        else:
            j += 1
    return holes

class CaveAlloc:
    def __init__(self, holes): self.holes = holes
    def alloc(self, n):
        for h in self.holes:
            if h[1] >= n:
                va = h[0]; h[0] += n*4; h[1] -= n; return va
        return None

def addiu_word(reg, imm):
    """addiu reg,reg,imm"""
    return 0x24000000 | (reg << 21) | (reg << 16) | (imm & 0xFFFF)

# ----------------------------------------------------------------------------
def patch(buf, log):
    err = 0
    def uniq(sig, name):
        h = find_all(buf, w32(sig))
        if len(h) != 1:
            log.append(f"  [ERR] {name}: {len(h)} sites (attendu 1)"); return None
        return h[0]

    # ---------- VP1 ----------
    p = buf.find(VP1_PREWIN)
    if p >= 0 and buf.count(VP1_PREWIN) == 1:
        wpos = p + 8
        if buf[wpos:wpos+4] == bytes.fromhex("80010434"):
            buf[wpos] = 0xE0; log.append("VP1 scaler 0x180->0x1E0: [ok]")
        elif buf[wpos:wpos+4] == bytes.fromhex("e0010434"):
            log.append("VP1 scaler: [skip]")
        else:
            log.append(f"  [WARN] VP1 mot inattendu {buf[wpos:wpos+4].hex()}")
    else:
        log.append(f"  [WARN] VP1 prewin {buf.count(VP1_PREWIN)}x (attendu 1)")

    # ---------- VP2 pillarbox ----------
    q = buf.find(VP2_SIG)
    if q >= 0 and buf.count(VP2_SIG) == 1:
        if buf[q:q+8] != JR_RA_NOP:
            buf[q:q+8] = JR_RA_NOP; log.append("VP2 pillarbox kill: [ok]")
        else: log.append("VP2 pillarbox: [skip]")
    elif buf.find(JR_RA_NOP) >= 0 and buf.count(VP2_SIG) == 0:
        log.append("VP2 pillarbox: [skip] (deja neutralise)")
    else:
        log.append(f"  [WARN] VP2 signature {buf.count(VP2_SIG)}x (attendu 1)")

    # ---------- VP width ----------
    width_hits = 0
    for win in VP_WIDTH_WINDOWS:
        for off in find_all(buf, win):
            if buf[off:off+4] == bytes.fromhex("80010634"):
                buf[off] = 0xE0; width_hits += 1
    log.append(f"VP width 0x180->0x1E0: {width_hits} site(s)")
    if width_hits < 8: log.append(f"  [WARN] attendu >=8, trouve {width_hits}")

    # ---------- VP camera ----------
    cam_hits = 0
    for off in find_all(buf, w32(VP_CAM_OLD)):
        struct.pack_into("<I", buf, off, VP_CAM_NEW); cam_hits += 1
    log.append(f"VP camera -192->-240: {cam_hits} site(s)")
    if cam_hits < 11: log.append(f"  [WARN] attendu 11, trouve {cam_hits}")

    # ---------- v1.1 painted-decor cull (temple/trees/menus) ----------
    pr = uniq(SIG_PAINT_R, "paint right lui a3,0x43c0")
    if pr is not None:
        struct.pack_into("<I", buf, pr, NEW_PAINT_R)
        log.append("PAINT cull droite 384->480: [ok]")
    else: err += 1
    pl = find_all(buf, PAINT_L_WIN)
    if len(pl) == 1:
        struct.pack_into("<I", buf, pl[0]+4, NEW_PAINT_L)   # subu is 2nd word
        log.append("PAINT cull gauche -tile->-96: [ok]")
    else:
        log.append(f"  [ERR] paint left window: {len(pl)} sites (attendu 1)"); err += 1

    # ---------- locate BG tilemap sites ----------
    hookA = uniq(SIG_HOOKA, "hookA sh t1,8(s0)")
    hookB = uniq(SIG_HOOKB, "hookB sh t0,8(s1)")
    cnt16 = uniq(SIG_CNT16, "count16 slti a0,a2,25")
    wrapA = uniq(WRAP_DRAW16[0], "wrap draw16 sh t1,0x22(s0)")
    wrapB = uniq(WRAP_DRAW32[0], "wrap draw32 sh t0,0x22(s1)")
    wrap177 = uniq(WRAP_177C8[0], "wrap 177c8 sh t0,0x22(s0)")
    hook177 = uniq(SIG_HOOK177, "hook177 sh t0,0x8(s0)")
    if None in (hookA, hookB, cnt16, wrapA, wrapB, wrap177, hook177):
        err += 1

    def nearest(sig, ref, name, span=0x600):
        h = find_all(buf, w32(sig))
        cand = [x for x in h if abs(x - ref) < span]
        if len(cand) != 1:
            log.append(f"  [ERR] {name}: {len(cand)} candidats pres de {ref:#x}")
            return None
        return cand[0]

    cnt32a = nearest(SIG_CNT32_A, hookB, "count32a") if hookB else None
    cnt32b = nearest(SIG_CNT32_B, hookB, "count32b") if hookB else None
    # 177c8 counts: entry (28C7000D) and back-edge (28C4000D) near its wrap store
    cnt177e = nearest(SIG_CNT32_A, wrap177, "count177 entry", 0x40) if wrap177 else None
    cnt177b = nearest(SIG_CNT32_B, wrap177, "count177 back", 0x300) if wrap177 else None
    if None in (cnt32a, cnt32b, cnt177e, cnt177b):
        err += 1

    if err:
        log.append(f"\n!! {err} erreur(s) -> aucune ecriture BG/cull.")
        return err

    # ---------- caves ----------
    holes = find_exec_zero_holes(buf, 4)
    alloc = CaveAlloc(holes)
    def mkhook_xptr(site, hi_addiu_imm, lo_addiu_imm, shword):
        """Xstart-= / ptr-= hook cave (7 words). shword = original sh rt,0x8(rs)."""
        rt = (shword >> 16) & 0x1F; rs = (shword >> 21) & 0x1F
        va = alloc.alloc(7)
        if va is None: return None, None
        cave = [addiu_word(rt, hi_addiu_imm), shword,
                0x8C000010 | (rs << 21) | (12 << 16),      # lw t4,0x10(rs)
                addiu_word(12, lo_addiu_imm),              # addiu t4,t4,lo
                0xAC000010 | (rs << 21) | (12 << 16),      # sw t4,0x10(rs)
                J((site - 0x74) + 8), 0]
        return va, cave
    def mkwrap(site, plus, shword):
        """wrap-trigger += plus cave (4 words). shword = original sh rt,0x22(rs)."""
        rt = (shword >> 16) & 0x1F
        va = alloc.alloc(4)
        if va is None: return None, None
        return va, [addiu_word(rt, plus), shword, J((site - 0x74) + 8), 0]

    builds = []   # (cave_va, cave_words, hook_site_off)
    # v1.0 hooks (Xstart-=48/ptr-=12 for 16px; Xstart-=64/ptr-=8 for 32px)
    cA = mkhook_xptr(hookA, -48, -12, SIG_HOOKA); builds.append((cA, hookA))
    cB = mkhook_xptr(hookB, -64,  -8, SIG_HOOKB); builds.append((cB, hookB))
    # v1.1 wrap fixes
    wA = mkwrap(wrapA, WRAP_DRAW16[1], WRAP_DRAW16[0]); builds.append((wA, wrapA))
    wB = mkwrap(wrapB, WRAP_DRAW32[1], WRAP_DRAW32[0]); builds.append((wB, wrapB))
    w7 = mkwrap(wrap177, WRAP_177C8[1], WRAP_177C8[0]); builds.append((w7, wrap177))
    # v1.1 177c8 hook (32px: -64/-8)
    h7 = mkhook_xptr(hook177, -64, -8, SIG_HOOK177); builds.append((h7, hook177))

    for (cv, _), site in builds:
        if cv is None:
            log.append("  [ERR] plus d'espace cave"); return 1

    # verify + write caves
    for (cv, cave), _ in builds:
        for i in range(len(cave)):
            if struct.unpack_from("<I", buf, cv + i*4 + 0x74)[0] != 0:
                log.append(f"  [ERR] cave {cv+i*4:#x} non vide"); return 1
    for (cv, cave), _ in builds:
        for i, wd in enumerate(cave):
            struct.pack_into("<I", buf, cv + i*4 + 0x74, wd)

    # counts (right extension)
    struct.pack_into("<I", buf, cnt16,   NEW_CNT16)
    struct.pack_into("<I", buf, cnt32a,  NEW_CNT32_A)
    struct.pack_into("<I", buf, cnt32b,  NEW_CNT32_B)
    struct.pack_into("<I", buf, cnt177e, NEW_CNT32_A)   # 0xd->0x11
    struct.pack_into("<I", buf, cnt177b, NEW_CNT32_B)   # 0xd->0x11
    # hooks last (jumps to caves)
    for (cv, _), site in builds:
        struct.pack_into("<I", buf, site, J(cv))
    log.append("BG FULL prepend + wrap-fix + 177c8: [ok]")
    log.append(f"  caves utilisees: {', '.join(hex(b[0][0]) for b in builds)}")
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
