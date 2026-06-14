# SFA3 MAX — Patch widescreen 16:9 natif (PSP)

> 🌐 [English](README.md) · [日本語](README.ja.md) · **Français** · [Español](README.es.md) · [Português (BR)](README.pt-BR.md)

Patch widescreen **16:9 natif (480×272)** pour **Street Fighter Alpha 3 MAX** /
**Street Fighter Zero 3 Double Upper** sur PSP.

L'option d'affichage interne du jeu doit être réglée sur **« Normal »** (4:3 non
étiré). Ce patch fait rendre le décor par le moteur **nativement en 16:9** : la
fenêtre de rendu est ouverte à 480 px complets et les calques de tuiles du décor
sont étendus avec de **vraies tuiles du stage** à gauche et à droite, **en restant
centrés** — sans étirement, sans duplication par triple rendu.

## Avant / après

| D'origine (4:3, pillarbox) | Patché (16:9 natif) |
|:---:|:---:|
| ![avant](images/before_4x3.png) | ![après](images/after_16x9.png) |

| | |
|---|---|
| **Version** | **1.1** |
| **Dumps supportés** | EU `ULES-00235` (v1.01) · US `ULUS-10062` · JP `ULJM-05082` (v1.01, Zero 3 Double Upper) |
| **Testé sur** | PPSSPP |
| **Entrée** | un `EBOOT.BIN` **déchiffré** (ELF) |
| **Méthode** | patcher binaire pur-Python, **pattern-scan** (aucun offset codé en dur) |

---

## Ce que ça fait

* **Ouverture du viewport** — fenêtre de rendu 384 → 480 px, pillarbox latéral supprimé.
* **Décor en widescreen** — les trois routines de dessin des tuiles de décor (calques
  16 px et 32 px) reçoivent des colonnes supplémentaires + un décalage à gauche, pour
  que le décor remplisse les 480 px **centré**.

### Nouveautés v1.1

* **Calques de décor peint / objets** (temples, arbres, éléments d'avant-plan, et les
  écrans titre / menu / sélection de personnage — un pipeline de rendu distinct que le
  patch v1.0 ne touchait pas) sont désormais étendus à 480 px au lieu d'être coupés aux
  anciennes bornes 4:3.
* **Correction du décalage vertical à la couture de wrap** — la v1.0 décalait les calques
  de tuiles vers la gauche pour combler le côté élargi, mais le déclencheur de
  rebouclage n'était pas ajusté : la dernière colonne / la couture de défilement lisait
  une rangée de tuiles trop bas (décalage d'environ 16 px vers le bas). Les trois
  routines de dessin compensent maintenant le déclencheur, et les coutures s'alignent
  parfaitement.
* **Troisième routine de tuiles** (`FUN_177c8`) — la seule routine de tilemap que la v1.0
  laissait en 4:3 reçoit maintenant le traitement widescreen complet (comptage +
  décalage à gauche + correction de couture).

Les sprites des personnages, le HUD et le gameplay ne sont pas modifiés et restent centrés.

### Limitation connue

Aux **extrémités d'un stage** (là où la tilemap ne contient tout simplement plus de
tuiles), une petite marge peut subsister dans ces rares positions de caméra. C'est une
limite *de données* du stage d'origine, pas une limite de code. En milieu de stage, le
décor est en plein 16:9.

---

## Démarrage rapide (PPSSPP, EBOOT déchiffré)

```
python sfa3_ws_patternpatcher.py  EBOOT.BIN  EBOOT_WS.BIN
```

Lance ensuite `EBOOT_WS.BIN` (ou réintègre-le dans l'ISO — voir plus bas) et règle
l'option d'affichage interne du jeu sur **Normal**.

Le patcher refuse d'écrire si quelque chose semble anormal (signature
manquante/dupliquée), et il est **idempotent** (une nouvelle exécution affiche `[skip]`).

---

## Installation la plus simple — cheat PPSSPP (sans déchiffrer ni réintégrer)

Des cheats prêts à l'emploi sont dans [`cheats/`](cheats/), un par région. Ils
appliquent exactement les mêmes modifications mémoire que le patcher, en continu à
l'exécution, donc **rien à déchiffrer ni réintégrer** — il suffit de déposer le fichier
et de l'activer.

