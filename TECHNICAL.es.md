# Documento técnico — parche widescreen 16:9 SFA3 MAX

> 🌐 [English](TECHNICAL.md) · [日本語](TECHNICAL.ja.md) · [Français](TECHNICAL.fr.md) · **Español** · [Português (BR)](TECHNICAL.pt-BR.md)

Explicación completa de cómo se hizo la ingeniería inversa del parche y de qué hace cada
edición de bytes. Salvo indicación contraria, todas las direcciones de abajo son
**direcciones virtuales (VA)** del EBOOT descifrado.

## Convenciones

| Término | Valor |
|---|---|
| Offset de archivo de una VA | `file = VA + 0x74` (la cabecera de programa ELF mapea VA 0 → file 0x74) |
| Base de carga en runtime | `0x08804000` → `runtime = VA + 0x08804000` |
| Pantalla nativa de PSP | 480 × 272 (16:9 real por hardware) |
| Ancho de contenido 4:3 | 384 px → márgenes de 48 px a cada lado (el offset de centrado) |
| Codificación `j`/`jal` | `0x08000000 | ((target >> 2) & 0x03FFFFFF)` |

> **Advertencia de relocalización.** Los `j`/`jal` inyectados a mano **no** son relocados
> por el loader de PSP (solo corrige los saltos presentes al momento del enlace). Por tanto
> los saltos inyectados deben codificar el objetivo en **runtime** (`VA + 0x08804000`).
> Equivocarse aquí produce un fallo «Bad Execution Address → Jump to 0x00xxxxxx» (observado
> y corregido durante el desarrollo).

## Independencia de región (pattern-scan)

EU, US y JP comparten el mismo código de render pero en **offsets distintos** (JP es ~1 KB
más pequeño; US difiere de EU en ~30 % de los bytes). Las direcciones fijas no son fiables,
así que el parcheador localiza cada sitio por una **firma de bytes de instrucción única** y
parchea en el offset encontrado. Cada firma se verificó que aparece el número esperado de
veces en los tres EBOOT.

---

## Parte 1 — Apertura del viewport

El juego de origen renderiza una ventana de 384 px de ancho centrada en 480, con barras
negras (pillarbox) a los lados. Cuatro ediciones la abren al 480 completo.

### VP1 — ancho del escalador de render (`ori a0,zero,0x180` → `0x1E0`)

Un único sitio carga `0x180` (384) como ancho de render en `a0`. Localizado por la
**ventana previa única** `32 00 a5 a7 24 00 a4 a7`; la siguiente palabra es
`ori a0,zero,0x180` (LE `80 01 04 34`). Parche del byte bajo del inmediato `0x80 → 0xE0`
→ `0x1E0`.

### VP2 — anular la rutina del pillarbox (`jr ra; nop`)

La función que dibuja las barras laterales se anula reemplazando su prólogo por
`jr ra; nop` (`08 00 e0 03 00 00 00 00`). Localizada por la firma de prólogo única de
12 bytes `90 ff bd 27  60 00 b0 af  20 00 10 3c`.

### VP ancho — 8 sitios de llamada (`ori a2/a3,zero,0x180` → `0x1E0`)

Ocho lugares construyen un argumento de ancho GE de `0x180`. La palabra literal
`34 06 01 80` aparece **15 veces**, pero solo 8 son el argumento de ancho. Se desambiguan
con una **ventana de 8 bytes** `[ori 0x180][instr siguiente]`, coincidiendo exactamente con
los 8 sitios deseados (8 aciertos EU & US, 0 colisiones con los otros 7). Parche del byte
bajo `0x80 → 0xE0`.

### VP cámara — 11 sitios (`li t0,-192` → `-240`)

La tabla de límite izquierdo de la cámara carga `-192` (`addiu t0,zero,-0xC0` =
`34 08 ff 40`) en 11 entradas consecutivas → parcheado a `-240` (`34 08 ff 10`), dejando que
la cámara haga pan 48 px más a la izquierda para mantener el contenido centrado en la
ventana ampliada.

---

## Parte 2 — Capas de tiles del fondo

### Arquitectura (hallada con los depuradores GE + CPU)

* El fondo es una **tilemap dibujada tile a tile**: cada tile es un quad `DRAW PRIM` en
  modo through de GE.
* Dos rutinas de dibujo, cada una compartida por **todas** las capas de su tamaño de tile:
  * **`FUN_17268`** — tiles de 16 px (cielo, nubes, rocas). Dibuja **25 columnas**.
  * **`FUN_16B28`** — tiles de 32 px (templo, cascada, hierba de primer plano). Dibuja
    **13 columnas × 9 filas**.
* Struct de estado por capa (`s0`/`s1`): `+0x08` X viva · `+0x10` puntero de tile de
  trabajo · `+0x18` stride X · `+0x20` inicio X · `+0x22` columna de wrap · `+0x3E`
  número de filas.
* Los tiles viven en un **búfer circular estático** (64 columnas) llenado una vez al cargar
  el escenario; el scroll solo mueve la ventana de lectura. Slots vacíos = `0x00000000`,
  tiles válidos con flag `0x80000000`.
