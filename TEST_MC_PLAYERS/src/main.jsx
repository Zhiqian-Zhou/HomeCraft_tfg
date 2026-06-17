import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './index.css';

// Aviso si no hay ratón/teclado (móvil): el estudio requiere escritorio.
const isCoarse = window.matchMedia('(pointer: coarse)').matches;
if (isCoarse) {
  document.getElementById('root').innerHTML =
    '<div style="display:flex;height:100vh;align-items:center;justify-content:center;' +
    'font-family:system-ui;padding:2rem;text-align:center;color:#444">' +
    '<p><b>Este estudio requiere un ordenador con ratón y teclado.</b><br>' +
    'Por favor, ábrelo desde un PC o portátil. ¡Gracias!</p></div>';
} else {
  createRoot(document.getElementById('root')).render(<App />);
}
