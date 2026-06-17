# TEST_MC_PLAYERS — Evaluación de los 20 edificios con jugadores de Minecraft

> **Nota sobre este repo público.** Aquí se incluye solo el **código del instrumento**
> (la SPA de evaluación). Los 20 edificios-estímulo (`public/data/`) son salidas generadas
> del Experimento 2 y **no se publican**; el `RESULT_EMAIL` se ha dejado en blanco. Los
> resultados y el análisis de este estudio (RQ5) están en [`../correlacion_humano/`](../correlacion_humano/).

Web (SPA) donde ~10 jugadores de Minecraft **exploran en primera persona** los
20 edificios del Experimento 2 (los mismos de `Test_Arquitecto/test.md`) y los
**puntúan de 1 a 10** en las 8 dimensiones de calidad. Las respuestas se envían
a una hoja de Google Sheets (y se pueden descargar en CSV) para correlacionarlas
(Spearman) con el evaluador automático.

## Stack

- **Vite + React 19 + React Three Fiber 9 + drei 10 + three 0.184 + zustand 5 + Tailwind 4**
- Rendering: **un `THREE.InstancedMesh` por entrada de paleta** (≈30–60 draw
  calls por edificio, nunca un mesh por bloque). Las formas especiales
  (puertas, camas, antorchas, escaleras, losas, vallas, cristales, plantas…)
  vienen de los *block handlers* portados del visor del proyecto
  (`src/lib/blocks/`), con orientación por blockstate (`facing`, `half`, `axis`).
- Texturas reales de Minecraft **1.16.5** desde jsDelivr (CORS `*`), con caché.
  Los IDs inventados por los LLM o post-1.16 se corrigen en `src/lib/remap.js`.
- Físicas propias (`src/lib/physics.js`): AABB 0.6×1.8 con gravedad, colisión
  **por eje** contra un `Set` de vóxeles, *step-up* automático de 1 bloque
  (las escaleras se suben andando) y **modo SUPER** (tecla `F` o doble-espacio):
  vuelo libre atravesando bloques.

## Ejecutar en local

```bash
cd TEST_MC_PLAYERS
npm install
npm run dev          # → http://localhost:5173
```

Si `public/data/` no tuviera los 20 edificios, la app arranca con una casita
de prueba (`public/data/mock.json`).

## Regenerar los datos de los 20 edificios

```bash
python3 tools/build_test_mc_players_data.py   # desde la raíz del repo
```

Lee `Test_Arquitecto/chosen20.json`, copia cada candidato
(vóxeles + paleta) y sus planos de planta (`floors/floor_*.json`: salas con
rol + AABB), y adjunta el prompt en EN/ES/ZH →
`public/data/buildings/NN_<key>.json` + `public/data/index.json` (~3 MB total).

## Recogida de resultados

Todas las puntuaciones se guardan **siempre en el navegador** (`localStorage`):
el participante puede cerrar y continuar otro día sin perder nada. Para que
lleguen al investigador hay dos vías (la primera es la principal):

### 1. Botón "Enviar resultados al investigador" (correo, sin backend)

