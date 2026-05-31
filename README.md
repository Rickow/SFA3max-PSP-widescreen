# SFA3 MAX — Native 16:9 Widescreen Patch (PSP)

Native **16:9 (480×272)** widescreen patch for **Street Fighter Alpha 3 MAX** /
**Street Fighter Zero 3 Double Upper** on PSP.

The game's internal display option must be set to **"Normal"** (un-stretched 4:3).
This patch makes the engine render the background **natively in 16:9**: the
viewport is opened to the full 480 px and the background tile layers are extended
with **real stage tiles** on the left and right, **kept centered** — no stretching,
no triple-render duplication.

## Before / after

| Stock (4:3, pillarbox) | Patched (native 16:9) |
|:---:|:---:|
| ![before](images/before_4x3.png) | ![after](images/after_16x9.png) |

| | |
|---|---|
| **Supported regions** | EU `ULES-00235`, US `ULUS-10062`, JP `ULJM-05193` (Double Upper) |
| **Tested on** | PPSSPP |
| **Input** | a **decrypted** `EBOOT.BIN` (ELF) |
| **Method** | pure-Python binary patcher, **pattern-scan** (no hard-coded offsets) |

---

## What it does

* **Viewport opener** — render window 384 → 480 px, side pillarbox removed.
* **Background widescreen** — both background draw routines (16 px and 32 px tile
  layers) get extra columns: 3 on the left + extension on the right (16 px),
  2 + extension (32 px), so the background fills the whole 480 px **centered**.

The character sprites, HUD and gameplay are untouched and stay centered.

### Known limitation

At the **extreme edges of a stage** (where the tilemap simply contains no more
tiles) a small margin can remain in those rare camera positions. This is a
*data* limit of the original stage, not a code limit. Mid-stage the background
is full 16:9.

---

## Quick start (PPSSPP, decrypted EBOOT)

```
python sfa3_ws_patternpatcher.py  EBOOT.BIN  EBOOT_WS.BIN
```

Then run `EBOOT_WS.BIN` (or repack it into the ISO — see below) and set the
game's internal display option to **Normal**.

The patcher refuses to write if anything looks wrong (missing/duplicate
signature), and is **idempotent** (re-running prints `[skip]`).

---

## Full workflow: ISO → decrypt → patch → repack

The EBOOT inside a retail ISO is **encrypted** (`~PSP` / `PSAR` header). You must
decrypt it first. Re-encryption is **not** required for PPSSPP.

### 1. Extract & decrypt the EBOOT (PPSSPP)

PPSSPP can dump the decrypted EBOOT for you:

1. **Settings → Tools → Developer tools** → enable
   **"Dump Decrypted EBOOT.BIN on game boot"**.
2. Boot the game once.
3. The decrypted file appears in
   `memstick/PSP/SYSTEM/DUMP/<DISC-ID>_EBOOT.BIN`
   (e.g. `ULES00235_EBOOT.BIN`). Copy it out.

> Alternatively use **PRXDecrypter** on a real/emulated PSP, which writes a
> decrypted `BOOT.BIN`.

### 2. Patch it

```
python sfa3_ws_patternpatcher.py  ULES00235_EBOOT.BIN  EBOOT_WS.BIN
```

### 3. Repack into the ISO (UMDGen)

1. Open the original ISO in **UMDGen**.
2. Navigate to `PSP_GAME/SYSDIR/EBOOT.BIN`.
3. **Right-click → Import / Replace file** and select `EBOOT_WS.BIN`.
   - PPSSPP runs a **decrypted** EBOOT placed in the ISO directly; no signing
     needed for emulator use.
4. **File → Save As** a new ISO.

> Real-hardware use needs a signed EBOOT (e.g. `sign_np`) and CFW; this guide
> targets PPSSPP.

### 4. Set display to Normal

In-game: **Options → Display → Normal** (not "Wide"/stretched). The widescreen
now comes from real rendered tiles, not stretching.

---

## Files

| File | Purpose |
|---|---|
| `sfa3_ws_patternpatcher.py` | the patcher (EU/US/JP, pattern-scan) |
| `README.md` | this file — user guide |
| `TECHNICAL.md` | full reverse-engineering write-up: every patch explained |
| `LICENSE` | MIT (patcher code only); game © Capcom |

---

## Tools used

| Tool | Role | Where |
|---|---|---|
| **Python 3** | runs the patcher (stdlib only — no `pip install`) | python.org |
| **PPSSPP** | EBOOT decryption dump · GE/CPU debuggers used for the reverse-engineering | ppsspp.org |
| **UMDGen** | repack the patched EBOOT into the ISO | (Windows ISO tool) |
| **PRXDecrypter** | alternative EBOOT decryption on real/CFW PSP | (PSP homebrew) |
| **sign_np** | re-sign EBOOT for real-hardware use (not needed for PPSSPP) | (PSP homebrew) |

> Requirements: **Python 3.8+**. No third-party packages — the patcher imports
> only `os`, `sys`, `struct` from the standard library.

---

## Credits / notes

Reverse-engineered from the decrypted EBOOT via static MIPS disassembly and
PPSSPP's GE/CPU debuggers. The patch is a set of in-place instruction edits plus
two small code-caves placed in existing executable padding — no file size change.

Original game © Capcom.
