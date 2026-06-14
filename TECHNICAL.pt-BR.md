# Documento técnico — patch widescreen 16:9 SFA3 MAX

> 🌐 [English](TECHNICAL.md) · [日本語](TECHNICAL.ja.md) · [Français](TECHNICAL.fr.md) · [Español](TECHNICAL.es.md) · **Português (BR)**

Explicação completa de como o patch foi obtido por engenharia reversa e do que cada edição
de bytes faz. Salvo indicação em contrário, todos os endereços abaixo são **endereços
virtuais (VA)** do EBOOT descriptografado.

## Convenções

| Termo | Valor |
|---|---|
| Offset de arquivo de um VA | `file = VA + 0x74` (o cabeçalho de programa ELF mapeia VA 0 → file 0x74) |
| Base de carga em runtime | `0x08804000` → `runtime = VA + 0x08804000` |
| Tela nativa do PSP | 480 × 272 (16:9 real por hardware) |
| Largura do conteúdo 4:3 | 384 px → margens de 48 px de cada lado (o offset de centralização) |
| Codificação `j`/`jal` | `0x08000000 | ((target >> 2) & 0x03FFFFFF)` |

> **Aviso de relocação.** Os `j`/`jal` injetados à mão **não** são relocados pelo loader do
> PSP (ele só corrige os saltos presentes no momento do link). Portanto os saltos injetados
> devem codificar o alvo em **runtime** (`VA + 0x08804000`). Errar aqui produz um crash
> "Bad Execution Address → Jump to 0x00xxxxxx" (observado e corrigido durante o
> desenvolvimento).

## Independência de região (pattern-scan)

EU, US e JP compartilham o mesmo código de render, mas em **offsets diferentes** (JP é
~1 KB menor; US difere de EU em ~30 % dos bytes). Endereços fixos não são confiáveis, então
o patcher localiza cada ponto por uma **assinatura única de bytes de instrução** e aplica o
patch no offset encontrado. Cada assinatura foi verificada como ocorrendo o número esperado
de vezes nos três EBOOT.

---

## Parte 1 — Abertura da viewport

O jogo original renderiza uma janela de 384 px de largura centralizada em 480, com barras
pretas (pillarbox) nas laterais. Quatro edições a abrem para os 480 completos.

### VP1 — largura do escalonador de render (`ori a0,zero,0x180` → `0x1E0`)

Um único ponto carrega `0x180` (384) como largura de render em `a0`. Localizado pela
**janela anterior única** `32 00 a5 a7 24 00 a4 a7`; a palavra seguinte é
`ori a0,zero,0x180` (LE `80 01 04 34`). Patch do byte baixo do imediato `0x80 → 0xE0`
→ `0x1E0`.

### VP2 — neutralizar a rotina do pillarbox (`jr ra; nop`)

A função que desenha as barras laterais é neutralizada substituindo seu prólogo por
`jr ra; nop` (`08 00 e0 03 00 00 00 00`). Localizada pela assinatura de prólogo única de
12 bytes `90 ff bd 27  60 00 b0 af  20 00 10 3c`.

### VP largura — 8 pontos de chamada (`ori a2/a3,zero,0x180` → `0x1E0`)

Oito lugares constroem um argumento de largura GE de `0x180`. A palavra literal
`34 06 01 80` aparece **15 vezes**, mas só 8 são o argumento de largura. Eles são
desambiguados por uma **janela de 8 bytes** `[ori 0x180][instr seguinte]`, correspondendo
exatamente aos 8 pontos desejados (8 acertos EU & US, 0 colisões com os outros 7). Patch do
byte baixo `0x80 → 0xE0`.

### VP câmera — 11 pontos (`li t0,-192` → `-240`)

A tabela de limite esquerdo da câmera carrega `-192` (`addiu t0,zero,-0xC0` =
`34 08 ff 40`) em 11 entradas consecutivas → corrigido para `-240` (`34 08 ff 10`),
permitindo que a câmera faça pan 48 px mais à esquerda para manter o conteúdo centralizado
na janela ampliada.

---

## Parte 2 — Camadas de tiles do fundo

### Arquitetura (descoberta com os depuradores GE + CPU)

* O fundo é uma **tilemap desenhada tile a tile**: cada tile é um quad `DRAW PRIM` no modo
  through do GE.
* Duas rotinas de desenho, cada uma compartilhada por **todas** as camadas do seu tamanho
  de tile:
  * **`FUN_17268`** — tiles de 16 px (céu, nuvens, rochas). Desenha **25 colunas**.
  * **`FUN_16B28`** — tiles de 32 px (templo, cachoeira, grama de primeiro plano). Desenha
    **13 colunas × 9 linhas**.
* Struct de estado por camada (`s0`/`s1`): `+0x08` X viva · `+0x10` ponteiro de tile de
  trabalho · `+0x18` stride X · `+0x20` início X · `+0x22` coluna de wrap · `+0x3E`
  número de linhas.
* Os tiles ficam em um **buffer circular estático** (64 colunas) preenchido uma vez no
  carregamento do estágio; a rolagem só move a janela de leitura. Slots vazios =
  `0x00000000`, tiles válidos com flag `0x80000000`.
