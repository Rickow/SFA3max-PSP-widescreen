# Technical write-up — SFA3 MAX 16:9 widescreen patch

> 🌐 **English** · [日本語](TECHNICAL.ja.md) · [Français](TECHNICAL.fr.md) · [Español](TECHNICAL.es.md) · [Português (BR)](TECHNICAL.pt-BR.md)

Full explanation of how the patch was reverse-engineered and what every byte
edit does. All addresses below are **virtual addresses (VA)** of the decrypted
EBOOT unless stated otherwise.

## Conventions

| Term | Value |
|---|---|
| File offset of a VA | `file = VA + 0x74` (the ELF program header maps VA 0 → file 0x74) |
| Runtime load base | `0x08804000` → `runtime = VA + 0x08804000` |
| Native PSP screen | 480 × 272 (true 16:9 hardware) |
| 4:3 content width | 384 px → margins of 48 px each side (the centering offset) |
| `j`/`jal` encoding | `0x08000000 | ((target >> 2) & 0x03FFFFFF)` |

> **Relocation caveat.** Hand-injected `j`/`jal` are **not** relocated by the PSP
> loader (it only fixes up jumps present at link time). Injected jumps must
> therefore encode the **runtime** target (`VA + 0x08804000`). Getting this wrong
> produces a "Bad Execution Address → Jump to 0x00xxxxxx" crash (observed and
> fixed during development).

## Region independence (pattern-scan)

EU, US and JP share the same rendering code but at **different offsets** (JP is
~1 KB smaller; US differs from EU in ~30 % of bytes). Hard-coded addresses are
unreliable, so the patcher locates every site by a **unique instruction-byte
signature** and patches at the matched offset. Each signature was verified to
occur the expected number of times in all three EBOOTs.

---

## Part 1 — Viewport opener

The stock game renders a 384-px-wide window centered in 480, with black
pillarbox bars on the sides. Four edits open it to the full 480.

### VP1 — render-scaler width (`ori a0,zero,0x180` → `0x1E0`)

A single site loads `0x180` (384) as the render width into `a0`. Located by the
**unique preceding window** `32 00 a5 a7 24 00 a4 a7`; the next word is
`ori a0,zero,0x180` (LE `80 01 04 34`). Patch low imm byte `0x80 → 0xE0` → `0x1E0`.

### VP2 — kill the pillarbox routine (`jr ra; nop`)

The function that draws the side bars is neutralized by replacing its prologue
with `jr ra; nop` (`08 00 e0 03 00 00 00 00`). Located by the unique 12-byte
prologue signature `90 ff bd 27  60 00 b0 af  20 00 10 3c`.

### VP width — 8 call sites (`ori a2/a3,zero,0x180` → `0x1E0`)

Eight places build a GE width arg of `0x180`. The literal word `34 06 01 80`
appears **15 times**, but only 8 are the width arg. They are disambiguated by an
**8-byte window** `[ori 0x180][next instr]`, matching exactly the 8 wanted sites
(8 hits EU & US, 0 collisions with the other 7). Patch low byte `0x80 → 0xE0`.

### VP camera — 11 sites (`li t0,-192` → `-240`)

The camera left-bound table loads `-192` (`addiu t0,zero,-0xC0` = `34 08 ff 40`)
in 11 consecutive entries → patched to `-240` (`34 08 ff 10`), letting the camera
pan 48 px further left to keep content centered in the wider window.

---

## Part 2 — Background tile layers

### Architecture (found via GE + CPU debugger)

* The background is a **tilemap drawn tile-by-tile**: each tile is one `DRAW PRIM`
  quad in GE through-mode.
* Two draw routines, each shared by **all** layers of its tile size:
  * **`FUN_17268`** — 16 px tiles (sky, clouds, rocks). Draws **25 columns**.
  * **`FUN_16B28`** — 32 px tiles (temple, waterfall, foreground grass). Draws
    **13 columns × 9 rows**.
* Per-layer state struct (`s0`/`s1`): `+0x08` live X · `+0x10` working tile
  pointer · `+0x18` X stride · `+0x20` X start · `+0x22` wrap column · `+0x3E`
  row count.
* Tiles live in a **static circular buffer** (64 columns) filled once at stage
  load; scrolling just moves the read window. Empty slots = `0x00000000`, valid
  tiles carry flag `0x80000000`.
