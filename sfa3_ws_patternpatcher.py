#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFA3 MAX - Native 16:9 widescreen patcher (PATTERN-SCAN, multi-region)  v1.1
============================================================================

One file, standard library only. Give it either a **decrypted EBOOT.BIN** or the
game's **ISO/CSO** and it does the right thing:

    python sfa3_ws_patternpatcher.py  GAME.iso     [GAME_WS.iso]    <- patch in the image
    python sfa3_ws_patternpatcher.py  EBOOT.BIN    [EBOOT_WS.BIN]   <- patch an EBOOT
    python sfa3_ws_patternpatcher.py  GAME.cso     [GAME_WS.iso]    <- CSO in, ISO out
    python sfa3_ws_patternpatcher.py  GAME.iso     --list           <- show the ISO tree

Locates everything by INSTRUCTION PATTERNS (not fixed addresses), so it works
on EU, US and JP decrypted EBOOTs regardless of build offsets.

v1.0 : viewport opener + BG FULL widescreen prepend (3 tilemap drawers hook).
v1.1 : + painted-decor cull widen (temple/trees/menus, the "8th pipeline"),
       + wrap-seam vertical-shift fix on all 3 tilemap drawers,
       + 3rd tilemap drawer (FUN_177c8) full treatment (count+hook+wrapfix).
       + direct ISO/CSO patching (no EBOOT extraction, no UMDGen).

ISO mode
--------
Walks the ISO9660 filesystem (PVD at LBA 16, directory tree, no hard-coded LBA),
finds `PSP_GAME/SYSDIR/EBOOT.BIN`, patches it and writes a NEW image - the source
is only ever read. The result is then re-opened and verified: the EBOOT reads back
exactly as patched and every other file is checked byte-identical (sha1 per file).

* EBOOT already a decrypted ELF -> patched in place; the patch never changes the
  file size, so not a single LBA moves.
* EBOOT still encrypted (`~PSP`) -> falls back to `PSP_GAME/SYSDIR/BOOT.BIN`, which
  on a retail UMD is the same program as a plain ELF (verified byte-identical to
  PPSSPP's decrypted dump on EU/US/JP, which only adds a 344-byte signature trailer
  outside the loadable image): nothing needs decrypting. The patched ELF goes into
  the EBOOT.BIN slot, and BOOT.BIN is patched too unless `--no-boot`.
* No plain BOOT.BIN -> supply a decrypted EBOOT with `--eboot`, or a PRXDecrypter
  style tool with `--decrypter "<cmd>"` (called as `<cmd> <in> <out>`). If the
  replacement needs more room, the image is resized the way UMDGen does: following
  sectors shifted, every directory-record LBA, both path tables and the volume
  space size fixed.
* `--dry-run` writes nothing. Re-run on an already-patched image and it says so.

