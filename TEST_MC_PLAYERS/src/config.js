// Configuración de la app de evaluación.

// URL del Web App de Google Apps Script que escribe las respuestas en una
// hoja de Google Sheets (ver README.md, sección "Recogida de resultados").
// Mientras esté vacío, la app funciona igualmente: las respuestas se guardan
// en el navegador (localStorage) y se descargan como CSV al final.
export const APPS_SCRIPT_URL = '';

// Correo del investigador al que llegan los resultados con el botón "Enviar".
// El envío usa FormSubmit (sin backend); la primera vez hay que activarlo
// haciendo clic en el correo de confirmación (ver README).
export const RESULT_EMAIL = ''; // set your own FormSubmit email to enable the "Enviar" button

// Las 6 dimensiones de calidad, una por cada familia del evaluador
// (Global, Físico, Interior, Exterior, Alexander, Prompt), en lenguaje de
// jugador. Escala 1–10. `label` = título corto, `question` = enunciado.
export const DIMENSIONS = [
  { id: 'q1', label: 'Valoración global',
    question: 'En conjunto, como jugador, ¿qué nota le pones a este edificio?' },
  { id: 'q2', label: 'Solidez y construcción',
    question: '¿Está bien construido? ¿Se aguanta sin bloques flotando ni agujeros raros, y puedes recorrerlo entero?' },
  { id: 'q3', label: 'Interior habitable',
    question: 'Por dentro, ¿es cómodo? Habitaciones con espacio, muebles, altura para moverte y luz suficiente (no a oscuras).' },
  { id: 'q4', label: 'Aspecto exterior',
    question: 'Por fuera, ¿está bien rematado? Paredes y tejado completos, sin huecos en el casco; ¿te gusta cómo queda?' },
  { id: 'q5', label: 'Sensación de buen lugar',
    question: '¿Se siente como un sitio real y agradable? Entrada clara, buena separación entre zonas comunes y privadas, luz natural y un tejado que cobija.' },
  { id: 'q6', label: 'Fidelidad a la descripción',
    question: '¿Se parece a lo que pedía el texto? El tipo de edificio, los materiales y las partes que menciona.' },
];

export const BASE = import.meta.env.BASE_URL; // raíz de assets (Vite)