* O emissor de vértices compartilhado `FUN_1DD620` aplica a **centralização de +48 px**
  (`addiu a3,a3,0x30`). Ele tem **22 chamadores** (sprites, HUD, …) → **não** deve ser
  tocado, ou os personagens se deslocariam.

25 col × 16 px ≈ 384 px (o conteúdo 4:3). Para preencher 480 → ≈ 31 colunas (6 a mais: 3 à
esquerda + 3 à direita), centralizado.

### Extensão à direita — travas de contagem de colunas

| Rotina | Trava | De | Para |
|---|---|---|---|
| `FUN_17268` (16 px) | `slti a0,a2,25` (`28 c4 00 19`) | 25 | **31** (`…1F`) |
| `FUN_16B28` (32 px) | `slti a3,a2,13` (`28 c7 00 0d`) | 13 | **17** (`…11`) |
| `FUN_16B28` (32 px) | `slti a0,a2,13` (`28 c4 00 0d`) | 13 | **17** (`…11`) |

Cada assinatura de 32 px aparece **duas vezes**; só a que está **dentro do corpo de
`FUN_16B28`** (a mais próxima do hook de início de linha, dentro de 0x600 bytes) é
corrigida — a duplicata não relacionada fica intacta. (Verificado no JP: duplicatas distantes
em 0x17ae0 / 0x17d20 não tocadas.)

### Acréscimo à esquerda (prepend) — code-caves

O loop começa numa borda esquerda fixa e avança para a direita, então uma contagem maior só
faz crescer o lado **direito**. Para adicionar colunas à **esquerda** mantendo os tiles
existentes no pixel, a configuração de início de linha é hookada e, por linha:

```
Xstart -= N * stride     ; a janela começa N colunas antes (recentraliza em 480)
ptr    -= N * 4          ; ponteiro de tile recua N colunas (4 bytes por coluna)
```

16 px: N=3 (Xstart-48, ptr-12). 32 px: N=2 (Xstart-64, ptr-8). O ponteiro e o início X se
movem em quantidades correspondentes → os tiles existentes não se movem, N novos tiles reais
aparecem na margem esquerda.

**Hook A** — store de linha de `FUN_17268` `sh t1,0x08(s0)` (`a6 09 00 08`, único) →
`j caveA`. `t1` = início X vivo aqui.
**Hook B** — store de linha de `FUN_16B28` `sh t0,0x08(s1)` (`a6 28 00 08`, único) →
`j caveB`. `t0` = início X vivo aqui.

> A geração de código do JP emite a área de início de linha de forma um pouco diferente; o
> patcher pega o **último** store do cluster encontrado, o ponto de hook estruturalmente
> correto (verificado por desassembly: `t1`/`t0` = início X ali nas três regiões).

**Cave A** (7 palavras) no buraco de padding executável encontrado dinamicamente (uma
sequência de zeros ≥56 bytes em `.text`, na prática VA `0x1FF1B4`):

```
addiu t1,t1,-48      ; Xstart -= 3*16
sh    t1,0x08(s0)    ; replica o store deslocado (ajustado)
lw    t4,0x10(s0)    ; ponteiro de tile de trabalho
addiu t4,t4,-12      ; ptr -= 3 colunas
sw    t4,0x10(s0)
j     <hookA+8>      ; retorno relocado em runtime
nop
```

**Cave B** (7 palavras, logo após A): mesma forma com `-64`/`-8`, `s1`/`t0`, retornando a
`<hookB+8>`.

As caves ficam no **padding de zeros existente dentro do segmento executável** (a única
região comprovadamente executada de forma confiável). Sem mudança de tamanho de arquivo.

---

## O que foi tentado e rejeitado

* **Duplicação por render triplo** — rejeitado por design (descentralizado, falso).
* **Patch do ponteiro de wrap / do streamer** — o buffer de tiles é estático; o streamer só
  atualiza campos de scroll, não tiles, então ampliá-lo não trazia nada.
* **Clamp-to-edge (duplicar o último tile válido nos slots vazios)** — corrompe os menus,
  porque "vazio" significa *transparente*, não *borda do estágio*; os dois não podem ser
  distinguidos sem dados de largura de estágio por camada. Abandonado.

A solução final (prepend + extensão da contagem) preenche o quadro com tiles **reais** e é
estável tanto nos menus quanto no jogo.

---

## Resumo dos patches (por região, aplicados por assinatura)

| # | Patch | Assinatura | Edição |
|---|---|---|---|
| 1 | VP1 scaler | prewin `32 00 a5 a7 24 00 a4 a7` | `0x180→0x1E0` |
| 2 | VP2 pillarbox | `90 ff bd 27 60 00 b0 af 20 00 10 3c` | → `jr ra; nop` |
| 3 | VP largura ×8 | 6 janelas distintas de 8 bytes | `0x180→0x1E0` |
| 4 | VP câmera ×11 | palavra `34 08 ff 40` | `→ 34 08 ff 10` |
| 5 | count 16 px | `28 c4 00 19` (único) | `→ 28 c4 00 1f` |
| 6 | count 32 px (a3) | `28 c7 00 0d` perto de hookB | `→ 28 c7 00 11` |
| 7 | count 32 px (a0) | `28 c4 00 0d` perto de hookB | `→ 28 c4 00 11` |
| 8 | hook A + cave A | `a6 09 00 08` | `→ j caveA` + cave de 7 palavras |
| 9 | hook B + cave B | `a6 28 00 08` | `→ j caveB` + cave de 7 palavras |

