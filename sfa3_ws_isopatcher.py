#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFA3 MAX - 16:9 widescreen ISO patcher (direct, no UMDGen)            v1.0
=========================================================================

Patches the game straight inside a PSP ISO: no manual EBOOT extraction and no
UMDGen repack. The widescreen edits themselves come from
`sfa3_ws_patternpatcher.py` (imported, single source of truth).

What it does
------------
1. Walks the ISO9660 filesystem (no hard-coded LBA) and locates
   `PSP_GAME/SYSDIR/EBOOT.BIN` (and `BOOT.BIN`).
2. If that EBOOT is a *decrypted* ELF -> patches it **in place**. The patch never
   changes the file size, so the ISO layout is untouched (zero-risk path).
3. If it is still *encrypted* (`~PSP` / PSAR) -> falls back to
   `PSP_GAME/SYSDIR/BOOT.BIN`, which on a retail UMD is the **same program as a
   plain ELF** (verified byte-identical to PPSSPP's decrypted dump on EU/US/JP):
   no decryption needed at all. Otherwise a decrypted EBOOT must be supplied with
   `--eboot` (PPSSPP: Developer tools -> "Dump Decrypted EBOOT.BIN") or produced by
   `--decrypter`. The patched ELF then goes into the EBOOT.BIN slot; if it needs
   more room the image is resized the way UMDGen does: following sectors shifted,
   every directory-record LBA, both path tables and the volume space size fixed.
   `BOOT.BIN` itself is patched too (in place) unless `--no-boot`.
4. Re-opens the written ISO and verifies it: EBOOT.BIN (and BOOT.BIN) read back
   exactly as patched, and **every other file is byte-identical** (sha1 per file).

Usage
-----
    python sfa3_ws_isopatcher.py  GAME.iso  [GAME_WS.iso]
    python sfa3_ws_isopatcher.py  GAME.iso  GAME_WS.iso  --eboot ULES00235_EBOOT.BIN
    python sfa3_ws_isopatcher.py  GAME.iso  GAME_WS.iso  --no-boot
    python sfa3_ws_isopatcher.py  GAME.iso  --list
    python sfa3_ws_isopatcher.py  GAME.cso  GAME_WS.iso      (CSO in -> ISO out)

Afterwards set the game's INTERNAL display option to 'Normal'.
PPSSPP runs a decrypted EBOOT inside an ISO as-is; real-hardware/CFW use still
needs a re-signed EBOOT (sign_np).
"""
import os, re, sys, struct, hashlib, shutil, subprocess, tempfile

from sfa3_ws_patternpatcher import (patch as ws_patch, SIG_PAINT_R, NEW_PAINT_R,
                                    SIG_CNT16, NEW_CNT16)


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
    if not os.path.isfile(src): raise SystemExit(f"not found: {src}")

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

        err = 0 if already_patched(buf) else ws_patch(buf, log)
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
                if ws_patch(bb, blog) == 0:
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

if __name__ == "__main__":
    main()
