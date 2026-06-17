# Validación del evaluador automático frente al juicio humano

Código y datos del estudio que valida el evaluador automático de edificios (5
familias + compuesta) contra el consenso de **13 jugadores de Minecraft**
anonimizados (`P01`…`P13`) que puntuaron **20 escenas** en **6 preguntas**
(escala 1–10). Reproduce el informe de validación final usado en la memoria
(§ "Validating the evaluator against human judgement" y § "Agreement with human
judgement", Apéndice de validación humana).

## Archivos

- `human_ratings.csv` — datos crudos **anonimizados**: `rater (P01..P13),
  scene_num, key, q1..q6, seconds`. (260 filas = 13 × 20.)
- `auto_scores.csv` — puntuaciones del evaluador por escena: `scene_num,
  type_style, key, fisicas, interior, exterior, alexander, prompt, compuesta`.
  El `Exterior` ausente (escenas 4 y 12) se trata como `0` ("sin exterior
  evaluable" = peor valor posible).
- `analysis.py` — análisis completo (numpy + scipy).

## Emparejamiento pregunta → familia (la "diagonal" que se valida)

`q1` global ↔ compuesta · `q2` solidez ↔ física · `q3` interior ↔ interior ·
`q4` exterior ↔ exterior · `q5` sensación de lugar ↔ Alexander ·
`q6` fidelidad ↔ prompt.

## Qué calcula `analysis.py`

1. **Diagonal** pregunta↔familia: Pearson y Spearman sobre las 20 escenas
   (con n=20, |r|≳0.44 para p<0.05).
2. **Agregados**: media humana de las 6 preguntas vs compuesta, y media humana
   vs media de las 5 familias.
3. **Acuerdo inter-evaluador** `r₁`: correlación media por pares, calculada por
   pregunta y promediada (alimenta Spearman-Brown).
4. **Fiabilidad de Spearman-Brown** `R_k = k·r₁ / (1+(k−1)·r₁)` y nº de
   evaluadores por banda (0.70 / 0.80 / 0.90).
5. **Convergencia**: correlación según el nº de evaluadores promediados (1→13).
6. **Robustez**: agregado al excluir evaluadores.
7. **Detección de atípicos**: z-score modificado (mediana/MAD) sobre el acuerdo
   de cada evaluador con el consenso; criterio |z|>3.5.

## Resultados (reproducidos)

- Diagonal (Pearson): compuesta 0.826, interior 0.790, exterior 0.733,
  física 0.659, Alexander 0.630, prompt 0.596 — **las seis significativas**.
- Agregado media humana vs media métricas: **0.840**.
- `r₁ = 0.449` → fiabilidad de la media de 13 evaluadores **0.914** ("excelente");
  para 0.90 hacen falta 12, así que 13 la supera.
- Convergencia: las correlaciones se estabilizan hacia ~6 evaluadores.
- Robustez: el agregado se mantiene (~0.84) al excluir evaluadores; **0 atípicos**.

## Uso

```bash
pip install numpy scipy
python3 analysis.py
```

Los nombres reales de los participantes no se almacenan; solo los códigos
anónimos `P01`…`P13`.
