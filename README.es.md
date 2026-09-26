# SFA3 MAX — Parche widescreen 16:9 nativo (PSP)

> 🌐 [English](README.md) · [日本語](README.ja.md) · [Français](README.fr.md) · **Español** · [Português (BR)](README.pt-BR.md)

Parche widescreen **16:9 nativo (480×272)** para **Street Fighter Alpha 3 MAX** /
**Street Fighter Zero 3 Double Upper** en PSP.

La opción de pantalla interna del juego debe estar en **«Normal»** (4:3 sin estirar).
Este parche hace que el motor renderice el fondo **de forma nativa en 16:9**: el
viewport se abre a los 480 px completos y las capas de tiles del fondo se extienden con
**tiles reales del escenario** a izquierda y derecha, **manteniéndose centradas** — sin
estiramiento, sin duplicación por triple renderizado.

## Antes / después

| Original (4:3, pillarbox) | Con parche (16:9 nativo) |
|:---:|:---:|
| ![antes](images/before_4x3.png) | ![después](images/after_16x9.png) |

| | |
|---|---|
| **Versión** | **1.1** |
| **Dumps soportados** | EU `ULES-00235` (v1.01) · US `ULUS-10062` · JP `ULJM-05082` (v1.01, Zero 3 Double Upper) |
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

El parcheador se niega a escribir si algo parece incorrecto (firma ausente/duplicada), así
que nunca produce un archivo a medio parchear, y reconoce de antemano un EBOOT o una ISO ya
parcheados, que deja intactos.

---

## Instalación más fácil — cheat de PPSSPP (sin descifrar ni reempaquetar)

Hay cheats listos para usar en [`cheats/`](cheats/), uno por región. Aplican exactamente
las mismas ediciones de memoria que el parcheador, de forma continua en tiempo de
ejecución, así que **no hace falta descifrar ni reempaquetar nada** — solo coloca el
archivo y actívalo.

1. Copia `cheats/<DISC-ID>.ini` en `memstick/PSP/Cheats/` (p. ej. `ULES00235.ini`).
2. PPSSPP: **Settings → System → Enable cheats**.
3. Inicia el juego → **Pause → Cheats** → marca **«16:9 Widescreen (native, v1.1)»**.
4. Pon la opción de pantalla interna del juego en **Normal**.

> ⚠️ **Específico de versión.** Las direcciones del cheat son fijas para los dumps
> listados arriba (EU/JP **v1.01**). Una revisión distinta desplaza las direcciones — en
> ese caso usa el parcheador Python, que localiza todo por patrón y se adapta a cualquier
> revisión. (La revisión de tu dump aparece en la info del juego de PPSSPP, o como `_1.0x`
> en los nombres de los save-states.)

---

---

## Parchear una ISO directamente (sin extraer, sin UMDGen)

El **mismo script** acepta la imagen de disco y hace todo el trabajo:

```
python sfa3_ws_patternpatcher.py  JUEGO.iso  JUEGO_WS.iso
```

Recorre el sistema de archivos ISO9660 (sin ningún LBA fijo en el código), localiza
`PSP_GAME/SYSDIR/EBOOT.BIN`, lo parchea y escribe una ISO nueva; luego vuelve a abrir
esa ISO y la verifica: el EBOOT se relee exactamente como quedó parcheado y **todos los
demás archivos son idénticos byte a byte** (sha1 por archivo).

* **ISO con un EBOOT descifrado** (una ISO «DECRYPTED», o una que ya reempaquetaste):
  se parchea **en el sitio** — el parche nunca cambia el tamaño del archivo, así que no
  se mueve ni un LBA.
* **ISO original (EBOOT cifrado `~PSP`)**: tampoco hay nada que descifrar. Un UMD
  original conserva el ELF *sin cifrar* justo al lado del firmado, como
  `PSP_GAME/SYSDIR/BOOT.BIN` — byte a byte el mismo programa que el volcado descifrado
  de PPSSPP (verificado en EU, US y JP). El script recurre a él automáticamente, lo
  parchea y lo escribe en el hueco de `EBOOT.BIN`; ambos quedan parcheados
  (`--no-boot` deja `BOOT.BIN` intacto). En este juego el ELF parcheado es *más
  pequeño* que el EBOOT cifrado, así que cabe en la extensión existente y ningún LBA
  se mueve.

  Para una ISO sin un `BOOT.BIN` en claro, pasa un EBOOT descifrado:
  ```
  python sfa3_ws_patternpatcher.py JUEGO.iso JUEGO_WS.iso --eboot ULES00235_EBOOT.BIN
  ```
  (o `--decrypter "<cmd>"`, invocada como `<cmd> <entrada> <salida>`, para una
  herramienta tipo PRXDecrypter). Si entonces el resultado necesita más espacio que el
  original, la imagen se redimensiona como haría UMDGen: desplazamiento de los sectores
  siguientes y corrección de todos los LBA de los registros de directorio, de las dos
  tablas de rutas y del tamaño del volumen.
* **Entrada CSO** se lee directamente (`JUEGO.cso` → `.iso` parcheada); usa maxcso si
  quieres volver a CSO. ZSO/DAX no están soportados.
* `--list` muestra el árbol de la ISO · `--dry-run` no escribe nada · al reejecutarlo
  sobre una ISO ya parcheada simplemente lo indica.

Probado en ISOs originales **y** descifradas de las tres regiones (EU `ULES-00235`,
US `ULUS-10062`, JP `ULJM-05082`): en cada caso el EBOOT parcheado releído de la ISO
lleva exactamente las 62 palabras modificadas del cheat de esa región, y todos los demás
archivos del disco son idénticos byte a byte.

> Un EBOOT descifrado dentro de una ISO funciona sin problemas en PPSSPP; el hardware
> real/CFW sigue necesitando un EBOOT refirmado (`sign_np`). Si una ISO no lleva un
> `BOOT.BIN` en claro, el paso de descifrado es inevitable — UMDGen tampoco puede
> hacerlo; solo realiza la cirugía del sistema de archivos, que es justamente lo que
> sustituye este script.

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
| `sfa3_ws_patternpatcher.py` | el parcheador — un solo archivo, acepta una ISO/CSO **o** un EBOOT descifrado |
| `cheats/<DISC-ID>.ini` | cheats de PPSSPP listos para usar (por región, sin reempaquetar) |
| `README.md` | este archivo — guía de usuario |
| `TECHNICAL.md` | documento completo de ingeniería inversa: cada parche explicado |
| `LICENSE` | MIT (solo el código del parcheador); juego © Capcom |

---

## Herramientas utilizadas

| Herramienta | Función | Dónde |
|---|---|---|
| **Python 3** | ejecuta el parcheador (solo stdlib — sin `pip install`) | python.org |
| **PPSSPP** | volcado de descifrado del EBOOT · depuradores GE/CPU usados para la ingeniería inversa | ppsspp.org |
| **UMDGen** | reempaqueta el EBOOT parcheado en la ISO — **opcional**, `sfa3_ws_patternpatcher.py` lo hace | (herramienta ISO de Windows) |
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
