// Layout principal: canvas 3D (80%) + sidebar (20%).

import { useEffect } from 'react';
import { useStore } from './store.js';
import { BASE } from './config.js';
import World from './components/World.jsx';
import Sidebar from './components/Sidebar.jsx';
import Hud from './components/Hud.jsx';

export default function App() {
  const loadIndex = useStore((s) => s.loadIndex);

  useEffect(() => { loadIndex(BASE); }, [loadIndex]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-stone-900">
      {/* id="scene": PointerLockControls captura el cursor SOLO al hacer clic
          aquí (panel 3D). Así puntuar en el sidebar nunca re-bloquea el ratón. */}
      <main id="scene" className="relative" style={{ width: '80%' }}>
        <World />
        <Hud />
      </main>
      <div style={{ width: '20%', minWidth: 290 }}>
        <Sidebar />
      </div>
    </div>
  );
}