* The shared vertex emitter `FUN_1DD620` applies the **+48 px centering**
  (`addiu a3,a3,0x30`). It has **22 callers** (sprites, HUD, …) → must **not** be
  touched, or characters would shift.

25 cols × 16 px ≈ 384 px (the 4:3 content). To fill 480 → ≈ 31 columns (6 more:
3 left + 3 right), centered.

### Right extension — column-count gates

| Routine | Gate | From | To |
|---|---|---|---|
| `FUN_17268` (16 px) | `slti a0,a2,25` (`28 c4 00 19`) | 25 | **31** (`…1F`) |
| `FUN_16B28` (32 px) | `slti a3,a2,13` (`28 c7 00 0d`) | 13 | **17** (`…11`) |
| `FUN_16B28` (32 px) | `slti a0,a2,13` (`28 c4 00 0d`) | 13 | **17** (`…11`) |

Each 32 px signature occurs **twice**; only the one **inside the `FUN_16B28`
body** (nearest the row-start hook, within 0x600 bytes) is patched — the
unrelated duplicate is left intact. (Verified on JP: far duplicates at 0x17ae0 /
0x17d20 untouched.)

### Left prepend — code-caves

The loop starts at a fixed left edge and advances right, so a larger count only
grows the **right** side. To add columns on the **left** while keeping existing
tiles pixel-exact, the row-start setup is hooked and, per row:

```
Xstart -= N * stride     ; window starts N columns earlier (recenters on 480)
ptr    -= N * 4          ; tile pointer back N columns (4 bytes per column)
```

16 px: N=3 (Xstart-48, ptr-12). 32 px: N=2 (Xstart-64, ptr-8). Pointer and X
start move by matching amounts → existing tiles don't move, N fresh real tiles
appear in the left margin.

**Hook A** — `FUN_17268` row store `sh t1,0x08(s0)` (`a6 09 00 08`, unique) →
`j caveA`. `t1` = live X start here.
**Hook B** — `FUN_16B28` row store `sh t0,0x08(s1)` (`a6 28 00 08`, unique) →
`j caveB`. `t0` = live X start here.

> JP codegen emits the row-start area slightly differently; the patcher takes the
> **last** store of the matched cluster, the structurally-correct hook point
> (verified by disassembly: `t1`/`t0` = X start there in all three regions).

**Cave A** (7 words) in the executable padding hole found dynamically (a ≥56-byte
zero run in `.text`, in practice VA `0x1FF1B4`):

```
addiu t1,t1,-48      ; Xstart -= 3*16
sh    t1,0x08(s0)    ; replicate the displaced store (adjusted)
lw    t4,0x10(s0)    ; working tile pointer
addiu t4,t4,-12      ; ptr -= 3 columns
sw    t4,0x10(s0)
j     <hookA+8>      ; runtime-relocated return
nop
```

**Cave B** (7 words, right after A): same shape with `-64`/`-8`, `s1`/`t0`,
returning to `<hookB+8>`.

Caves live in **existing zero padding inside the executable segment** (the only
region proven to execute reliably). No file size change.

---

## What was tried and rejected

* **Triple-render duplication** — rejected by design (off-center, fake).
* **Wrap-pointer / streamer patching** — the tile buffer is static; the streamer
  only updates scroll fields, not tiles, so widening it gained nothing.
* **Clamp-to-edge (duplicate last valid tile on empty slots)** — corrupts menus,
  because "empty" means *transparent*, not *stage edge*; the two cannot be
  distinguished without per-layer stage-width data. Abandoned.

The shipped solution (prepend + count extension) fills the frame with **real**
tiles and is stable across menus and gameplay.

---

## Patch summary (per region, applied by signature)

| # | Patch | Signature | Edit |
|---|---|---|---|
| 1 | VP1 scaler | prewin `32 00 a5 a7 24 00 a4 a7` | `0x180→0x1E0` |
| 2 | VP2 pillarbox | `90 ff bd 27 60 00 b0 af 20 00 10 3c` | → `jr ra; nop` |
| 3 | VP width ×8 | 6 distinct 8-byte windows | `0x180→0x1E0` |
| 4 | VP camera ×11 | word `34 08 ff 40` | `→ 34 08 ff 10` |
| 5 | count 16 px | `28 c4 00 19` (unique) | `→ 28 c4 00 1f` |
| 6 | count 32 px (a3) | `28 c7 00 0d` near hookB | `→ 28 c7 00 11` |
| 7 | count 32 px (a0) | `28 c4 00 0d` near hookB | `→ 28 c4 00 11` |
| 8 | hook A + cave A | `a6 09 00 08` | `→ j caveA` + 7-word cave |
| 9 | hook B + cave B | `a6 28 00 08` | `→ j caveB` + 7-word cave |