* El emisor de vértices compartido `FUN_1DD620` aplica el **centrado de +48 px**
  (`addiu a3,a3,0x30`). Tiene **22 llamadores** (sprites, HUD, …) → **no** debe tocarse, o
  los personajes se desplazarían.

25 col × 16 px ≈ 384 px (el contenido 4:3). Para llenar 480 → ≈ 31 columnas (6 más: 3 a la
izquierda + 3 a la derecha), centrado.

### Extensión a la derecha — límites de conteo de columnas

| Rutina | Límite | De | A |
|---|---|---|---|
| `FUN_17268` (16 px) | `slti a0,a2,25` (`28 c4 00 19`) | 25 | **31** (`…1F`) |
| `FUN_16B28` (32 px) | `slti a3,a2,13` (`28 c7 00 0d`) | 13 | **17** (`…11`) |
| `FUN_16B28` (32 px) | `slti a0,a2,13` (`28 c4 00 0d`) | 13 | **17** (`…11`) |

Cada firma de 32 px aparece **dos veces**; solo se parchea la que está **dentro del cuerpo
de `FUN_16B28`** (la más cercana al hook de inicio de fila, dentro de 0x600 bytes) — el
duplicado no relacionado se deja intacto. (Verificado en JP: duplicados lejanos en 0x17ae0 /
0x17d20 sin tocar.)

### Añadido a la izquierda (prepend) — code-caves

El bucle empieza en un borde izquierdo fijo y avanza a la derecha, así que un conteo mayor
solo hace crecer el lado **derecho**. Para añadir columnas a la **izquierda** manteniendo
los tiles existentes al píxel, la configuración de inicio de fila se hookea y, por fila:

```
Xstart -= N * stride     ; la ventana empieza N columnas antes (recentra en 480)
ptr    -= N * 4          ; puntero de tile retrocede N columnas (4 bytes por columna)
```

16 px: N=3 (Xstart-48, ptr-12). 32 px: N=2 (Xstart-64, ptr-8). El puntero y el inicio X se
mueven en cantidades coincidentes → los tiles existentes no se mueven, N nuevos tiles reales
aparecen en el margen izquierdo.

**Hook A** — store de fila de `FUN_17268` `sh t1,0x08(s0)` (`a6 09 00 08`, único) →
`j caveA`. `t1` = inicio X vivo aquí.
**Hook B** — store de fila de `FUN_16B28` `sh t0,0x08(s1)` (`a6 28 00 08`, único) →
`j caveB`. `t0` = inicio X vivo aquí.

> La generación de código de JP emite el área de inicio de fila algo distinta; el
> parcheador toma el **último** store del clúster encontrado, el punto de hook
> estructuralmente correcto (verificado por desensamblado: `t1`/`t0` = inicio X allí en las
> tres regiones).

**Cave A** (7 palabras) en el hueco de padding ejecutable hallado dinámicamente (una racha
de ceros ≥56 bytes en `.text`, en la práctica VA `0x1FF1B4`):

```
addiu t1,t1,-48      ; Xstart -= 3*16
sh    t1,0x08(s0)    ; replica el store desplazado (ajustado)
lw    t4,0x10(s0)    ; puntero de tile de trabajo
addiu t4,t4,-12      ; ptr -= 3 columnas
sw    t4,0x10(s0)
j     <hookA+8>      ; retorno relocado en runtime
nop
```

**Cave B** (7 palabras, justo después de A): misma forma con `-64`/`-8`, `s1`/`t0`,
retornando a `<hookB+8>`.

Las caves viven en el **padding de ceros existente dentro del segmento ejecutable** (la
única región probada que ejecuta de forma fiable). Sin cambio de tamaño de archivo.

---

## Lo que se probó y se descartó

* **Duplicación por triple render** — descartado por diseño (descentrado, falso).
* **Parchear el puntero de wrap / el streamer** — el búfer de tiles es estático; el streamer
  solo actualiza campos de scroll, no tiles, así que ampliarlo no aportaba nada.
* **Clamp-to-edge (duplicar el último tile válido en slots vacíos)** — corrompe los menús,
  porque «vacío» significa *transparente*, no *borde de escenario*; ambos no pueden
  distinguirse sin datos de ancho de escenario por capa. Abandonado.

La solución final (prepend + extensión del conteo) llena el cuadro con tiles **reales** y es
estable tanto en menús como en juego.

---

## Resumen de parches (por región, aplicados por firma)

| # | Parche | Firma | Edición |
|---|---|---|---|
| 1 | VP1 scaler | prewin `32 00 a5 a7 24 00 a4 a7` | `0x180→0x1E0` |
| 2 | VP2 pillarbox | `90 ff bd 27 60 00 b0 af 20 00 10 3c` | → `jr ra; nop` |
| 3 | VP ancho ×8 | 6 ventanas distintas de 8 bytes | `0x180→0x1E0` |
| 4 | VP cámara ×11 | palabra `34 08 ff 40` | `→ 34 08 ff 10` |
| 5 | count 16 px | `28 c4 00 19` (único) | `→ 28 c4 00 1f` |
| 6 | count 32 px (a3) | `28 c7 00 0d` cerca de hookB | `→ 28 c7 00 11` |
| 7 | count 32 px (a0) | `28 c4 00 0d` cerca de hookB | `→ 28 c4 00 11` |
| 8 | hook A + cave A | `a6 09 00 08` | `→ j caveA` + cave de 7 palabras |
| 9 | hook B + cave B | `a6 28 00 08` | `→ j caveB` + cave de 7 palabras |