1. Copie `cheats/<DISC-ID>.ini` dans `memstick/PSP/Cheats/` (ex. `ULES00235.ini`).
2. PPSSPP : **Settings → System → Enable cheats**.
3. Lance le jeu → **Pause → Cheats** → coche **« 16:9 Widescreen (native, v1.1) »**.
4. Règle l'option d'affichage interne du jeu sur **Normal**.

> ⚠️ **Spécifique à la version.** Les adresses du cheat sont fixes pour les dumps listés
> ci-dessus (EU/JP **v1.01**). Une révision différente décale les adresses — dans ce cas,
> utilise plutôt le patcher Python, qui localise tout par motif et s'adapte à n'importe
> quelle révision. (La révision de ton dump apparaît dans les infos du jeu de PPSSPP, ou
> sous la forme `_1.0x` dans les noms de save-states.)

---

## Workflow complet : ISO → déchiffrer → patcher → réintégrer

L'EBOOT dans une ISO commerciale est **chiffré** (en-tête `~PSP` / `PSAR`). Il faut
d'abord le déchiffrer. Le re-chiffrement n'est **pas** nécessaire pour PPSSPP.

### 1. Extraire et déchiffrer l'EBOOT (PPSSPP)

PPSSPP peut produire l'EBOOT déchiffré pour toi :

1. **Settings → Tools → Developer tools** → active
   **"Dump Decrypted EBOOT.BIN on game boot"**.
2. Démarre le jeu une fois.
3. Le fichier déchiffré apparaît dans
   `memstick/PSP/SYSTEM/DUMP/<DISC-ID>_EBOOT.BIN`
   (ex. `ULES00235_EBOOT.BIN`). Copie-le.

> Alternativement, utilise **PRXDecrypter** sur une PSP réelle/émulée, qui écrit un
> `BOOT.BIN` déchiffré.

### 2. Le patcher

```
python sfa3_ws_patternpatcher.py  ULES00235_EBOOT.BIN  EBOOT_WS.BIN
```

### 3. Réintégrer dans l'ISO (UMDGen)

1. Ouvre l'ISO d'origine dans **UMDGen**.
2. Va dans `PSP_GAME/SYSDIR/EBOOT.BIN`.
3. **Clic droit → Import / Replace file** et choisis `EBOOT_WS.BIN`.
   - PPSSPP exécute directement un EBOOT **déchiffré** placé dans l'ISO ; aucune
     signature nécessaire pour l'émulateur.
4. **File → Save As** pour une nouvelle ISO.

> L'usage sur matériel réel nécessite un EBOOT signé (ex. `sign_np`) et un CFW ; ce
> guide vise PPSSPP.

### 4. Régler l'affichage sur Normal

Dans le jeu : **Options → Display → Normal** (pas « Wide »/étiré). Le widescreen vient
maintenant de vraies tuiles rendues, pas d'un étirement.

---

## Fichiers

| Fichier | Rôle |
|---|---|
| `sfa3_ws_patternpatcher.py` | le patcher (EU/US/JP, pattern-scan) |
| `cheats/<DISC-ID>.ini` | cheats PPSSPP prêts à l'emploi (par région, sans réintégration) |
| `README.md` | ce fichier — guide utilisateur |
| `TECHNICAL.md` | écrit complet de reverse-engineering : chaque patch expliqué |
| `LICENSE` | MIT (code du patcher uniquement) ; jeu © Capcom |

---

## Outils utilisés

| Outil | Rôle | Où |
|---|---|---|
| **Python 3** | exécute le patcher (stdlib uniquement — pas de `pip install`) | python.org |
| **PPSSPP** | dump de déchiffrement EBOOT · débogueurs GE/CPU utilisés pour le reverse | ppsspp.org |
| **UMDGen** | réintègre l'EBOOT patché dans l'ISO | (outil ISO Windows) |
| **PRXDecrypter** | déchiffrement EBOOT alternatif sur PSP réelle/CFW | (homebrew PSP) |
| **sign_np** | re-signe l'EBOOT pour le matériel réel (inutile pour PPSSPP) | (homebrew PSP) |

> Prérequis : **Python 3.8+**. Aucun paquet tiers — le patcher n'importe que `os`,
> `sys`, `struct` de la bibliothèque standard.

---

## Crédits / notes

Reverse-engineering réalisé depuis l'EBOOT déchiffré par désassemblage MIPS statique et
les débogueurs GE/CPU de PPSSPP. Le patch est un ensemble de modifications d'instructions
en place plus deux petits code-caves placés dans du padding exécutable existant — aucun
changement de taille de fichier.

Jeu d'origine © Capcom.
