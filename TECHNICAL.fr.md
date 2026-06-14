# Note technique — patch widescreen 16:9 SFA3 MAX

> 🌐 [English](TECHNICAL.md) · [日本語](TECHNICAL.ja.md) · **Français** · [Español](TECHNICAL.es.md) · [Português (BR)](TECHNICAL.pt-BR.md)

Explication complète de la façon dont le patch a été reverse-engineered et de ce que
fait chaque modification d'octet. Sauf indication contraire, toutes les adresses ci-dessous
sont des **adresses virtuelles (VA)** de l'EBOOT déchiffré.

## Conventions

| Terme | Valeur |
|---|---|
| Offset fichier d'une VA | `file = VA + 0x74` (l'en-tête de programme ELF mappe VA 0 → file 0x74) |
| Base de chargement runtime | `0x08804000` → `runtime = VA + 0x08804000` |
| Écran natif PSP | 480 × 272 (vrai 16:9 matériel) |
| Largeur contenu 4:3 | 384 px → marges de 48 px de chaque côté (l'offset de centrage) |
| Encodage `j`/`jal` | `0x08000000 | ((target >> 2) & 0x03FFFFFF)` |

> **Avertissement relocalisation.** Les `j`/`jal` injectés à la main ne sont **pas**
> relocalisés par le loader PSP (il ne corrige que les sauts présents au moment du link).
> Les sauts injectés doivent donc encoder la cible **runtime** (`VA + 0x08804000`). Une
> erreur ici produit un crash « Bad Execution Address → Jump to 0x00xxxxxx » (observé et
> corrigé pendant le développement).

## Indépendance de région (pattern-scan)

EU, US et JP partagent le même code de rendu mais à des **offsets différents** (JP est
~1 Ko plus petit ; US diffère d'EU sur ~30 % des octets). Les adresses codées en dur ne
sont pas fiables, donc le patcher localise chaque site par une **signature d'octets
d'instruction unique** et patche à l'offset trouvé. Chaque signature a été vérifiée comme
apparaissant le nombre de fois attendu dans les trois EBOOT.

---

## Partie 1 — Ouverture du viewport

Le jeu d'origine rend une fenêtre de 384 px de large centrée dans 480, avec des barres
noires (pillarbox) sur les côtés. Quatre modifications l'ouvrent au 480 complet.

### VP1 — largeur du scaler de rendu (`ori a0,zero,0x180` → `0x1E0`)

Un seul site charge `0x180` (384) comme largeur de rendu dans `a0`. Localisé par la
**fenêtre précédente unique** `32 00 a5 a7 24 00 a4 a7` ; le mot suivant est
`ori a0,zero,0x180` (LE `80 01 04 34`). Patch de l'octet bas de l'immédiat `0x80 → 0xE0`
→ `0x1E0`.

### VP2 — neutraliser la routine pillarbox (`jr ra; nop`)

La fonction qui dessine les barres latérales est neutralisée en remplaçant son prologue
par `jr ra; nop` (`08 00 e0 03 00 00 00 00`). Localisée par la signature de prologue unique
de 12 octets `90 ff bd 27  60 00 b0 af  20 00 10 3c`.

### VP largeur — 8 sites d'appel (`ori a2/a3,zero,0x180` → `0x1E0`)

Huit endroits construisent un argument de largeur GE à `0x180`. Le mot littéral
`34 06 01 80` apparaît **15 fois**, mais seuls 8 sont l'argument de largeur. Ils sont
désambiguïsés par une **fenêtre de 8 octets** `[ori 0x180][instr suivante]`, correspondant
exactement aux 8 sites voulus (8 occurrences EU & US, 0 collision avec les 7 autres). Patch
de l'octet bas `0x80 → 0xE0`.

### VP caméra — 11 sites (`li t0,-192` → `-240`)

La table de borne gauche de la caméra charge `-192` (`addiu t0,zero,-0xC0` = `34 08 ff 40`)
dans 11 entrées consécutives → patché à `-240` (`34 08 ff 10`), laissant la caméra panoter
48 px plus à gauche pour garder le contenu centré dans la fenêtre élargie.

---

## Partie 2 — Calques de tuiles du décor

### Architecture (trouvée via les débogueurs GE + CPU)

* Le décor est une **tilemap dessinée tuile par tuile** : chaque tuile est un quad
  `DRAW PRIM` en mode through GE.
* Deux routines de dessin, chacune partagée par **tous** les calques de sa taille de tuile :
  * **`FUN_17268`** — tuiles 16 px (ciel, nuages, rochers). Dessine **25 colonnes**.
  * **`FUN_16B28`** — tuiles 32 px (temple, cascade, herbe d'avant-plan). Dessine
    **13 colonnes × 9 rangées**.
* Struct d'état par calque (`s0`/`s1`) : `+0x08` X live · `+0x10` pointeur de tuile de
  travail · `+0x18` stride X · `+0x20` X start · `+0x22` colonne de wrap · `+0x3E`
  nombre de rangées.
* Les tuiles vivent dans un **buffer circulaire statique** (64 colonnes) rempli une fois au
  chargement du stage ; le défilement ne fait que déplacer la fenêtre de lecture. Slots
  vides = `0x00000000`, tuiles valides portant le flag `0x80000000`.
* L'émetteur de sommets partagé `FUN_1DD620` applique le **centrage de +48 px**
  (`addiu a3,a3,0x30`). Il a **22 appelants** (sprites, HUD, …) → ne doit **pas** être
  touché, sinon les personnages se décaleraient.

25 col × 16 px ≈ 384 px (le contenu 4:3). Pour remplir 480 → ≈ 31 colonnes (6 de plus :
3 à gauche + 3 à droite), centré.

### Extension à droite — verrous de comptage de colonnes

| Routine | Verrou | De | À |
|---|---|---|---|
| `FUN_17268` (16 px) | `slti a0,a2,25` (`28 c4 00 19`) | 25 | **31** (`…1F`) |
| `FUN_16B28` (32 px) | `slti a3,a2,13` (`28 c7 00 0d`) | 13 | **17** (`…11`) |
| `FUN_16B28` (32 px) | `slti a0,a2,13` (`28 c4 00 0d`) | 13 | **17** (`…11`) |

Chaque signature 32 px apparaît **deux fois** ; seule celle **dans le corps de
`FUN_16B28`** (la plus proche du hook de début de rangée, dans les 0x600 octets) est
patchée — le doublon non lié est laissé intact. (Vérifié sur JP : doublons lointains à
0x17ae0 / 0x17d20 non touchés.)

### Ajout à gauche (prepend) — code-caves

La boucle commence à un bord gauche fixe et avance vers la droite, donc un comptage plus
grand ne fait grandir que le côté **droit**. Pour ajouter des colonnes à **gauche** tout
en gardant les tuiles existantes au pixel près, la configuration de début de rangée est
hookée et, par rangée :

```
Xstart -= N * stride     ; la fenêtre commence N colonnes plus tôt (recentre sur 480)
ptr    -= N * 4          ; pointeur de tuile reculé de N colonnes (4 octets par colonne)
```

16 px : N=3 (Xstart-48, ptr-12). 32 px : N=2 (Xstart-64, ptr-8). Le pointeur et le X start
bougent de quantités correspondantes → les tuiles existantes ne bougent pas, N nouvelles
tuiles réelles apparaissent dans la marge gauche.

**Hook A** — store de rangée de `FUN_17268` `sh t1,0x08(s0)` (`a6 09 00 08`, unique) →
`j caveA`. `t1` = X start live ici.
**Hook B** — store de rangée de `FUN_16B28` `sh t0,0x08(s1)` (`a6 28 00 08`, unique) →
`j caveB`. `t0` = X start live ici.

> La génération de code JP émet la zone de début de rangée un peu différemment ; le patcher
> prend le **dernier** store du cluster trouvé, le point de hook structurellement correct
> (vérifié par désassemblage : `t1`/`t0` = X start là dans les trois régions).

**Cave A** (7 mots) dans le trou de padding exécutable trouvé dynamiquement (une plage de
zéros ≥56 octets dans `.text`, en pratique VA `0x1FF1B4`) :

```
addiu t1,t1,-48      ; Xstart -= 3*16
sh    t1,0x08(s0)    ; reproduit le store déplacé (ajusté)
lw    t4,0x10(s0)    ; pointeur de tuile de travail
addiu t4,t4,-12      ; ptr -= 3 colonnes
sw    t4,0x10(s0)
j     <hookA+8>      ; retour relocalisé en runtime
nop
```

**Cave B** (7 mots, juste après A) : même forme avec `-64`/`-8`, `s1`/`t0`, retour à
`<hookB+8>`.

Les caves vivent dans le **padding de zéros existant à l'intérieur du segment exécutable**
(la seule région prouvée s'exécuter de façon fiable). Aucun changement de taille de fichier.

---

## Ce qui a été essayé puis rejeté

* **Duplication par triple rendu** — rejeté par conception (décentré, factice).
* **Patch du pointeur de wrap / du streamer** — le buffer de tuiles est statique ; le
  streamer ne met à jour que les champs de scroll, pas les tuiles, donc l'élargir
  n'apportait rien.
* **Clamp-to-edge (dupliquer la dernière tuile valide sur les slots vides)** — corrompt les
  menus, car « vide » signifie *transparent*, pas *bord de stage* ; les deux ne peuvent pas
  être distingués sans données de largeur de stage par calque. Abandonné.

La solution livrée (prepend + extension du comptage) remplit l'image avec de **vraies**
tuiles et est stable dans les menus comme en jeu.

---

## Récapitulatif des patches (par région, appliqués par signature)

| # | Patch | Signature | Édition |
|---|---|---|---|
| 1 | VP1 scaler | prewin `32 00 a5 a7 24 00 a4 a7` | `0x180→0x1E0` |
| 2 | VP2 pillarbox | `90 ff bd 27 60 00 b0 af 20 00 10 3c` | → `jr ra; nop` |
| 3 | VP largeur ×8 | 6 fenêtres distinctes de 8 octets | `0x180→0x1E0` |
| 4 | VP caméra ×11 | mot `34 08 ff 40` | `→ 34 08 ff 10` |
| 5 | count 16 px | `28 c4 00 19` (unique) | `→ 28 c4 00 1f` |
| 6 | count 32 px (a3) | `28 c7 00 0d` près de hookB | `→ 28 c7 00 11` |
| 7 | count 32 px (a0) | `28 c4 00 0d` près de hookB | `→ 28 c4 00 11` |
| 8 | hook A + cave A | `a6 09 00 08` | `→ j caveA` + cave 7 mots |
| 9 | hook B + cave B | `a6 28 00 08` | `→ j caveB` + cave 7 mots |

### Ajouts v1.1

| # | Patch | Signature | Édition |
|---|---|---|---|
| 10 | cull décor peint droite | `3c 07 43 c0` (`lui a3,0x43c0`=384.0f, unique) | `→ 0x43f0` (480.0f) |
| 11 | cull décor peint gauche | fenêtre `86 04 00 10 · 00 04 40 23` (unique) | `subu→addiu t0,zr,-96` |
| 12 | fix wrap draw16 | `a6 09 00 22` (`sh t1,0x22(s0)`, unique) | `→ j cave` (trigger +3) |
| 13 | fix wrap draw32 | `a6 28 00 22` (`sh t0,0x22(s1)`, unique) | `→ j cave` (trigger +2) |
| 14 | hook 177c8 | `a6 08 00 08` (`sh t0,0x8(s0)`, unique) | `→ j cave` (X−64 / ptr−8) |
| 15 | fix wrap 177c8 | `a6 08 00 22` (`sh t0,0x22(s0)`, unique) | `→ j cave` (trigger +2) |
| 16 | counts 177c8 ×2 | `28 c7 00 0d` / `28 c4 00 0d` près de (15) | `→ …11` (13→17) |

**Pourquoi le fix de wrap (12–15).** Le hook v1.0 décale le départ d'un calque de tuiles de
N colonnes vers la gauche (N=3 pour 16 px, N=2 pour 32 px : `ptr -= N·4`, `Xstart -= N·16`)
pour combler la marge gauche élargie, mais le déclencheur de wrap par calque (graine
`+0x58` → `+0x22`) n'est **pas** ajusté. Le buffer du calque fait 64 colonnes en ordre
ligne (stride `0x100`) ; au wrap, le rembobinage soustrait exactement une rangée (`-0x100`).
Comme le départ a bougé de N colonnes en avance, le rembobinage atterrit N entrées dans la
rangée **précédente**, donc les colonnes après la couture lisent une rangée de tuiles plus
haut et s'affichent ~16 px **trop bas**. Le fix ajoute `+N` au déclencheur pour que le
rembobinage tombe pile sur la frontière de rangée. Chaque fix est une cave de 4 mots :
`addiu rt,rt,N ; <sh rt,0x22(rs) d'origine> ; j site+8 ; nop`.

Tous les patches sont localisés par des signatures uniques (vérifié 1 occurrence sur
EU/US/JP, sauf les deux mots `subu`/count qui sont désambiguïsés par une fenêtre de contexte
ou par proximité au store de wrap unique). La v1.1 a besoin de 6 code-caves (33 mots au total).

**Placement des caves (important).** Toutes les plages de zéros de l'image exécutable ne
sont pas sûres : certaines sont du scratch runtime (à zéro dans le fichier mais écrites à
l'exécution), et le grand trou de fin de segment est écrasé aussi — une cave placée là est
écrasée et le hook saute dans des données invalides (écran noir). Seul le **padding de code
en milieu de segment** est en lecture seule à l'exécution. L'allocateur s'ancre donc sur le
premier trou `>=14` mots en parcourant en ascendant (la région exacte qu'utilisait le build
v1.0 validé en jeu), puis alloue **uniquement depuis les plus grands trous de cette bande
locale** (worst-fit, grandes caves d'abord), de sorte que les 6 caves atterrissent dans le
padding prouvé sûr (`0x1ff1b4`, `0x1fef38`, `0x1feed0` sur chaque région) et que les
petits trous épars / de fin ne sont jamais touchés.

Tout validé au niveau octet sur EU, US et JP ; la sortie auto JP s'affiche à l'identique de
la référence manuelle confirmée en jeu (même logique de patch ; caves dans la même bande
prouvée sûre).

### Ancres par région (informatif ; le patcher ne les code pas en dur)

| | EU | US | JP |
|---|---|---|---|
| hook A `sh t1,8(s0)` | `0x173FC` | `0x173FC` | `0x17464` |
| hook B `sh t0,8(s1)` | `0x16F30` | `0x16F30` | `0x16F98` |
| count 16 px | `0x1775C` | `0x1775C` | `0x177C4` |
| wrap draw16 `sh t1,0x22(s0)` | `0x1741C` | `0x1741C` | `0x17484` |
| wrap draw32 `sh t0,0x22(s1)` | `0x16F50` | `0x16F50` | `0x16FB8` |
| hook 177c8 `sh t0,0x8(s0)` | `0x17A50` | `0x17A48` | `0x17AB8` |
| wrap 177c8 `sh t0,0x22(s0)` | `0x17A70` | `0x17A70` | `0x17AD8` |
| cull décor peint droite `lui a3,0x43c0` | — | — | `0x7978` |
| caves (v1.1, ×6) | dynamique | dynamique | dynamique |