### Adições v1.1

| # | Patch | Assinatura | Edição |
|---|---|---|---|
| 10 | cull decoração direita | `3c 07 43 c0` (`lui a3,0x43c0`=384.0f, único) | `→ 0x43f0` (480.0f) |
| 11 | cull decoração esquerda | janela `86 04 00 10 · 00 04 40 23` (única) | `subu→addiu t0,zr,-96` |
| 12 | fix wrap draw16 | `a6 09 00 22` (`sh t1,0x22(s0)`, único) | `→ j cave` (trigger +3) |
| 13 | fix wrap draw32 | `a6 28 00 22` (`sh t0,0x22(s1)`, único) | `→ j cave` (trigger +2) |
| 14 | hook 177c8 | `a6 08 00 08` (`sh t0,0x8(s0)`, único) | `→ j cave` (X−64 / ptr−8) |
| 15 | fix wrap 177c8 | `a6 08 00 22` (`sh t0,0x22(s0)`, único) | `→ j cave` (trigger +2) |
| 16 | counts 177c8 ×2 | `28 c7 00 0d` / `28 c4 00 0d` perto de (15) | `→ …11` (13→17) |

**Por que o fix de wrap (12–15).** O hook v1.0 desloca o início de uma camada de tiles N
colunas à esquerda (N=3 para 16 px, N=2 para 32 px: `ptr -= N·4`, `Xstart -= N·16`) para
preencher a margem esquerda ampliada, mas o gatilho de wrap por camada (semente `+0x58` →
`+0x22`) **não** é ajustado. O buffer da camada tem 64 colunas em ordem de linha (stride
`0x100`); no wrap, o rebobinamento subtrai exatamente uma linha (`-0x100`). Como o início se
moveu N colunas antes, o rebobinamento cai N entradas na linha **anterior**, então as colunas
depois da emenda leem uma linha de tiles acima e são desenhadas ~16 px **baixo demais**. O
fix soma `+N` ao gatilho para que o rebobinamento caia exatamente na borda da linha. Cada fix
é uma cave de 4 palavras: `addiu rt,rt,N ; <sh rt,0x22(rs) original> ; j site+8 ; nop`.

Todos os patches são localizados por assinaturas únicas (verificado 1 ocorrência em EU/US/JP,
exceto as duas palavras `subu`/count que são desambiguadas por uma janela de contexto ou por
proximidade ao store de wrap único). A v1.1 precisa de 6 code-caves (33 palavras no total).

**Posicionamento das caves (importante).** Nem toda sequência de zeros na imagem executável
é segura: algumas são scratch de runtime (zeradas no arquivo mas escritas em execução), e o
grande buraco de fim de segmento também é sobrescrito — uma cave colocada ali é sobrescrita e
o hook salta para lixo (tela preta). Só o **padding de código no meio do segmento** é
somente-leitura em execução. Por isso o alocador se ancora no primeiro buraco de `>=14`
palavras varrendo em ordem crescente (a região exata que o build v1.0 validado em jogo usou)
e então aloca **apenas dos maiores buracos dessa banda local** (worst-fit, caves grandes
primeiro), de modo que as 6 caves caem no padding comprovadamente seguro (`0x1ff1b4`,
`0x1fef38`, `0x1feed0` em cada região) e os buracos pequenos/dispersos/de fim nunca são
tocados.

Tudo validado em nível de bytes em EU, US e JP; a saída automática do JP renderiza idêntica à
referência manual confirmada em jogo (mesma lógica de patch; caves na mesma banda
comprovadamente segura).

### Âncoras por região (informativo; o patcher não as fixa em duro)

| | EU | US | JP |
|---|---|---|---|
| hook A `sh t1,8(s0)` | `0x173FC` | `0x173FC` | `0x17464` |
| hook B `sh t0,8(s1)` | `0x16F30` | `0x16F30` | `0x16F98` |
| count 16 px | `0x1775C` | `0x1775C` | `0x177C4` |
| wrap draw16 `sh t1,0x22(s0)` | `0x1741C` | `0x1741C` | `0x17484` |
| wrap draw32 `sh t0,0x22(s1)` | `0x16F50` | `0x16F50` | `0x16FB8` |
| hook 177c8 `sh t0,0x8(s0)` | `0x17A50` | `0x17A48` | `0x17AB8` |
| wrap 177c8 `sh t0,0x22(s0)` | `0x17A70` | `0x17A70` | `0x17AD8` |
| cull decoração direita `lui a3,0x43c0` | — | — | `0x7978` |
| caves (v1.1, ×6) | dinâmico | dinâmico | dinâmico |