### Añadidos v1.1

| # | Parche | Firma | Edición |
|---|---|---|---|
| 10 | cull decorado derecha | `3c 07 43 c0` (`lui a3,0x43c0`=384.0f, único) | `→ 0x43f0` (480.0f) |
| 11 | cull decorado izquierda | ventana `86 04 00 10 · 00 04 40 23` (única) | `subu→addiu t0,zr,-96` |
| 12 | fix wrap draw16 | `a6 09 00 22` (`sh t1,0x22(s0)`, único) | `→ j cave` (trigger +3) |
| 13 | fix wrap draw32 | `a6 28 00 22` (`sh t0,0x22(s1)`, único) | `→ j cave` (trigger +2) |
| 14 | hook 177c8 | `a6 08 00 08` (`sh t0,0x8(s0)`, único) | `→ j cave` (X−64 / ptr−8) |
| 15 | fix wrap 177c8 | `a6 08 00 22` (`sh t0,0x22(s0)`, único) | `→ j cave` (trigger +2) |
| 16 | counts 177c8 ×2 | `28 c7 00 0d` / `28 c4 00 0d` cerca de (15) | `→ …11` (13→17) |

**Por qué el fix de wrap (12–15).** El hook v1.0 desplaza el inicio de una capa de tiles N
columnas a la izquierda (N=3 para 16 px, N=2 para 32 px: `ptr -= N·4`, `Xstart -= N·16`)
para llenar el margen izquierdo ampliado, pero el disparador de wrap por capa (semilla
`+0x58` → `+0x22`) **no** se ajusta. El búfer de la capa tiene 64 columnas en orden de fila
(stride `0x100`); en el wrap el rebobinado resta exactamente una fila (`-0x100`). Como el
inicio se movió N columnas antes, el rebobinado aterriza N entradas en la fila **anterior**,
así que las columnas tras la costura leen una fila de tiles más arriba y se dibujan ~16 px
**demasiado abajo**. El fix añade `+N` al disparador para que el rebobinado caiga justo en el
borde de fila. Cada fix es una cave de 4 palabras:
`addiu rt,rt,N ; <sh rt,0x22(rs) original> ; j site+8 ; nop`.

Todos los parches se localizan por firmas únicas (verificado 1 aparición en EU/US/JP, salvo
las dos palabras `subu`/count que se desambiguan por una ventana de contexto o por
proximidad al store de wrap único). La v1.1 necesita 6 code-caves (33 palabras en total).

**Colocación de caves (importante).** No toda racha de ceros en la imagen ejecutable es
segura: algunas son scratch de runtime (a cero en el archivo pero escritas en ejecución), y
el gran hueco de fin de segmento también se sobrescribe — una cave puesta allí se sobrescribe
y el hook salta a basura (pantalla negra). Solo el **padding de código a mitad de segmento**
es de solo lectura en ejecución. Por eso el asignador se ancla en el primer hueco de `>=14`
palabras escaneando en ascendente (la región exacta que usó el build v1.0 validado en juego)
y luego asigna **solo desde los huecos más grandes de esa banda local** (worst-fit, caves
grandes primero), de modo que las 6 caves caen en el padding probado seguro (`0x1ff1b4`,
`0x1fef38`, `0x1feed0` en cada región) y los huecos pequeños/dispersos/de fin nunca se tocan.

Todo validado a nivel de bytes en EU, US y JP; la salida automática de JP se renderiza
idéntica a la referencia manual confirmada en juego (misma lógica de parche; caves en la
misma banda probada segura).

### Anclas por región (informativo; el parcheador no las codifica en duro)

| | EU | US | JP |
|---|---|---|---|
| hook A `sh t1,8(s0)` | `0x173FC` | `0x173FC` | `0x17464` |
| hook B `sh t0,8(s1)` | `0x16F30` | `0x16F30` | `0x16F98` |
| count 16 px | `0x1775C` | `0x1775C` | `0x177C4` |
| wrap draw16 `sh t1,0x22(s0)` | `0x1741C` | `0x1741C` | `0x17484` |
| wrap draw32 `sh t0,0x22(s1)` | `0x16F50` | `0x16F50` | `0x16FB8` |
| hook 177c8 `sh t0,0x8(s0)` | `0x17A50` | `0x17A48` | `0x17AB8` |
| wrap 177c8 `sh t0,0x22(s0)` | `0x17A70` | `0x17A70` | `0x17AD8` |
| cull decorado derecha `lui a3,0x43c0` | — | — | `0x7978` |
| caves (v1.1, ×6) | dinámico | dinámico | dinámico |