En el panel derecho, en cuanto hay ≥1 edificio puntuado, aparece **✉ Enviar
resultados al investigador**: manda el CSV completo por correo a
`RESULT_EMAIL` (`src/config.js`) usando [FormSubmit](https://formsubmit.co)
(no requiere servidor ni cuenta). También hay un **⬇ Descargar CSV (respaldo)**.

> **Activación (una sola vez).** La PRIMERA vez que alguien pulse "Enviar",
> FormSubmit manda un correo de confirmación a `RESULT_EMAIL`; abre ese correo
> y pulsa **Activate** / **Confirmar**. A partir de ahí, todos los envíos
> llegan a tu bandeja automáticamente. Recomendado: haz tú mismo un primer
> envío de prueba para activarlo antes de repartir el enlace a los jugadores.

Para cambiar el correo destino, edita `RESULT_EMAIL` en `src/config.js`.

### 2. (Opcional) Google Sheets vía Apps Script

Si prefieres que cada edificio completado se vuelque también a una hoja de
cálculo en vivo: crea una hoja con pestaña **`respuestas`**, pega este Apps
Script, despliégalo como **Aplicación web** (*Ejecutar como: yo*, *acceso:
cualquier usuario*) y copia la URL `/exec` en `src/config.js` → `APPS_SCRIPT_URL`:

```javascript
function doPost(e) {
  const d = JSON.parse(e.postData.contents);
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('respuestas');
  sheet.appendRow([
    d.timestamp, d.participantId, d.buildingNum, d.buildingKey,
    d.q1, d.q2, d.q3, d.q4, d.q5, d.q6, d.secondsExplored,
  ]);
  return ContentService.createTextOutput(JSON.stringify({ ok: true }))
    .setMimeType(ContentService.MimeType.JSON);
}
function doGet() { return ContentService.createTextOutput('ok'); }
```

> Ojo: si cambias el código del Apps Script, crea una **nueva versión** de la
> implementación (editar sin redeplegar sirve el código viejo). Si
> `APPS_SCRIPT_URL` está vacío, esta vía simplemente no se usa.

### Las 6 dimensiones (1–10)

`q1` Valoración global · `q2` Solidez y construcción · `q3` Interior habitable ·
`q4` Aspecto exterior · `q5` Sensación de buen lugar · `q6` Fidelidad a la
descripción. Cada una está alineada con una familia del evaluador automático
(global, físico, interior, exterior, Alexander, prompt) para la correlación
posterior.

## Deploy en Vercel

1. Sube el repo a GitHub (ya lo está) y entra en [vercel.com](https://vercel.com)
   → **Add New → Project** → importa `HomeCraft_v2Z`.
2. En la configuración del proyecto pon **Root Directory = `TEST_MC_PLAYERS`**.
   Vercel detecta Vite solo (build `npm run build`, salida `dist/`).
3. Cada `git push` redeploya. La URL pública (`*.vercel.app`) es la que se
   envía a los jugadores.

Requisitos del participante: **ordenador con ratón y teclado** (en móvil la web
muestra un aviso y no carga; el pointer lock no existe en táctil).

## Controles

| Tecla | Acción |
|---|---|
| clic en la pantalla | capturar el ratón y explorar |
| `WASD` / flechas | moverse |
| ratón | mirar |
| `Espacio` | saltar (en vuelo: subir) |
| `Shift` | (en vuelo) bajar |
| `F` o doble-espacio | alternar modo SUPER (volar + atravesar bloques) |
| `ESC` | soltar el ratón para puntuar en el panel derecho |

## Estructura

```
src/
├── App.jsx                  # layout 80/20
├── store.js                 # zustand: edificio actual, scores, modo, envíos
├── config.js                # APPS_SCRIPT_URL + las 8 dimensiones
├── components/
│   ├── World.jsx            # <Canvas>: cielo, luces, terreno, PointerLockControls
│   ├── VoxelBuilding.jsx    # InstancedMesh por entrada de paleta
│   ├── Player.jsx           # WASD + gravedad/colisiones o vuelo SUPER
│   ├── Sidebar.jsx          # lista de 20, prompt ES/EN/中文, pasos guiados
│   ├── FloorPlan.jsx        # plano 2D por planta (roles + jugador), sigue tu altura
│   ├── ScorePanel.jsx       # 8 × botones 1–10, no guarda hasta 8/8
│   └── Hud.jsx              # crosshair, overlays, bienvenida, botón SUPER
└── lib/
    ├── blocks/              # handlers de forma por familia (del visor del TFG)
    ├── blockstate.js        # texturas por cara + rotaciones 1.16.5
    ├── textures.js          # caché de texturas (CDN jsDelivr)
    ├── remap.js             # IDs inválidos → bloque 1.16.5 equivalente
    ├── physics.js           # Set de vóxeles + AABB por eje + step-up
    └── results.js           # localStorage + CSV + POST a Apps Script
```

---
*Estudio académico (TFG, UPC-FIB). No es un producto oficial de Minecraft; no
está aprobado por ni asociado con Mojang.*
