// First-person fly controls.
//
// Wraps Three.js PointerLockControls and layers WASD movement + space (up)
// + shift (down) on top. No collision — you fly through walls.
//
//   const fps = new FpsControls(camera, domElement);
//   fps.enable();   // requests pointer lock and starts the input loop
//   fps.disable();  // releases pointer lock and stops moving
//   fps.update(dt); // call in the render loop while enabled
//
// Movement is camera-relative: W moves forward in the direction the camera
// is facing (projected onto the XZ plane for horizontal flight that feels
// natural; pitch only affects look, not movement). Space/Shift do pure Y.

import * as THREE from 'three';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';

// Slower defaults so indoor exploration is easy to control. Hold Ctrl to
// sprint across large exteriors.
const SPEED_NORMAL = 6;    // blocks / second (was 18 — too fast to control indoors)
const SPEED_FAST   = 16;   // hold Ctrl to sprint (was 45)

export class FpsControls {
  constructor(camera, domElement) {
    this.camera = camera;
    this.domElement = domElement;
    this.controls = new PointerLockControls(camera, domElement);
    // Gentler mouse look so it's easier to aim while exploring (default 1.0).
    this.controls.pointerSpeed = 0.55;

    this.keys = { w: false, a: false, s: false, d: false, space: false, shift: false, ctrl: false };
    this.enabled = false;

    this._onKeyDown = this._onKeyDown.bind(this);
    this._onKeyUp = this._onKeyUp.bind(this);
    this._onLock = this._onLock.bind(this);
    this._onUnlock = this._onUnlock.bind(this);

    this.controls.addEventListener('lock', this._onLock);
    this.controls.addEventListener('unlock', this._onUnlock);

    this._velocity = new THREE.Vector3();
    this._forward = new THREE.Vector3();
    this._right = new THREE.Vector3();
    this._up = new THREE.Vector3(0, 1, 0);

    // Listeners for unlock callback (so app.js can toggle UI back to orbit)
    this._onExitCallbacks = [];
  }

  onExit(cb) { this._onExitCallbacks.push(cb); }

  enable() {
    if (this.enabled) return;
    this.controls.lock();
  }

  disable() {
    if (!this.enabled) return;
    this.controls.unlock();
  }

  _onLock() {
    this.enabled = true;
    window.addEventListener('keydown', this._onKeyDown);
    window.addEventListener('keyup', this._onKeyUp);
  }

  _onUnlock() {
    this.enabled = false;
    window.removeEventListener('keydown', this._onKeyDown);
    window.removeEventListener('keyup', this._onKeyUp);
    Object.keys(this.keys).forEach(k => this.keys[k] = false);
    for (const cb of this._onExitCallbacks) cb();
  }

  _onKeyDown(e) {
    switch (e.code) {
      case 'KeyW': this.keys.w = true; break;
      case 'KeyA': this.keys.a = true; break;
      case 'KeyS': this.keys.s = true; break;
      case 'KeyD': this.keys.d = true; break;
      case 'Space': this.keys.space = true; e.preventDefault(); break;
      case 'ShiftLeft': case 'ShiftRight': this.keys.shift = true; break;
      case 'ControlLeft': case 'ControlRight': this.keys.ctrl = true; break;
    }
  }

  _onKeyUp(e) {
    switch (e.code) {
      case 'KeyW': this.keys.w = false; break;
      case 'KeyA': this.keys.a = false; break;
      case 'KeyS': this.keys.s = false; break;
      case 'KeyD': this.keys.d = false; break;
      case 'Space': this.keys.space = false; break;
      case 'ShiftLeft': case 'ShiftRight': this.keys.shift = false; break;
      case 'ControlLeft': case 'ControlRight': this.keys.ctrl = false; break;
    }
  }

  update(dt) {
    if (!this.enabled) return;
    const speed = (this.keys.ctrl ? SPEED_FAST : SPEED_NORMAL) * dt;

    // forward = camera direction projected to XZ
    this.camera.getWorldDirection(this._forward);
    this._forward.y = 0;
    if (this._forward.lengthSq() > 0) this._forward.normalize();
    this._right.crossVectors(this._forward, this._up).normalize();

    this._velocity.set(0, 0, 0);
    if (this.keys.w) this._velocity.addScaledVector(this._forward,  speed);
    if (this.keys.s) this._velocity.addScaledVector(this._forward, -speed);
    if (this.keys.d) this._velocity.addScaledVector(this._right,    speed);
    if (this.keys.a) this._velocity.addScaledVector(this._right,   -speed);
    if (this.keys.space) this._velocity.y += speed;
    if (this.keys.shift) this._velocity.y -= speed;

    this.camera.position.add(this._velocity);
  }

  /** Set the player's eye position to a sensible spot inside the AABB. */
  placeAt(x, y, z) {
    this.camera.position.set(x, y, z);
  }
}
