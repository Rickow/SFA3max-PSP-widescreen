# SFA3 MAX — Parche widescreen 16:9 nativo (PSP)

> 🌐 [English](README.md) · [日本語](README.ja.md) · [Français](README.fr.md) · **Español** · [Português (BR)](README.pt-BR.md)

Parche widescreen **16:9 nativo (480×272)** para **Street Fighter Alpha 3 MAX** /
**Street Fighter Zero 3 Double Upper** en PSP.

La opción de pantalla interna del juego debe estar en **«Normal»** (4:3 sin estirar).
Este parche hace que el motor renderice el fondo **de forma nativa en 16:9**: el
viewport se abre a los 480 px completos y las capas de tiles del fondo se extienden con
**tiles reales del escenario** a izquierda y derecha, **manteniéndose centradas** — sin
estiramiento, sin duplicación por triple renderizado.

| | |
|---|---|
| **Versión** | **1.1** |
| **Regiones soportadas** | EU `ULES-00235`, US `ULUS-10062`, JP `ULJM-05082` (Zero 3 Double Upper) |
| **Probado en** | PPSSPP |
| **Entrada** | un `EBOOT.BIN` **descifrado** (ELF) |
| **Método** | parcheador binario en Python puro, **pattern-scan** (sin offsets fijos) |

---

## Qué hace

* **Apertura del viewport** — ventana de render 384 → 480 px, pillarbox lateral eliminado.
* **Fondo en widescreen** — las tres rutinas de dibujo de tiles del fondo (capas de
  16 px y 32 px) reciben columnas adicionales + un desplazamiento a la izquierda, para
  que el fondo llene los 480 px **centrado**.

### Novedades en v1.1

* **Capas de decorado pintado / objetos** (templos, árboles, elementos de primer plano y
  el arte de título / menú / selección de personaje — una ruta de render aparte que el
  parche v1.0 no tocaba) ahora se extienden a 480 px en lugar de recortarse en los
  antiguos límites 4:3.
* **Corrección del desplazamiento vertical en la costura de wrap** — la v1.0 desplazaba
  las capas de tiles a la izquierda para llenar el lado ampliado, pero no ajustaba el
  disparador del rebobinado, así que la última columna / la costura de scroll leía una
  fila de tiles demasiado abajo (un desplazamiento de ~16 px hacia abajo). Las tres
  rutinas de dibujo compensan ahora el disparador y las costuras encajan exactamente.
* **Tercera rutina de tiles** (`FUN_177c8`) — la única rutina de tilemap que la v1.0
  dejaba en 4:3 ahora recibe el tratamiento widescreen completo (conteo + desplazamiento
  a la izquierda + corrección de costura).

Los sprites de los personajes, el HUD y el gameplay no se modifican y permanecen centrados.

### Limitación conocida

En los **extremos de un escenario** (donde la tilemap simplemente ya no contiene más
tiles) puede quedar un pequeño margen en esas raras posiciones de cámara. Es un límite de
*datos* del escenario original, no de código. En el centro del escenario el fondo es 16:9
completo.

---

## Inicio rápido (PPSSPP, EBOOT descifrado)

```
python sfa3_ws_patternpatcher.py  EBOOT.BIN  EBOOT_WS.BIN
```

Luego ejecuta `EBOOT_WS.BIN` (o reempaquétalo en la ISO — ver abajo) y pon la opción de
pantalla interna del juego en **Normal**.

El parcheador se niega a escribir si algo parece incorrecto (firma ausente/duplicada) y
es **idempotente** (al reejecutarlo muestra `[skip]`).

---

## Flujo completo: ISO → descifrar → parchear → reempaquetar

El EBOOT dentro de una ISO comercial está **cifrado** (cabecera `~PSP` / `PSAR`). Primero
debes descifrarlo. El recifrado **no** es necesario para PPSSPP.

### 1. Extraer y descifrar el EBOOT (PPSSPP)

PPSSPP puede volcar el EBOOT descifrado por ti:

1. **Settings → Tools → Developer tools** → activa
   **"Dump Decrypted EBOOT.BIN on game boot"**.
2. Arranca el juego una vez.
3. El archivo descifrado aparece en
   `memstick/PSP/SYSTEM/DUMP/<DISC-ID>_EBOOT.BIN`
   (p. ej. `ULES00235_EBOOT.BIN`). Cópialo.

> Como alternativa, usa **PRXDecrypter** en una PSP real/emulada, que escribe un
> `BOOT.BIN` descifrado.

### 2. Parchearlo

```
python sfa3_ws_patternpatcher.py  ULES00235_EBOOT.BIN  EBOOT_WS.BIN
```

### 3. Reempaquetar en la ISO (UMDGen)

1. Abre la ISO original en **UMDGen**.
2. Ve a `PSP_GAME/SYSDIR/EBOOT.BIN`.
3. **Clic derecho → Import / Replace file** y elige `EBOOT_WS.BIN`.
   - PPSSPP ejecuta directamente un EBOOT **descifrado** colocado en la ISO; no hace
     falta firmarlo para el emulador.
4. **File → Save As** para una ISO nueva.

> El uso en hardware real requiere un EBOOT firmado (p. ej. `sign_np`) y CFW; esta guía
> está orientada a PPSSPP.

### 4. Poner la pantalla en Normal

En el juego: **Options → Display → Normal** (no «Wide»/estirado). El widescreen ahora
proviene de tiles realmente renderizados, no de un estiramiento.

---

## Archivos

| Archivo | Propósito |
|---|---|
| `sfa3_ws_patternpatcher.py` | el parcheador (EU/US/JP, pattern-scan) |
| `README.md` | este archivo — guía de usuario |
| `TECHNICAL.md` | documento completo de ingeniería inversa: cada parche explicado |
| `LICENSE` | MIT (solo el código del parcheador); juego © Capcom |

---

## Herramientas utilizadas

| Herramienta | Función | Dónde |
|---|---|---|
| **Python 3** | ejecuta el parcheador (solo stdlib — sin `pip install`) | python.org |
| **PPSSPP** | volcado de descifrado del EBOOT · depuradores GE/CPU usados para la ingeniería inversa | ppsspp.org |
| **UMDGen** | reempaqueta el EBOOT parcheado en la ISO | (herramienta ISO de Windows) |
| **PRXDecrypter** | descifrado de EBOOT alternativo en PSP real/CFW | (homebrew PSP) |
| **sign_np** | refirma el EBOOT para hardware real (no necesario en PPSSPP) | (homebrew PSP) |

> Requisitos: **Python 3.8+**. Sin paquetes de terceros — el parcheador solo importa
> `os`, `sys`, `struct` de la biblioteca estándar.

---

## Créditos / notas

Ingeniería inversa a partir del EBOOT descifrado mediante desensamblado estático MIPS y
los depuradores GE/CPU de PPSSPP. El parche es un conjunto de ediciones de instrucciones
in situ más dos pequeños code-caves colocados en padding ejecutable existente — sin cambio
de tamaño de archivo.

Juego original © Capcom.