Conventions: EBOOT image base VA0 -> file 0x74. Runtime load base 0x08804000
(hand-injected jumps use runtime targets, since the loader does not relocate
them). After patching, set the game's INTERNAL display option to 'Normal'.
PPSSPP runs a decrypted EBOOT inside an ISO as-is; real hardware/CFW still needs a
re-signed EBOOT (sign_np).
"""
import os, re, sys, struct, hashlib, shutil, subprocess, tempfile
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
    """Allocate caves from the LARGEST holes first (worst-fit). Small scattered
    zero-runs in the exec image are NOT reliably safe at runtime (some are
    runtime scratch and get clobbered -> jump into garbage -> black screen).
    The big padding bands (the same ones the validated manual build used) are
    the proven-safe code padding, so we always pull from the biggest hole that
    fits and keep the tiny risky holes untouched."""
    def __init__(self, holes): self.holes = [list(h) for h in holes]
    def alloc(self, n):
        cand = [h for h in self.holes if h[1] >= n]
        if not cand: return None
        h = max(cand, key=lambda x: x[1])   # biggest hole that fits
        va = h[0]; h[0] += n*4; h[1] -= n; return va

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
    # The validated v1.0 build placed its cave in the FIRST big (>=14-word) zero
    # hole scanned ascending from the start: that is the proven-safe mid-segment
    # code-padding band (NOT the big end-of-segment hole, which is runtime
    # scratch and crashes). We anchor on that hole and only allocate from the
    # local padding band around it, biggest-hole-first (see CaveAlloc).
    holes = find_exec_zero_holes(buf, 4)
    anchor = next((h for h in holes if h[1] >= 14), None)
    if anchor is None:
        log.append("  [ERR] pas de banc de padding (>=14 mots)"); return 1
    lo = anchor[0] - 0x800
    hi = anchor[0] + anchor[1]*4 + 0x100
    band = [h for h in holes if lo <= h[0] < hi]
    # Use only the LARGEST holes of the band (the real padding bands, the ones the
    # validated build used) until we have >=33 words; this skips the tiny scattered
    # zero-runs that are not reliably safe at runtime.
    NEED = 33
    chosen, acc = [], 0
    for h in sorted(band, key=lambda x: -x[1]):
        chosen.append(h); acc += h[1]
        if acc >= NEED: break
    if acc < NEED:
        log.append(f"  [ERR] banc de caves trop petit ({acc} mots, besoin {NEED})"); return 1
    alloc = CaveAlloc(chosen)
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

    builds = []   # ((cave_va, cave_words), hook_site_off)
    # Allocate the 7-word hook caves FIRST (constrained), then the 4-word wrap
    # caves, so the big caves land in the big safe padding bands.
    # v1.0 hooks (Xstart-=48/ptr-=12 for 16px; Xstart-=64/ptr-=8 for 32px)
    cA = mkhook_xptr(hookA, -48, -12, SIG_HOOKA); builds.append((cA, hookA))
    cB = mkhook_xptr(hookB, -64,  -8, SIG_HOOKB); builds.append((cB, hookB))
    # v1.1 177c8 hook (32px: -64/-8)
    h7 = mkhook_xptr(hook177, -64, -8, SIG_HOOK177); builds.append((h7, hook177))
    # v1.1 wrap fixes (4-word caves)
    wA = mkwrap(wrapA, WRAP_DRAW16[1], WRAP_DRAW16[0]); builds.append((wA, wrapA))
    wB = mkwrap(wrapB, WRAP_DRAW32[1], WRAP_DRAW32[0]); builds.append((wB, wrapB))
    w7 = mkwrap(wrap177, WRAP_177C8[1], WRAP_177C8[0]); builds.append((w7, wrap177))

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


def already_patched(buf):
    """True when this EBOOT already carries the widescreen patch. Checked here
    rather than inside the patcher, which aborts (safely, without writing) when
    its signatures are gone."""
    w = lambda x: struct.pack("<I", x)
    return (w(SIG_PAINT_R) not in buf and w(NEW_PAINT_R) in buf
            and w(SIG_CNT16) not in buf and w(NEW_CNT16) in buf)

SECTOR = 2048
PVD_OFF = 16 * SECTOR          # first volume descriptor: LBA 16

# ---------------------------------------------------------------------------
# ISO9660 access, on the file (an ISO can be 1.8 GB: never slurp it in RAM)
# ---------------------------------------------------------------------------
class DirRec:
    __slots__ = ("rec_off", "lba", "size", "flags", "name", "path")
    def __init__(self, rec_off, lba, size, flags, name, path):
        self.rec_off, self.lba, self.size = rec_off, lba, size
        self.flags, self.name, self.path = flags, name, path
    @property
    def is_dir(self): return bool(self.flags & 0x02)
    @property
    def offset(self): return self.lba * SECTOR
    @property
    def sectors(self): return (self.size + SECTOR - 1) // SECTOR

def open_iso(path, writable=False):
    """Iso() with a readable message instead of a traceback."""
    try:
        return Iso(path, writable)
    except ValueError as e:
        raise SystemExit(f"{os.path.basename(path)}: {e}\n"
                         "Expected a PSP ISO (or a CSO). A raw EBOOT.BIN goes to "
                         "sfa3_ws_patternpatcher.py instead.")


class Iso:
    def __init__(self, path, writable=False):
        self.path = path
        self.f = open(path, "r+b" if writable else "rb")
        if self.rd(PVD_OFF + 1, 5) != b"CD001":
            raise ValueError("not an ISO9660 image (no CD001 at LBA 16)")
        if self.u16(PVD_OFF + 128) != SECTOR:
            raise ValueError("logical block size != 2048")

    def close(self): self.f.close()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    def rd(self, off, n):
        self.f.seek(off); return self.f.read(n)
    def wr(self, off, data):
        self.f.seek(off); self.f.write(data)
    def u16(self, off): return struct.unpack("<H", self.rd(off, 2))[0]
    def u32(self, off): return struct.unpack("<I", self.rd(off, 4))[0]
    def u32be(self, off): return struct.unpack(">I", self.rd(off, 4))[0]
    def put_both(self, off, val):
        """ISO9660 stores most numbers twice: LE then BE."""
        self.wr(off, struct.pack("<I", val) + struct.pack(">I", val))

    # -- volume fields --------------------------------------------------------
    @property
    def volume_sectors(self): return self.u32(PVD_OFF + 80)
    @property
    def path_table_size(self): return self.u32(PVD_OFF + 132)
    def path_table_lbas(self):
        """(lba, big_endian) for the up-to-4 path tables: L, L-opt, M, M-opt."""
        out = []
        for i in range(4):
            off = PVD_OFF + 140 + 4 * i
            be = i >= 2
            lba = self.u32be(off) if be else self.u32(off)
            if lba: out.append((off, lba, be))
        return out
    def root(self):
        return self.parse_rec(PVD_OFF + 156, "")

    # -- directory records ---------------------------------------------------
    def parse_rec(self, off, parent_path):
        raw = self.rd(off, 33)
        ln = raw[0]
        if ln == 0: return None
        lba, size = struct.unpack_from("<I", raw, 2)[0], struct.unpack_from("<I", raw, 10)[0]
        flags, nlen = raw[25], raw[32]
        name = self.rd(off + 33, nlen)
        if nlen == 1 and name in (b"\x00", b"\x01"):
            disp = "." if name == b"\x00" else ".."
        else:
            disp = name.split(b";")[0].decode("ascii", "replace")
        path = parent_path + "/" + disp if disp not in (".", "..") else parent_path
        return DirRec(off, lba, size, flags, disp, path)

    def listdir(self, rec):
        """Direct children of a directory record (skips '.' and '..')."""
        out = []
        for s in range(rec.sectors):
            base = rec.offset + s * SECTOR
            pos = 0
            limit = min(SECTOR, rec.size - s * SECTOR)
            while pos < limit:
                ln = self.rd(base + pos, 1)
                if not ln or ln[0] == 0: break
                r = self.parse_rec(base + pos, rec.path)
                if r and r.name not in (".", ".."): out.append(r)
                pos += ln[0]
        return out

    def walk(self, rec=None):
        """Every record under `rec`, directories included, depth-first."""
        if rec is None: rec = self.root()
        for child in self.listdir(rec):
            yield child
            if child.is_dir:
                yield from self.walk(child)

    def find(self, path):
        """Look up '/PSP_GAME/SYSDIR/EBOOT.BIN' (case-insensitive)."""
        cur = self.root()
        for part in [p for p in path.split("/") if p]:
            nxt = next((c for c in self.listdir(cur) if c.name.upper() == part.upper()), None)
            if nxt is None: return None
            cur = nxt
        return cur

    def read_file(self, rec):
        return self.rd(rec.offset, rec.size)

    def hash_files(self):
        """{path: (size, sha1)} for every file, read straight from the image."""
        out = {}
        for r in self.walk():
            if r.is_dir: continue
            h = hashlib.sha1()
            left, off = r.size, r.offset
            while left > 0:
                chunk = self.rd(off, min(1 << 20, left))
                if not chunk: break
                h.update(chunk); off += len(chunk); left -= len(chunk)
            out[r.path] = (r.size, h.hexdigest())
        return out

    # -- the UMDGen-style resize --------------------------------------------
    def relocate_after(self, file_lba, rec_off, diff):
        """After splicing `diff` sectors at `file_lba`, fix every stored LBA that
        points past it: the whole directory tree, both path tables, and the
        volume space size. Same rules as UMD-REPLACE/UMDGen."""
        # the root record lives in the PVD, outside the tree walk below
        root_lba = self.u32(PVD_OFF + 156 + 2)
        if root_lba > file_lba:
            self.put_both(PVD_OFF + 156 + 2, root_lba + diff)
        # directory tree (LE at +2, BE at +6)
        stack = [self.root()]
        seen = set()
        while stack:
            d = stack.pop()
            if d.offset in seen: continue
            seen.add(d.offset)
            for s in range(d.sectors):
                base = d.offset + s * SECTOR
                pos, limit = 0, min(SECTOR, d.size - s * SECTOR)
                while pos < limit:
                    off = base + pos
                    ln = self.rd(off, 1)
                    if not ln or ln[0] == 0: break
                    lba = self.u32(off + 2)
                    # '>' only: the replaced file keeps its own LBA. Equal LBAs
                    # (0-byte files sharing an extent) shift only if they sit
                    # after the replaced record.
                    if lba > file_lba or (lba == file_lba and off > rec_off):
                        self.put_both(off + 2, lba + diff)
                        lba += diff
                    nlen = self.rd(off + 32, 1)[0]
                    nm = self.rd(off + 33, nlen)
                    is_dot = nlen == 1 and nm in (b"\x00", b"\x01")
                    if (self.rd(off + 25, 1)[0] & 0x02) and not is_dot:
                        stack.append(DirRec(off, lba, self.u32(off + 10), 0x02, "", ""))
                    pos += ln[0]
        # path tables (dirs only; LBA endianness follows the table)
        for _, tbl_lba, be in self.path_table_lbas():
            pos, end = 0, self.path_table_size
            base = tbl_lba * SECTOR
            while pos < end:
                nlen = self.rd(base + pos, 1)
                if not nlen or nlen[0] == 0: break
                n = nlen[0]
                off = base + pos + 2
                lba = self.u32be(off) if be else self.u32(off)
                if lba > file_lba:
                    self.wr(off, struct.pack(">I" if be else "<I", lba + diff))
                pos += 8 + n + (n & 1)
        # volume space size
        self.put_both(PVD_OFF + 80, self.volume_sectors + diff)

# ---------------------------------------------------------------------------
# CSO (CISO) reader -> plain ISO
# ---------------------------------------------------------------------------
def cso_to_iso(src, dst, log):
    import zlib
    with open(src, "rb") as f:
        hdr = f.read(0x18)
        magic = hdr[:4]
        if magic == b"ZISO":
            raise SystemExit("ZSO (lz4) not supported: convert to ISO with maxcso first.")
        if magic != b"CISO":
            raise SystemExit(f"unknown compressed format {magic!r}: convert to ISO first.")
        hdr_size, total, block, ver, shift = struct.unpack_from("<IQIBB", hdr, 4)
        nblocks = (total + block - 1) // block
        f.seek(hdr_size if hdr_size >= 0x18 else 0x18)
        idx = struct.unpack(f"<{nblocks+1}I", f.read(4 * (nblocks + 1)))
        log.append(f"CSO: {total/1048576:.1f} MB, block {block}, {nblocks} blocks -> decompressing")
        with open(dst, "wb") as o:
            for i in range(nblocks):
                pos, nxt = idx[i], idx[i + 1]
                plain = pos & 0x80000000
                start = (pos & 0x7FFFFFFF) << shift
                end = (nxt & 0x7FFFFFFF) << shift
                f.seek(start)
                raw = f.read(max(end - start, 1))
                o.write(raw[:block] if plain else zlib.decompress(raw, -15, block))
            o.truncate(total)
    return dst

# ---------------------------------------------------------------------------
def sha1_bytes(b): return hashlib.sha1(b).hexdigest()

def decrypt_with(cmd, src, workdir, log):
    """Run an external decrypter (pspdecrypt-like): <cmd> <in> <out>."""
    out = os.path.join(workdir, "EBOOT_DEC.BIN")
    argv = cmd.split() + [src, out]
    log.append(f"decrypter: {' '.join(argv)}")
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(out):
        raise SystemExit(f"decrypter failed (rc={r.returncode}):\n{r.stdout}\n{r.stderr}")
    return out

def is_iso9660(path):
    """CD001 at LBA 16 - cheap enough to sniff before opening properly."""
    try:
        with open(path, "rb") as f:
            f.seek(PVD_OFF + 1)
            return f.read(5) == b"CD001"
    except OSError:
        return False

# ----------------------------------------------------------------------------
# EBOOT mode
# ----------------------------------------------------------------------------
def run_eboot(src, dst):
    with open(src, "rb") as f: buf = bytearray(f.read())
    if already_patched(buf):
        print("Deja patche (les signatures BG/cull ont laisse place aux valeurs patchees):"
              " [skip]\nAucune ecriture.")
        return
    log = []
    err = patch(buf, log)
    print("\n".join(log))
    if err: print("\nABANDON."); sys.exit(3)
    with open(dst, "wb") as f: f.write(buf)
    print(f"\nOK -> {dst}")
    print("Regle l'affichage INTERNE du jeu sur 'Normal'.")


# ----------------------------------------------------------------------------
# ISO/CSO mode
# ----------------------------------------------------------------------------
def run_iso(src, out, opt_eboot, opt_decrypter, do_list, dry, do_boot):
    log = []
    tmpdir = tempfile.mkdtemp(prefix="sfa3ws_")
    try:
        # --- CSO/ZSO in -> work on a plain ISO ------------------------------
        work_src = src
        if open(src, "rb").read(4) in (b"CISO", b"ZISO"):
            work_src = cso_to_iso(src, os.path.join(tmpdir, "in.iso"), log)
            print("\n".join(log)); log = []

        if do_list:
            with open_iso(work_src) as iso:
                print(f"volume: {iso.volume_sectors} sectors ({iso.volume_sectors*SECTOR/1048576:.1f} MB)")
                for r in iso.walk():
                    kind = "DIR " if r.is_dir else "    "
                    print(f"{kind}LBA {r.lba:<8} {r.size:>12}  {r.path}")
            return

        if out is None:
            base, _ = os.path.splitext(src)
            out = base + "_WS.iso"
        if os.path.abspath(out) == os.path.abspath(src):
            raise SystemExit("refusing to overwrite the source ISO: give a different output path")

        # --- inspect the source ISO -----------------------------------------
        with open_iso(work_src) as iso:
            eb = iso.find("/PSP_GAME/SYSDIR/EBOOT.BIN")
            bt = iso.find("/PSP_GAME/SYSDIR/BOOT.BIN")
            if eb is None:
                raise SystemExit("PSP_GAME/SYSDIR/EBOOT.BIN not found: is this a PSP ISO?")
            head = iso.rd(eb.offset, 4)
            log.append(f"EBOOT.BIN  LBA {eb.lba} @ {eb.offset:#x}  {eb.size} bytes  magic {head!r}")
            if bt is not None:
                log.append(f"BOOT.BIN   LBA {bt.lba} @ {bt.offset:#x}  {bt.size} bytes  "
                           f"magic {iso.rd(bt.offset,4)!r}")
            sfo = iso.find("/PSP_GAME/PARAM.SFO")
            if sfo is not None:
                raw = iso.read_file(sfo)
                m = re.search(rb"(UL[EUJ][SMA]\d{5}|NP[A-Z]{2}\d{5})", raw)
                log.append("disc id: " + (m.group(1).decode() if m else "unknown"))
            is_elf = head == b"\x7fELF"
            src_hashes = iso.hash_files()
            src_eboot = iso.read_file(eb)
            src_boot = iso.read_file(bt) if bt is not None else None
        print("\n".join(log)); log = []

        # --- build the patched EBOOT ----------------------------------------
        if is_elf:
            if already_patched(src_eboot) and (src_boot is None or already_patched(src_boot)):
                print("\nEBOOT already carries the widescreen patch: nothing to do.")
                return
            buf = bytearray(src_eboot)
        elif opt_eboot is None and opt_decrypter is None and src_boot is not None \
                and src_boot[:4] == b"\x7fELF":
            # A retail UMD keeps the unencrypted ELF next to the signed EBOOT: on
            # EU/US/JP it is byte-identical to PPSSPP's decrypted dump (minus a
            # 344-byte signature trailer outside the loadable image), so the ISO
            # carries everything we need and nothing has to be decrypted.
            log.append("EBOOT.BIN is encrypted -> using SYSDIR/BOOT.BIN (plain ELF, same program)")
            buf = bytearray(src_boot)
        else:
            log.append("EBOOT is ENCRYPTED (retail). A decrypted ELF is required.")
            dec = opt_eboot
            if dec is None and opt_decrypter:
                enc = os.path.join(tmpdir, "EBOOT_ENC.BIN")
                open(enc, "wb").write(src_eboot)
                dec = decrypt_with(opt_decrypter, enc, tmpdir, log)
            if dec is None:
                print("\n".join(log))
                raise SystemExit(
                    "\nNo decrypted EBOOT available. Two ways:\n"
                    "  * PPSSPP: Settings > Tools > Developer tools > 'Dump Decrypted EBOOT.BIN\n"
                    "    on game boot', boot the game once, then pass\n"
                    "      --eboot memstick/PSP/SYSTEM/DUMP/<DISC-ID>_EBOOT.BIN\n"
                    "  * or --decrypter \"<cmd>\" with a PRXDecrypter-style tool taking <in> <out>.\n"
                    "This ISO has no plain-ELF SYSDIR/BOOT.BIN to fall back on, and UMDGen\n"
                    "cannot decrypt either: no tool patches such an EBOOT without this step.")
            buf = bytearray(open(dec, "rb").read())
            if buf[:4] != b"\x7fELF":
                raise SystemExit(f"{dec} is not a decrypted ELF")
            if already_patched(buf):
                log.append(f"{dec} is already patched: inserting it as-is")
            log.append(f"decrypted EBOOT: {dec} ({len(buf)} bytes)")

        err = 0 if already_patched(buf) else patch(buf, log)
        print("\n".join(log)); log = []
        if err:
            raise SystemExit("\npatcher refused -> ISO untouched.")
        patched = bytes(buf)
        if is_elf and patched == src_eboot:
            print("\nEBOOT already patched and identical: nothing to do.")
            return
        print(f"\npatched EBOOT: {len(patched)} bytes  sha1 {sha1_bytes(patched)}")

        # BOOT.BIN holds the same program on a retail UMD: patch it too, so both
        # slots agree whatever the loader picks. Always an in-place, same-size write.
        patched_boot = None
        if do_boot and src_boot is not None and src_boot[:4] == b"\x7fELF":
            if already_patched(src_boot):
                print("BOOT.BIN: already patched")
            elif src_boot == buf[:len(src_boot)]:
                patched_boot = patched[:len(src_boot)]   # same bytes, already done
            else:
                bb = bytearray(src_boot)
                blog = []
                if patch(bb, blog) == 0:
                    patched_boot = bytes(bb)
                else:
                    print("BOOT.BIN: patcher refused -> left as-is")
            if patched_boot is not None:
                print(f"patched BOOT.BIN: {len(patched_boot)} bytes  sha1 {sha1_bytes(patched_boot)}")
        if dry:
            print("--dry-run: no ISO written."); return

        # --- write the ISO ---------------------------------------------------
        same_extent = len(patched) <= eb.sectors * SECTOR
        if len(patched) == eb.size:
            print(f"writing {out} (in-place, layout untouched)")
            shutil.copyfile(work_src, out)
            with open_iso(out, writable=True) as iso:
                iso.wr(eb.offset, patched)
        elif same_extent:
            print(f"writing {out} (fits the existing extent, size field updated)")
            shutil.copyfile(work_src, out)
            with open_iso(out, writable=True) as iso:
                pad = eb.sectors * SECTOR - len(patched)
                iso.wr(eb.offset, patched + b"\x00" * pad)
                iso.put_both(eb.rec_off + 10, len(patched))
        else:
            new_sectors = (len(patched) + SECTOR - 1) // SECTOR
            diff = new_sectors - eb.sectors
            print(f"writing {out} (resize: {eb.sectors} -> {new_sectors} sectors, {diff:+d})")
            tail_at = eb.offset + eb.sectors * SECTOR
            with open(work_src, "rb") as i, open(out, "wb") as o:
                left = eb.offset
                while left:                       # head
                    c = i.read(min(1 << 22, left)); o.write(c); left -= len(c)
                o.write(patched)
                o.write(b"\x00" * (new_sectors * SECTOR - len(patched)))
                i.seek(tail_at)
                while True:                       # tail
                    c = i.read(1 << 22)
                    if not c: break
                    o.write(c)
            with open_iso(out, writable=True) as iso:
                iso.put_both(eb.rec_off + 10, len(patched))
                iso.relocate_after(eb.lba, eb.rec_off, diff)

        if patched_boot is not None:
            with open_iso(out, writable=True) as iso:
                bt2 = iso.find("/PSP_GAME/SYSDIR/BOOT.BIN")
                iso.wr(bt2.offset, patched_boot)

        # --- verify the written ISO ------------------------------------------
        print("verifying...")
        with open_iso(out) as iso:
            eb2 = iso.find("/PSP_GAME/SYSDIR/EBOOT.BIN")
            got = iso.read_file(eb2)
            if got != patched:
                raise SystemExit(f"  [ERR] EBOOT read-back differs (size {eb2.size} vs {len(patched)})")
            print(f"  EBOOT.BIN: LBA {eb2.lba}, {eb2.size} bytes, sha1 matches")
            if patched_boot is not None:
                bt2 = iso.find("/PSP_GAME/SYSDIR/BOOT.BIN")
                if iso.read_file(bt2) != patched_boot:
                    raise SystemExit("  [ERR] BOOT.BIN read-back differs")
                print(f"  BOOT.BIN:  LBA {bt2.lba}, {bt2.size} bytes, sha1 matches")
            out_hashes = iso.hash_files()
            bad = []
            for p, (sz, h) in src_hashes.items():
                if p.upper() == "/PSP_GAME/SYSDIR/EBOOT.BIN": continue
                if patched_boot is not None and p.upper() == "/PSP_GAME/SYSDIR/BOOT.BIN": continue
                if p not in out_hashes: bad.append(f"missing {p}")
                elif out_hashes[p] != (sz, h): bad.append(f"changed {p}")
            extra = set(out_hashes) - set(src_hashes)
            if bad or extra:
                raise SystemExit("  [ERR] other files altered: " + ", ".join(bad + [f"new {x}" for x in extra]))
            skipped = 1 + (1 if patched_boot is not None else 0)
            print(f"  {len(out_hashes)-skipped} other files: byte-identical")
            print(f"  volume: {iso.volume_sectors} sectors, image {os.path.getsize(out)} bytes "
                  f"({os.path.getsize(out)//SECTOR} sectors)")
        print(f"\nOK -> {out}")
        print("Set the game's INTERNAL display option to 'Normal'.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__); sys.exit(1)
    src = args.pop(0)
    opt_eboot = opt_decrypter = None
    do_list = dry = False
    do_boot = True
    out = None
    while args:
        a = args.pop(0)
        if a == "--eboot": opt_eboot = args.pop(0)
        elif a == "--decrypter": opt_decrypter = args.pop(0)
        elif a == "--list": do_list = True
        elif a == "--dry-run": dry = True
        elif a == "--no-boot": do_boot = False
        elif a.startswith("-"): raise SystemExit(f"unknown option {a}")
        else: out = a
    if not os.path.isfile(src): raise SystemExit(f"Introuvable: {src}")

    with open(src, "rb") as f: head = f.read(4)
    if head == b"\x7fELF":
        if do_list: raise SystemExit("--list only applies to an ISO/CSO")
        if dry: raise SystemExit("--dry-run only applies to an ISO/CSO")
        run_eboot(src, out or os.path.splitext(src)[0] + "_WS.BIN")
    elif head in (b"CISO", b"ZISO") or is_iso9660(src):
        run_iso(src, out, opt_eboot, opt_decrypter, do_list, dry, do_boot)
    else:
        raise SystemExit(
            f"{os.path.basename(src)}: neither a decrypted EBOOT (ELF), an ISO nor a CSO.\n"
            "An encrypted EBOOT (~PSP) must be decrypted first - or just pass the ISO,\n"
            "which usually carries the plain ELF as PSP_GAME/SYSDIR/BOOT.BIN.")


if __name__ == "__main__":
    main()