### v1.1 additions

| # | Patch | Signature | Edit |
|---|---|---|---|
| 10 | paint cull right | `3c 07 43 c0` (`lui a3,0x43c0`=384.0f, unique) | `→ 0x43f0` (480.0f) |
| 11 | paint cull left | window `86 04 00 10 · 00 04 40 23` (unique) | `subu→addiu t0,zr,-96` |
| 12 | wrap fix draw16 | `a6 09 00 22` (`sh t1,0x22(s0)`, unique) | `→ j cave` (+3 trigger) |
| 13 | wrap fix draw32 | `a6 28 00 22` (`sh t0,0x22(s1)`, unique) | `→ j cave` (+2 trigger) |
| 14 | 177c8 hook | `a6 08 00 08` (`sh t0,0x8(s0)`, unique) | `→ j cave` (X−64 / ptr−8) |
| 15 | 177c8 wrap fix | `a6 08 00 22` (`sh t0,0x22(s0)`, unique) | `→ j cave` (+2 trigger) |
| 16 | 177c8 counts ×2 | `28 c7 00 0d` / `28 c4 00 0d` near (15) | `→ …11` (13→17) |

**Why the wrap fix (12–15).** The v1.0 hook shifts a tile layer's start left by N
columns (N=3 for 16 px, N=2 for 32 px: `ptr -= N·4`, `Xstart -= N·16`) to fill the
widened left margin, but the per-layer wrap trigger (`+0x58` seed → `+0x22`) is
*not* adjusted. The layer buffer is 64 columns row-major (stride `0x100`); at the
wrap the rewind subtracts exactly one row (`-0x100`). Because the start moved N
columns early, the rewind now lands N entries into the **previous** row, so the
columns after the seam read one tile-row up and render ~16 px **too low**. The fix
adds `+N` to the trigger so the rewind hits the row boundary exactly. Each fix is a
4-word cave: `addiu rt,rt,N ; <original sh rt,0x22(rs)> ; j site+8 ; nop`.

All patches are located by unique signatures (verified 1 occurrence on EU/US/JP,
except the two `subu`/count words which are disambiguated by a context window or by
proximity to the unique wrap store). v1.1 needs 6 code-caves (33 words total).

**Cave placement (important).** Not every zero-run in the exec image is safe: some
are runtime scratch (zeroed in the file but written at run time), and the big
end-of-segment hole is clobbered too — a cave placed there is overwritten and the
hook jumps into garbage (black screen). Only the **mid-segment code padding** is
read-only at run time. The allocator therefore anchors on the first `>=14`-word
hole scanned ascending (the exact region the in-game-validated v1.0 build used),
then allocates **only from the largest holes of that local band** (worst-fit,
big caves first), so all 6 caves land in the proven-safe padding (`0x1ff1b4`,
`0x1fef38`, `0x1feed0` on every region) and the small/scattered/end holes are
never touched.

All validated byte-level on EU, US and JP; the JP auto-output renders identically
to the in-game-confirmed manual reference (same patch logic; caves in the same
proven-safe band).

### Per-region anchors (informational; the patcher does not hard-code these)

| | EU | US | JP |
|---|---|---|---|
| hook A `sh t1,8(s0)` | `0x173FC` | `0x173FC` | `0x17464` |
| hook B `sh t0,8(s1)` | `0x16F30` | `0x16F30` | `0x16F98` |
| count 16 px | `0x1775C` | `0x1775C` | `0x177C4` |
| wrap draw16 `sh t1,0x22(s0)` | `0x1741C` | `0x1741C` | `0x17484` |
| wrap draw32 `sh t0,0x22(s1)` | `0x16F50` | `0x16F50` | `0x16FB8` |
| 177c8 hook `sh t0,0x8(s0)` | `0x17A50` | `0x17A48` | `0x17AB8` |
| 177c8 wrap `sh t0,0x22(s0)` | `0x17A70` | `0x17A70` | `0x17AD8` |
| paint cull right `lui a3,0x43c0` | — | — | `0x7978` |
| caves (v1.1, ×6) | dynamic | dynamic | dynamic |
