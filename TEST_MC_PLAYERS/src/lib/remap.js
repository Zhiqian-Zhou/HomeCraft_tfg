// Remap de IDs de bloque que NO existen en Minecraft Java 1.16.5 pero que
// aparecen en las paletas de los 20 edificios (alucinaciones del LLM o bloques
// 1.17+). Se sustituyen por el bloque 1.16.5 visualmente más parecido ANTES
// de resolver el handler, así cada uno se renderiza con textura real en vez
// del gris de "textura no encontrada". Las props del blockstate (facing,
// half, axis…) se conservan.

const BLOCK_REMAP = {
  // alucinaciones / nombres incompletos
  amphora: 'terracotta',
  podium: 'lectern',
  paper: 'white_wool',                  // muros de papel (edificios japoneses)
  concrete_pillar: 'white_concrete',
  dark_oak_beam: 'dark_oak_log',
  oak_nightstand: 'oak_planks',
  golden_rod: 'end_rod',
  dark_oak: 'dark_oak_planks',
  wool: 'white_wool',
  carpet: 'white_carpet',
  // camas "de madera" (las camas reales de MC van por color → entity/bed/<color>.png)
  oak_bed: 'white_bed',
  dark_oak_bed: 'brown_bed',
  dark_oak_beds: 'brown_bed',
  cherry_wood_fence: 'crimson_fence',
  white_concrete_wall: 'diorite_wall',
  pale_stone_slab: 'polished_diorite_slab',
  pale_stone_stairs: 'polished_diorite_stairs',
  red_banner: 'red_wool',
  // antorchas "de madera" inventadas (las antorchas no tienen variantes)
  spruce_wall_torch: 'wall_torch',
  dark_oak_wall_torch: 'wall_torch',
  armor_stand: 'oak_fence',             // entidad, no bloque: se ve como poste
  // macetas: se renderizan como la flor que contienen (cruz de planta)
  potted_poppy: 'poppy',
  // bloques 1.17+
  amethyst_block: 'purpur_block',
  candle: 'torch',
  flowering_azalea_leaves: 'oak_leaves',
};

/** Devuelve el nombre 1.16.5 equivalente (o el mismo si ya es válido). */
export function remapName(name) {
  return BLOCK_REMAP[name] ?? name;
}
