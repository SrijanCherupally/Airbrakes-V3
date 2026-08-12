// 3D flight replay.
//
// The flight computer logs altitude, vertical velocity and attitude, but no
// GPS or lateral position. The vertical column of the trajectory is therefore
// measured; the ground track is RECONSTRUCTED from attitude (see
// buildTrajectory). The UI labels it as an estimate and it can be switched off.
//
// Rendering is a small painter's-algorithm renderer on a 2D canvas so the app
// gains no dependencies.
(function () {
  const api = window.groundStation;
  const $ = s => document.querySelector(s);
  const TAU = Math.PI * 2;
  const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
  const STATE_NAMES = ['IDLE', 'PAD', 'BOOST', 'CONTROL', 'DESCENT', 'LANDED', 'GND ARMED', 'GND REC'];
  const STATE_COLORS = ['#8b98a6', '#8b98a6', '#d97706', '#0f9488', '#be185d', '#15803d', '#7c3aed', '#7c3aed'];
  const INK = '#16202b', MUTED = '#68788a', ACCENT = '#0f9488';

  /* ---------------------------------------------------------------- math -- */
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  function lerpAngle(a, b, t) { let d = b - a; while (d > Math.PI) d -= TAU; while (d < -Math.PI) d += TAU; return a + d * t; }

  // R = Rz(yaw)·Ry(pitch)·Rx(roll); columns are the body axes in world frame.
  // Column 2 (body +Z) is the rocket's long axis, which is world-up when all
  // three angles are zero — matching the logged attitude on the pad.
  function eulerMatrix(roll, pitch, yaw) {
    const cr = Math.cos(roll), sr = Math.sin(roll);
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    const cy = Math.cos(yaw), sy = Math.sin(yaw);
    return [
      [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
      [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
      [-sp, cp * sr, cp * cr]
    ];
  }
  const applyM = (m, v) => [
    m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
    m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
    m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2]
  ];

  /* ----------------------------------------------------------------- csv -- */
  function parseCsv(text) {
    const lines = text.trim().split(/\r?\n/).filter(Boolean);
    if (lines.length < 2) throw new Error('CSV has no data rows.');
    const head = lines[0].split(',').map(s => s.trim());
    const need = ['time_ms', 'altitude_m', 'velocity_ms', 'roll_rad', 'pitch_rad', 'yaw_rad', 'state'];
    const missing = need.filter(k => !head.includes(k));
    if (missing.length) throw new Error(`Not an Airbrakes flight log — missing column(s): ${missing.join(', ')}`);
    const rows = [];
    for (let i = 1; i < lines.length; i++) {
      const cells = lines[i].split(',');
      if (cells.length < head.length) continue;
      const row = {};
      for (let c = 0; c < head.length; c++) { const n = Number(cells[c]); row[head[c]] = Number.isFinite(n) ? n : 0; }
      rows.push(row);
    }
    if (!rows.length) throw new Error('CSV has no usable data rows.');
    return rows;
  }

  /* ---------------------------------------------------------- trajectory -- */
  // Ground track model: an aerodynamically stable rocket flies close to its own
  // long axis, so |v| ≈ v_vertical / axis_z and the horizontal components fall
  // out of the axis direction. That assumption fails once the airframe is near
  // horizontal or descending under a chute, so the speed is clamped and descent
  // is damped. This produces a plausible track, never a measured one.
  function buildTrajectory(rows, useTrack) {
    const maxMotor = Math.max(...rows.map(r => Math.abs(r.motor_pos || 0)));
    const samples = [];
    let x = 0, y = 0, prevT = rows[0].time_ms / 1000;
    for (const r of rows) {
      const t = r.time_ms / 1000;
      const dt = clamp(t - prevT, 0, 0.1);
      prevT = t;
      const m = eulerMatrix(r.roll_rad, r.pitch_rad, r.yaw_rad);
      const axis = [m[0][2], m[1][2], m[2][2]];
      const vz = r.velocity_ms;
      let vx = 0, vy = 0;
      if (useTrack) {
        if (Math.abs(axis[2]) > 0.25) {
          const cap = Math.abs(vz) * 2.5 + 8;
          const speed = clamp(vz / axis[2], -cap, cap);
          vx = speed * axis[0];
          vy = speed * axis[1];
          if (r.state === 4 || r.state === 5) { vx *= 0.4; vy *= 0.4; } // chute drift, not axis-aligned
        }
        x += vx * dt;
        y += vy * dt;
      }
      samples.push({
        t, pos: [x, y, r.altitude_m], axis, vel: [vx, vy, vz],
        roll: r.roll_rad, pitch: r.pitch_rad, yaw: r.yaw_rad,
        alt: r.altitude_m, vz, accel: r.vertical_accel_ms2 || 0,
        cd: r.Cd || 0, desiredCd: r.desired_Cd || 0,
        motor: r.motor_pos || 0, brake: maxMotor > 1e-3 ? clamp(Math.abs(r.motor_pos || 0) / maxMotor, 0, 1) : 0,
        volts: r.battery_voltage || 0, state: r.state | 0
      });
    }
    let apogee = 0;
    for (let i = 0; i < samples.length; i++) if (samples[i].alt > samples[apogee].alt) apogee = i;
    const ext = samples.reduce((a, s) => ({
      x: [Math.min(a.x[0], s.pos[0]), Math.max(a.x[1], s.pos[0])],
      y: [Math.min(a.y[0], s.pos[1]), Math.max(a.y[1], s.pos[1])],
      z: [Math.min(a.z[0], s.pos[2]), Math.max(a.z[1], s.pos[2])]
    }), { x: [0, 0], y: [0, 0], z: [0, 0] });
    return {
      samples, apogee, extent: ext, maxMotor,
      duration: samples[samples.length - 1].t - samples[0].t,
      t0: samples[0].t,
      maxV: Math.max(...samples.map(s => Math.abs(s.vz))),
      maxA: Math.max(...samples.map(s => s.accel))
    };
  }

  // Sample the flight at an arbitrary time, interpolating between log rows.
  function sampleAt(traj, time) {
    const s = traj.samples;
    let i = 0, hi = s.length - 1;
    while (i < hi) { const mid = (i + hi + 1) >> 1; if (s[mid].t <= time) i = mid; else hi = mid - 1; }
    const a = s[i], b = s[Math.min(i + 1, s.length - 1)];
    const span = b.t - a.t;
    const f = span > 1e-6 ? clamp((time - a.t) / span, 0, 1) : 0;
    const mix = (p, q) => p + (q - p) * f;
    const roll = lerpAngle(a.roll, b.roll, f), pitch = lerpAngle(a.pitch, b.pitch, f), yaw = lerpAngle(a.yaw, b.yaw, f);
    return {
      index: i,
      pos: [mix(a.pos[0], b.pos[0]), mix(a.pos[1], b.pos[1]), mix(a.pos[2], b.pos[2])],
      matrix: eulerMatrix(roll, pitch, yaw),
      roll, pitch, yaw,
      vel: [mix(a.vel[0], b.vel[0]), mix(a.vel[1], b.vel[1]), mix(a.vel[2], b.vel[2])],
      alt: mix(a.alt, b.alt), vz: mix(a.vz, b.vz), accel: mix(a.accel, b.accel),
      cd: mix(a.cd, b.cd), desiredCd: mix(a.desiredCd, b.desiredCd),
      motor: mix(a.motor, b.motor), brake: mix(a.brake, b.brake),
      volts: mix(a.volts, b.volts), state: a.state, t: time
    };
  }

  /* ----------------------------------------------------------- rocket mesh */
  // Modelled on the actual airframe: slender white tube, long ogive nose, a
  // narrow teal band and a wider teal airbrake module below it, and three
  // swept fins with rounded tips. Proportions are taken off a side-on photo
  // and expressed as fractions of overall length, nose at +Z, tail at -Z.
  const BODY = [238, 237, 233];
  const METAL = [183, 185, 184];
  const TEAL = [55, 164, 174];
  const TEAL_DARK = [26, 101, 108];
  const INK_DARK = [33, 38, 42];
  const R = 0.036;
  const Z_TAIL = -0.5, Z_NOSE = 0.405, Z_TIP = 0.5;
  const Z_SHOULDER = 0.025, Z_MODULE_TOP = -0.010;
  const Z_MODULE_BOTTOM = -0.145, Z_LOWER_BOTTOM = -0.455;
  const FIN_SPAN = 0.070, FIN_ROOT = -0.405, FIN_TIP_Z = -0.492;

  function makeRocket(brake) {
    const faces = [];
    const N = 20;
    const ring = (z, r) => Array.from({ length: N }, (_, i) => [Math.cos(i / N * TAU) * r, Math.sin(i / N * TAU) * r, z]);

    // Main tubes and the stepped lower assembly from the reference profile.
    const sections = [
      [Z_TAIL, Z_LOWER_BOTTOM, 0.040, 0.040, TEAL_DARK],
      [Z_LOWER_BOTTOM, Z_MODULE_BOTTOM, R, R, BODY],
      [Z_MODULE_BOTTOM, Z_MODULE_BOTTOM + 0.010, 0.043, 0.043, TEAL],
      [Z_MODULE_BOTTOM + 0.010, Z_MODULE_TOP, 0.043, 0.043, TEAL],
      [Z_MODULE_TOP, Z_SHOULDER, 0.043, 0.043, TEAL],
      [Z_SHOULDER, Z_SHOULDER + 0.018, 0.043, R, METAL],
      [Z_SHOULDER + 0.018, Z_NOSE, R, R, BODY]
    ];
    for (const [z0, z1, r0, r1, color] of sections) {
      const lo = ring(z0, r0), hi = ring(z1, r1);
      for (let i = 0; i < N; i++) {
        const j = (i + 1) % N;
        faces.push({ pts: [lo[i], lo[j], hi[j], hi[i]], c: color, solid: true });
      }
    }
    for (const [z0, z1, color] of [[Z_MODULE_TOP - 0.004, Z_MODULE_TOP, TEAL_DARK], [Z_MODULE_BOTTOM - 0.004, Z_MODULE_BOTTOM, TEAL_DARK]]) {
      const lo = ring(z0, 0.044), hi = ring(z1, 0.044);
      for (let i = 0; i < N; i++) { const j = (i + 1) % N; faces.push({ pts: [lo[i], lo[j], hi[j], hi[i]], c: color, solid: true }); }
    }

    // Ogive nose — elliptical profile, stacked rings to keep the curve.
    const M = 7;
    let prev = ring(Z_NOSE, R);
    for (let s = 1; s <= M; s++) {
      const t = s / M;
      const r = s === M ? 0 : R * Math.sqrt(Math.max(0, 1 - t * t));
      const z = Z_NOSE + (Z_TIP - Z_NOSE) * t;
      const cur = ring(z, r);
      for (let i = 0; i < N; i++) {
        const j = (i + 1) % N;
        faces.push(s === M
          ? { pts: [prev[i], prev[j], [0, 0, Z_TIP]], c: BODY, solid: true }
          : { pts: [prev[i], prev[j], cur[j], cur[i]], c: BODY, solid: true });
      }
      prev = cur;
    }
    faces.push({ pts: ring(Z_TAIL, R).reverse(), c: METAL, solid: true });

    // Three broad, rounded lower fins; the third stays visible while orbiting.
    for (let k = 0; k < 3; k++) {
      const a = k / 3 * TAU, ca = Math.cos(a), sa = Math.sin(a);
      const pts = [[ca * R, sa * R, FIN_ROOT]];
      for (let i = 0; i <= 8; i++) {
        const th = i / 8 * Math.PI;
        const rr = R + FIN_SPAN * (0.68 + 0.32 * Math.sin(th));
        const z = FIN_ROOT - 0.010 + (FIN_TIP_Z - FIN_ROOT + 0.010) * (0.5 - 0.5 * Math.cos(th));
        pts.push([ca * rr, sa * rr, z]);
      }
      pts.push([ca * R, sa * R, Z_TAIL]);
      faces.push({ pts, c: [206, 207, 205] });
    }

    // Airbrake flaps, hinged inside the lower teal module.
    const open = brake * 0.055;
    for (let k = 0; k < 3; k++) {
      const a = k / 3 * TAU + Math.PI / 3, ca = Math.cos(a), sa = Math.sin(a);
      const r1 = R + 0.003 + open;
      const c = brake > 0.02 ? [72, 82, 94] : [30, 111, 118];
      faces.push({
        pts: [[ca * R, sa * R, Z_MODULE_TOP - 0.008], [ca * r1, sa * r1, Z_MODULE_TOP - 0.014],
        [ca * r1, sa * r1, Z_MODULE_BOTTOM + 0.014], [ca * R, sa * R, Z_MODULE_BOTTOM + 0.008]],
        c
      });
    }

    // Rail button, the one asymmetric feature — useful for reading roll.
    // Small body fasteners and a module access detail from the reference.
    for (const [zr, rr] of [[0.170, 0.008], [-0.015, 0.007]]) {
      faces.push({ pts: [[R, -rr, zr - rr], [R + 0.004, -rr, zr - rr], [R + 0.004, rr, zr + rr], [R, rr, zr + rr]], c: INK_DARK });
      faces.push({ pts: [[R + 0.004, -rr * 0.45, zr - rr * 0.45], [R + 0.006, -rr * 0.45, zr - rr * 0.45], [R + 0.006, rr * 0.45, zr + rr * 0.45], [R + 0.004, rr * 0.45, zr + rr * 0.45]], c: [150, 153, 150] });
    }
    const rb = 0.008, zr = -0.078;
    faces.push({ pts: [[R, -rb, zr - rb], [R + 0.006, -rb, zr - rb], [R + 0.006, rb, zr + rb], [R, rb, zr + rb]], c: INK_DARK });
    return faces;
  }

  /* ------------------------------------------------------------- renderer */
  // Direction the light travels, so -Z lights upward-facing surfaces.
  const LIGHT = norm([-0.4, -0.55, -0.73]);

  function makeCamera() { return { az: -0.9, el: 0.30, dist: 260, fov: 55, target: [0, 0, 60] }; }

  function viewBasis(cam, target) {
    const ce = Math.cos(cam.el), se = Math.sin(cam.el);
    const eye = [target[0] + cam.dist * ce * Math.cos(cam.az), target[1] + cam.dist * ce * Math.sin(cam.az), target[2] + cam.dist * se];
    const fwd = norm(sub(target, eye));
    const right = norm(cross(fwd, [0, 0, 1]));
    const up = cross(right, fwd);
    return { eye, fwd, right, up };
  }

  class Stage {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.cam = makeCamera();
      this.w = 0; this.h = 0; this.dpr = 0;
      this.resize();
      this.bindInput();
    }
    // Polled from the render loop rather than driven by ResizeObserver: the
    // replay view starts display:none, so the canvas measures zero until the
    // tab is first opened.
    syncSize() {
      const box = this.canvas.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      if (Math.abs(box.width - this.w) < 0.5 && Math.abs(box.height - this.h) < 0.5 && dpr === this.dpr) return false;
      this.resize();
      return true;
    }
    resize() {
      const box = this.canvas.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      this.w = Math.max(1, box.width); this.h = Math.max(1, box.height); this.dpr = dpr;
      this.canvas.width = Math.round(this.w * dpr);
      this.canvas.height = Math.round(this.h * dpr);
      this.canvas.style.width = this.w + 'px';
      this.canvas.style.height = this.h + 'px';
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    bindInput() {
      let drag = null;
      this.canvas.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY }; this.canvas.setPointerCapture(e.pointerId); });
      this.canvas.addEventListener('pointermove', e => {
        if (!drag) return;
        this.cam.az -= (e.clientX - drag.x) * 0.008;
        this.cam.el = clamp(this.cam.el + (e.clientY - drag.y) * 0.006, -1.45, 1.45);
        drag = { x: e.clientX, y: e.clientY };
      });
      const stop = () => { drag = null; };
      this.canvas.addEventListener('pointerup', stop);
      this.canvas.addEventListener('pointercancel', stop);
      this.canvas.addEventListener('wheel', e => {
        e.preventDefault();
        this.cam.dist = clamp(this.cam.dist * Math.exp(e.deltaY * 0.0012), 6, 4000);
      }, { passive: false });
    }
    begin(target) {
      const b = viewBasis(this.cam, target);
      this.basis = b;
      this.focal = (this.h / 2) / Math.tan(this.cam.fov * Math.PI / 360);
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.w, this.h);
      const sky = ctx.createLinearGradient(0, 0, 0, this.h);
      const dark = document.body.classList.contains('dark');
      sky.addColorStop(0, dark ? '#18212b' : '#fdfdfe'); sky.addColorStop(1, dark ? '#0e141b' : '#eef1f5');
      ctx.fillStyle = sky; ctx.fillRect(0, 0, this.w, this.h);
    }
    project(p) {
      const d = sub(p, this.basis.eye);
      const z = dot(d, this.basis.fwd);
      if (z <= 0.05) return null;
      const k = this.focal / z;
      return { x: this.w / 2 + dot(d, this.basis.right) * k, y: this.h / 2 - dot(d, this.basis.up) * k, z, k };
    }
    line(a, b, color, width = 1, alpha = 1) {
      const p = this.project(a), q = this.project(b);
      if (!p || !q) return;
      const ctx = this.ctx;
      ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.lineWidth = width;
      ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    label(p3, text, color, dy = 0) {
      const p = this.project(p3);
      if (!p) return;
      const ctx = this.ctx;
      ctx.font = '600 11px Inter, system-ui, sans-serif';
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      const w = ctx.measureText(text).width;
      ctx.fillStyle = 'rgba(255,255,255,.86)';
      ctx.fillRect(p.x + 7, p.y + dy - 8, w + 10, 16);
      ctx.fillStyle = color;
      ctx.fillText(text, p.x + 12, p.y + dy);
    }
    // Depth-sorted, flat-shaded triangles/quads.
    mesh(faces) {
      const out = [];
      for (const f of faces) {
        const pts = f.pts.map(p => this.project(p));
        if (pts.some(p => !p)) continue;
        const n = norm(cross(sub(f.pts[1], f.pts[0]), sub(f.pts[2], f.pts[0])));
        const facing = dot(n, sub(f.pts[0], this.basis.eye));
        if (f.solid && facing > 0) continue;              // backface cull closed bodies
        // Directional light plus a camera-facing ("headlight") term. Without the
        // headlight, a vertical cylinder seen side-on shows only normals that
        // are horizontal — most of them facing away from the light — and a white
        // airframe renders mid-grey.
        const centroid = f.pts.reduce((s, p) => [s[0] + p[0] / f.pts.length, s[1] + p[1] / f.pts.length, s[2] + p[2] / f.pts.length], [0, 0, 0]);
        const toEye = norm(sub(this.basis.eye, centroid));
        const lit = f.solid ? Math.max(0, -dot(n, LIGHT)) : Math.abs(dot(n, LIGHT));
        const head = Math.abs(dot(n, toEye));
        const sh = Math.min(1, 0.55 + 0.18 * lit + 0.42 * head);
        out.push({ pts, depth: f.pts.reduce((s, p) => s + dot(sub(p, this.basis.eye), this.basis.fwd), 0) / f.pts.length, c: f.c, sh });
      }
      out.sort((a, b) => b.depth - a.depth);
      const ctx = this.ctx;
      for (const f of out) {
        ctx.beginPath();
        ctx.moveTo(f.pts[0].x, f.pts[0].y);
        for (let i = 1; i < f.pts.length; i++) ctx.lineTo(f.pts[i].x, f.pts[i].y);
        ctx.closePath();
        // Stroked in its own fill colour: the model is ~150 facets, and any
        // contrasting outline turns into solid ink once the rocket is small on
        // screen. This only closes the anti-aliasing seams between facets.
        ctx.fillStyle = `rgb(${Math.round(f.c[0] * f.sh)},${Math.round(f.c[1] * f.sh)},${Math.round(f.c[2] * f.sh)})`;
        ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = 0.5;
        ctx.fill(); ctx.stroke();
      }
    }
  }

  /* ------------------------------------------------------------------- app */
  const ui = {};
  let traj = null, rows = null, stage = null;
  let time = 0, playing = false, speed = 1, lastFrame = 0;
  let camMode = 'follow', showTrack = true, showGrid = true, showShadow = true, showVec = true, rocketSize = 20;
  let sourceName = '';

  function fmt(v, d = 1) { return Number.isFinite(v) ? v.toFixed(d) : '--'; }

  function gridStep(span) {
    const raw = span / 6;
    const pow = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
    const n = raw / pow;
    return (n >= 5 ? 5 : n >= 2 ? 2 : 1) * pow;
  }

  function drawGround(reach) {
    const step = gridStep(reach * 2);
    const lim = Math.ceil(reach / step) * step;
    for (let g = -lim; g <= lim + 1e-6; g += step) {
      const major = Math.abs(g) < 1e-6;
      const col = major ? 'rgba(15,148,136,.38)' : 'rgba(110,132,155,.22)';
      stage.line([g, -lim, 0], [g, lim, 0], col, major ? 1.4 : 1);
      stage.line([-lim, g, 0], [lim, g, 0], col, major ? 1.4 : 1);
    }
    // range rings every step, labelled
    for (let r = step; r <= lim + 1e-6; r += step) {
      let prev = null;
      for (let i = 0; i <= 64; i++) {
        const a = i / 64 * TAU, p = [Math.cos(a) * r, Math.sin(a) * r, 0];
        if (prev) stage.line(prev, p, 'rgba(110,132,155,.20)', 1);
        prev = p;
      }
      stage.label([r, 0, 0], `${r >= 1000 ? (r / 1000).toFixed(1) + ' km' : r + ' m'}`, MUTED);
    }
    // launch pad
    let prev = null;
    for (let i = 0; i <= 32; i++) {
      const a = i / 32 * TAU, p = [Math.cos(a) * step * 0.10, Math.sin(a) * step * 0.10, 0];
      if (prev) stage.line(prev, p, '#15803d', 2);
      prev = p;
    }
    stage.label([0, 0, 0], 'PAD', '#15803d', 14);
  }

  function drawTrail(upto) {
    const s = traj.samples;
    for (let i = 1; i <= upto && i < s.length; i++) {
      const c = STATE_COLORS[s[i].state] || '#91a7bf';
      stage.line(s[i - 1].pos, s[i].pos, c, 2.4, 0.95);
      if (showTrack && showShadow) stage.line([s[i - 1].pos[0], s[i - 1].pos[1], 0], [s[i].pos[0], s[i].pos[1], 0], c, 1.2, 0.28);
    }
    // remaining path, ghosted, so the whole flight reads at a glance
    for (let i = Math.max(1, upto + 1); i < s.length; i++) {
      stage.line(s[i - 1].pos, s[i].pos, '#b3bdc8', 1.2, 0.6);
    }
  }

  function drawRocket(cur) {
    const size = rocketSize;
    const faces = makeRocket(cur.brake).map(f => ({
      ...f,
      pts: f.pts.map(p => {
        const w = applyM(cur.matrix, [p[0] * size, p[1] * size, p[2] * size]);
        return [w[0] + cur.pos[0], w[1] + cur.pos[1], w[2] + cur.pos[2]];
      })
    }));
    stage.mesh(faces);
  }

  function draw() {
    if (!traj) return;
    const cur = sampleAt(traj, time);
    const reach = Math.max(30, traj.extent.z[1] * 0.85,
      Math.abs(traj.extent.x[0]), traj.extent.x[1], Math.abs(traj.extent.y[0]), traj.extent.y[1]);

    // camera target / framing per mode
    let target = cur.pos;
    if (camMode === 'world') {
      target = [(traj.extent.x[0] + traj.extent.x[1]) / 2, (traj.extent.y[0] + traj.extent.y[1]) / 2, traj.extent.z[1] / 2];
    } else if (camMode === 'pad') {
      target = cur.pos;
      const d = Math.hypot(cur.pos[0], cur.pos[1], cur.pos[2]);
      stage.cam.dist = Math.max(d * 1.05, 25);
      stage.cam.el = Math.asin(clamp(cur.pos[2] / Math.max(d, 1e-3), -1, 1)) * 0.92 + 0.05;
      stage.cam.az = Math.atan2(cur.pos[1], cur.pos[0]) + Math.PI;
    } else if (camMode === 'chase') {
      const v = cur.vel;
      if (Math.hypot(v[0], v[1]) > 0.5) stage.cam.az = Math.atan2(v[1], v[0]) + Math.PI;
    }

    stage.begin(target);
    if (showGrid) drawGround(reach);
    drawTrail(cur.index);

    if (showShadow) {
      stage.line([cur.pos[0], cur.pos[1], 0], cur.pos, 'rgba(15,148,136,.32)', 1);
      let prev = null;
      const r = rocketSize * 0.32;
      for (let i = 0; i <= 24; i++) {
        const a = i / 24 * TAU, p = [cur.pos[0] + Math.cos(a) * r, cur.pos[1] + Math.sin(a) * r, 0];
        if (prev) stage.line(prev, p, 'rgba(70,90,112,.40)', 1.2);
        prev = p;
      }
    }

    // apogee marker
    const ap = traj.samples[traj.apogee];
    let prev = null;
    for (let i = 0; i <= 32; i++) {
      const a = i / 32 * TAU, p = [ap.pos[0] + Math.cos(a) * rocketSize * 0.5, ap.pos[1] + Math.sin(a) * rocketSize * 0.5, ap.pos[2]];
      if (prev) stage.line(prev, p, '#c2670a', 1.6, 0.9);
      prev = p;
    }
    stage.label(ap.pos, `APOGEE ${fmt(ap.alt)} m · T+${fmt(ap.t, 2)}s`, '#c2670a');

    if (showVec) {
      const v = cur.vel, m = Math.hypot(v[0], v[1], v[2]);
      if (m > 0.5) {
        const k = rocketSize * 1.6 / Math.max(m, 1) * Math.min(m / 20, 2.2);
        stage.line(cur.pos, [cur.pos[0] + v[0] * k, cur.pos[1] + v[1] * k, cur.pos[2] + v[2] * k], '#15803d', 2.2, 0.95);
      }
      const ax = cur.matrix, a = [ax[0][2], ax[1][2], ax[2][2]], k = rocketSize * 1.1;
      stage.line(cur.pos, [cur.pos[0] + a[0] * k, cur.pos[1] + a[1] * k, cur.pos[2] + a[2] * k], '#be185d', 1.6, 0.8);
    }

    drawRocket(cur);
    updateHud(cur);
  }

  function updateHud(cur) {
    const tilt = Math.acos(clamp(cur.matrix[2][2], -1, 1)) * 180 / Math.PI;
    const set = (id, v) => { const e = ui[id]; if (e) e.textContent = v; };
    set('t', `T+${fmt(cur.t, 2)} s`);
    set('alt', `${fmt(cur.alt)} m`);
    set('vel', `${fmt(cur.vz)} m/s`);
    set('acc', `${fmt(cur.accel)} m/s²`);
    set('state', STATE_NAMES[cur.state] || `STATE ${cur.state}`);
    set('tilt', `${fmt(tilt)}°`);
    set('cd', `${fmt(cur.cd, 3)} → ${fmt(cur.desiredCd, 3)}`);
    set('brake', traj.maxMotor > 1e-3 ? `${fmt(cur.brake * 100, 0)}%` : 'closed (no travel logged)');
    set('volts', `${fmt(cur.volts, 2)} V`);
    set('rng', showTrack ? `${fmt(Math.hypot(cur.pos[0], cur.pos[1]))} m (est.)` : 'not modelled');
    const badge = ui.state;
    if (badge) badge.style.color = STATE_COLORS[cur.state] || '#91a7bf';
    if (ui.scrub && document.activeElement !== ui.scrub) ui.scrub.value = String(cur.t);
    if (ui.brakeBar) ui.brakeBar.style.width = `${clamp(cur.brake * 100, 0, 100)}%`;
  }

  function frame(now) {
    requestAnimationFrame(frame);
    const dt = lastFrame ? Math.min((now - lastFrame) / 1000, 0.1) : 0;
    lastFrame = now;
    if (!traj || !$('#replay')?.classList.contains('active')) return;
    stage.syncSize();
    if (playing) {
      time += dt * speed;
      if (time >= traj.t0 + traj.duration) { time = traj.t0 + traj.duration; setPlaying(false); }
    }
    draw();
  }

  function setPlaying(v) {
    playing = v;
    if (ui.play) { ui.play.textContent = v ? '❚❚ Pause' : '▶ Play'; ui.play.classList.toggle('primary', !v); }
  }

  function frameCamera() {
    if (!traj) return;
    const reach = Math.max(40, traj.extent.z[1],
      Math.abs(traj.extent.x[0]), traj.extent.x[1], Math.abs(traj.extent.y[0]), traj.extent.y[1]);
    // Follow distance is deliberately independent of rocketSize. Tying the two
    // together keeps the model at a fixed fraction of the viewport, which makes
    // the size slider do nothing visible — and a faithful 1:30 airframe at that
    // fraction is only a couple of pixels wide.
    stage.cam.dist = camMode === 'world' ? reach * 2.4 : clamp(reach * 0.5, 25, 400);
    stage.cam.el = 0.30;
    stage.cam.az = -0.9;
  }

  function load(text, name) {
    rows = parseCsv(text);
    sourceName = name;
    rebuild(true);
  }

  function rebuild(reframe) {
    traj = buildTrajectory(rows, showTrack);
    time = traj.t0;
    setPlaying(false);
    if (ui.scrub) { ui.scrub.min = String(traj.t0); ui.scrub.max = String(traj.t0 + traj.duration); ui.scrub.step = '0.005'; ui.scrub.value = String(traj.t0); }
    rocketSize = Number(ui.size?.value || 20);
    if (reframe) frameCamera();
    ui.file.textContent = `${sourceName} · ${traj.samples.length} samples · ${fmt(traj.duration, 2)} s · apogee ${fmt(traj.samples[traj.apogee].alt)} m · max ${fmt(traj.maxV)} m/s`;
    draw();
  }

  /* --------------------------------------------------------------- wiring */
  function init() {
    const canvas = $('#r3dCanvas');
    if (!canvas) return;
    stage = new Stage(canvas);
    Object.assign(ui, {
      file: $('#r3dFile'), play: $('#r3dPlay'), scrub: $('#r3dScrub'), size: $('#r3dSize'),
      t: $('#r3dT'), alt: $('#r3dAlt'), vel: $('#r3dVel'), acc: $('#r3dAcc'), state: $('#r3dState'),
      tilt: $('#r3dTilt'), cd: $('#r3dCd'), brake: $('#r3dBrake'), volts: $('#r3dVolts'), rng: $('#r3dRng'),
      brakeBar: $('#r3dBrakeBar')
    });

    $('#r3dOpen').onclick = async () => {
      try {
        const r = await api.pickCsv();
        if (!r) return;
        load(r.text, r.name || r.file);
      } catch (e) { ui.file.textContent = `Could not open: ${e.message}`; }
    };
    $('#r3dLocal').onchange = async e => {
      if (!e.target.value) return;
      try { const r = await api.readCsv(e.target.value); load(r.text, r.name || r.file); }
      catch (err) { ui.file.textContent = `Could not read: ${err.message}`; }
    };
    async function refreshLocal() {
      const sel = $('#r3dLocal');
      sel.innerHTML = '<option value="">Saved logs…</option>';
      for (const cat of ['flights', 'ground_tests']) {
        for (const e of await api.localEntries(cat)) sel.add(new Option(`${e.folder} (${e.num_records || 0} rec)`, e.path));
      }
    }
    $('#r3dRefresh').onclick = refreshLocal;
    refreshLocal().catch(() => {});

    ui.play.onclick = () => { if (!traj) return; if (time >= traj.t0 + traj.duration - 1e-6) time = traj.t0; setPlaying(!playing); };
    $('#r3dRestart').onclick = () => { if (traj) { time = traj.t0; draw(); } };
    $('#r3dApogee').onclick = () => { if (traj) { time = traj.samples[traj.apogee].t; setPlaying(false); draw(); } };
    ui.scrub.oninput = e => { if (!traj) return; time = Number(e.target.value); setPlaying(false); draw(); };
    $('#r3dSpeed').onchange = e => { speed = Number(e.target.value); };
    $('#r3dCam').onchange = e => { camMode = e.target.value; if (camMode !== 'pad') frameCamera(); draw(); };
    ui.size.oninput = e => { rocketSize = Number(e.target.value); $('#r3dSizeVal').textContent = `${rocketSize} m`; draw(); };
    $('#r3dFit').onclick = () => { frameCamera(); draw(); };
    const toggle = (id, fn) => { const el = $(id); el.onchange = () => { fn(el.checked); if (traj) draw(); }; };
    toggle('#r3dGrid', v => showGrid = v);
    toggle('#r3dShadow', v => showShadow = v);
    toggle('#r3dVec', v => showVec = v);
    $('#r3dTrack').onchange = e => { showTrack = e.target.checked; if (rows) rebuild(true); };

    window.addEventListener('keydown', e => {
      if (!traj || !$('#replay').classList.contains('active')) return;
      if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || '')) return;
      if (e.code === 'Space') { e.preventDefault(); ui.play.click(); }
      else if (e.code === 'ArrowRight') { time = Math.min(traj.t0 + traj.duration, time + (e.shiftKey ? 0.5 : 0.05)); setPlaying(false); draw(); }
      else if (e.code === 'ArrowLeft') { time = Math.max(traj.t0, time - (e.shiftKey ? 0.5 : 0.05)); setPlaying(false); draw(); }
    });

    requestAnimationFrame(frame);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
