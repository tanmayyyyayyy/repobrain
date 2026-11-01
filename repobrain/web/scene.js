/* RepoBrain 3D scene: a raw WebGL2 point-cloud (no libraries, works offline).
 *  - A procedural "brain" made of ~70k points, shaded lavender -> acid lime.
 *  - A morph target: a CONSTELLATION where each changed file is a cluster, coloured by its real verdict.
 *  - Cursor swirl/repel, dive-in, dust dissolve, shock-wave pulses, and a mood (turbulence/threat) driven by repo data.
 * The scene draws into a sub-rectangle of one fixed full-window canvas, so the stage can resize with scroll for free. */
(function () {
  const TAU = Math.PI * 2;
  function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
  const fract = (x) => x - Math.floor(x);
  const hash = (x, y, z) => fract(Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453);
  const smooth = (t) => t * t * (3 - 2 * t);
  function vnoise(x, y, z) {
    const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z), xf = smooth(x - xi), yf = smooth(y - yi), zf = smooth(z - zi);
    const l = (a, b, t) => a + (b - a) * t;
    return l(l(l(hash(xi, yi, zi), hash(xi + 1, yi, zi), xf), l(hash(xi, yi + 1, zi), hash(xi + 1, yi + 1, zi), xf), yf),
      l(l(hash(xi, yi, zi + 1), hash(xi + 1, yi, zi + 1), xf), l(hash(xi, yi + 1, zi + 1), hash(xi + 1, yi + 1, zi + 1), xf), yf), zf);
  }
  const ridged = (x, y, z) => 1 - Math.abs(vnoise(x, y, z) * 2 - 1);

  /* ---------- procedural brain ---------- */
  function buildBrain(N) {
    const r = rng(7), A = new Float32Array(N * 3), Nm = new Float32Array(N * 3), M = new Float32Array(N * 4);
    const gauss = () => { let a = 0; for (let i = 0; i < 6; i++) a += r(); return (a - 3) / 1.0; };
    for (let i = 0; i < N; i++) {
      const pick = r();
      let x, y, z, nx, ny, nz;
      if (pick < 0.82) {                                 // cerebrum: two hemispheres
        const h = r() < 0.5 ? -1 : 1;
        let dx = gauss(), dy = gauss(), dz = gauss(); const l = Math.hypot(dx, dy, dz) || 1; dx /= l; dy /= l; dz /= l;
        const u = dx * h;                                // >0 outer side, <0 faces the midline
        const g = ridged(dx * 2.7 + h * 3.1, dy * 2.7, dz * 2.7) * 0.62 + vnoise(dx * 7, dy * 7, dz * 7 + h) * 0.38;
        const disp = 1 + 0.085 * (g - 0.5) * 2;
        const ax = u >= 0 ? 0.62 + 0.62 * u * disp : 0.05 + 0.57 * Math.pow(1 + u, 0.6);   // inner face flattens toward the fissure
        x = h * ax; y = 0.12 + 0.8 * dy * disp; z = 1.12 * dz * disp; const sx = dx;
        if (y < -0.34) y = -0.34 + (y + 0.34) * 0.35;    // flatter underside
        nx = sx / 0.62; ny = dy / 0.8; nz = dz / 1.12;
      } else if (pick < 0.93) {                          // cerebellum with fine striations
        let dx = gauss(), dy = gauss(), dz = gauss(); const l = Math.hypot(dx, dy, dz) || 1; dx /= l; dy /= l; dz /= l;
        const d = 1 + 0.06 * Math.sin(dy * 34);
        x = 0.56 * dx * d; y = -0.62 + 0.27 * dy * d; z = -0.82 + 0.42 * dz * d; nx = dx; ny = dy; nz = dz;
      } else {                                           // brain stem
        const t = r(), th = r() * TAU, rad = 0.13 * (1 - 0.35 * t);
        x = rad * Math.cos(th); z = -0.3 + rad * Math.sin(th) + 0.18 * t; y = -0.5 - 0.75 * t; nx = Math.cos(th); ny = 0; nz = Math.sin(th);
      }
      const nl = Math.hypot(nx, ny, nz) || 1;
      A.set([x, y, z], i * 3); Nm.set([nx / nl, ny / nl, nz / nl], i * 3);
      M[i * 4] = r(); M[i * 4 + 1] = Math.max(0, Math.min(1, (y + 1.1) / 1.9)); M[i * 4 + 2] = -1; M[i * 4 + 3] = r();
    }
    return { A, N: Nm, M };
  }

  const VS = `#version 300 es
precision highp float;
in vec3 aA; in vec3 aB; in vec3 aN; in vec4 aM;
uniform mat4 uProj; uniform float uTime, uMix, uCam, uYaw, uPitch, uDissolve, uTurb, uThreat, uAspect, uDpr, uSize, uPulseT, uMouseOn, uSel, uHover;
uniform vec2 uMouse; uniform vec3 uGroupCol[32]; uniform vec3 uPulseCol;
out vec3 vCol; out float vA;
vec3 flow(vec3 p, float t){ return vec3(sin(p.y*2.1+t)+sin(p.z*1.7-t*.8), sin(p.z*2.3+t*.9)+sin(p.x*1.9+t*.7), sin(p.x*2.0-t*.8)+sin(p.y*1.6+t))*.5; }
vec3 rotY(vec3 p,float a){ float c=cos(a), s=sin(a); return vec3(c*p.x+s*p.z, p.y, -s*p.x+c*p.z); }
vec3 rotX(vec3 p,float a){ float c=cos(a), s=sin(a); return vec3(p.x, c*p.y-s*p.z, s*p.y+c*p.z); }
void main(){
  float m = clamp(uMix*1.5 - aM.x*0.5, 0., 1.); m = m*m*(3.-2.*m);
  vec3 p = mix(aA, aB, m);
  vec3 n = aN;
  float pulse = uTime - uPulseT;
  float amp = .010 + uTurb*.045 + uDissolve*1.0 + uThreat*.025*(.6+.4*sin(uTime*7.+aM.x*40.));
  p += flow(p*1.3 + aM.x*20., uTime*.33) * amp;
  float ring = (pulse > 0. && pulse < 1.8) ? exp(-pow((length(p)-pulse*2.1)*4.5, 2.)) : 0.;
  p += normalize(p+1e-4)*ring*.14;
  p = rotX(rotY(p, uYaw), uPitch); n = rotX(rotY(n, uYaw), uPitch);
  p.z -= uCam;
  vec4 clip = uProj*vec4(p,1.);
  vec2 ndc = clip.xy/clip.w;
  vec2 d = (ndc-uMouse)*vec2(uAspect,1.); float dist = length(d);
  float f = exp(-dist*dist*34.)*uMouseOn;
  ndc += (normalize(d+1e-4)*.07 + vec2(-d.y,d.x)*.9)*f/vec2(uAspect,1.);
  gl_Position = vec4(ndc*clip.w, clip.z, clip.w);
  float sel = (aM.z > -.5 && abs(aM.z-uSel) < .5) ? 1. : 0.;
  float hov = (aM.z > -.5 && abs(aM.z-uHover) < .5) ? 1. : 0.;
  float facing = normalize(n).z;
  float back = (1.-smoothstep(-.4,.12,facing)) * (1.-m) * step(aM.z,-.5);
  gl_PointSize = max(1.7, uSize*uDpr*pow(1.0/clip.w,.65)*(.65+.7*aM.w)) * (1.-.5*uDissolve) * (1.-.28*back) * (1.+.6*sel+.4*hov) * (1.+ring*1.5);
  vec3 lav = vec3(.79,.72,1.), lime = vec3(.91,.95,.23);
  vec3 base = mix(lime, lav, smoothstep(.12,.78,aM.y));
  float light = .30 + .75*pow(clamp(normalize(n).z*.5+.55,0.,1.),1.6);
  int gi = int(max(aM.z,0.)+.5);
  vec3 gc = aM.z < -.5 ? vec3(.42,.42,.58) : uGroupCol[gi];
  vec3 col = mix(base*light, gc*(.55+.6*aM.w), m);
  col *= 1.+uDissolve*1.3;
  col *= 1.-.55*back;
  col = mix(col, vec3(1.,.30,.38), uThreat*.22*(.5+.5*sin(uTime*3.+aM.y*6.)));
  col = mix(col, uPulseCol, ring*.9);
  col += (sel*.35 + hov*.25);
  vCol = col;
  vA = (aM.z < -.5 ? mix(1., .35, m) : 1.) * (1. - uDissolve*.25) * (1.-.6*back);
}`;
  const FS = `#version 300 es
precision mediump float; in vec3 vCol; in float vA; out vec4 o;
void main(){ o = vec4(vCol, vA); }`;

  function mkShader(gl, type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  const hex = (h) => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255];
  const GROUP_COL = { ok: hex("#C9B8FF"), ai: hex("#E8F23A"), blocked: hex("#FF5C6A"), warn: hex("#FFB74D"), gate: hex("#FF9F6B") };

  function create(canvas) {
    const gl = canvas.getContext("webgl2", { alpha: true, antialias: false, premultipliedAlpha: false, powerPreference: "high-performance" });
    if (!gl) return null;
    let prog;
    try {
      prog = gl.createProgram();
      gl.attachShader(prog, mkShader(gl, gl.VERTEX_SHADER, VS)); gl.attachShader(prog, mkShader(gl, gl.FRAGMENT_SHADER, FS));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    } catch (e) { console.warn("RepoBrain scene disabled:", e.message); return null; }
    gl.useProgram(prog);

    const MAXN = Math.min(90000, (navigator.hardwareConcurrency || 4) >= 6 && innerWidth > 900 ? 90000 : 42000);
    let count = MAXN;
    const brain = buildBrain(MAXN);
    const B = new Float32Array(MAXN * 3), M = brain.M;
    const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
    const bufs = {};
    function attr(name, data, size, usage) {
      const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, usage || gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, name); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0); bufs[name] = b;
    }
    // constellation starts as a dim sphere shell so the morph is never empty
    const rr = rng(11);
    for (let i = 0; i < MAXN; i++) { const th = rr() * TAU, ph = Math.acos(2 * rr() - 1), R = 1.5 + rr() * 0.8; B.set([R * Math.sin(ph) * Math.cos(th), R * Math.cos(ph) * 0.8, R * Math.sin(ph) * Math.sin(th)], i * 3); }
    attr("aA", brain.A, 3); attr("aB", B, 3, gl.DYNAMIC_DRAW); attr("aN", brain.N, 3); attr("aM", M, 4, gl.DYNAMIC_DRAW);

    const U = {}; ["uProj", "uTime", "uMix", "uCam", "uYaw", "uPitch", "uDissolve", "uTurb", "uThreat", "uAspect", "uDpr", "uSize", "uPulseT", "uMouseOn", "uSel", "uHover", "uMouse", "uGroupCol", "uPulseCol"]
      .forEach((n) => (U[n] = gl.getUniformLocation(prog, n)));
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const S = { mix: 0, cam: 3.7, yaw: 0.9, pitch: 0.08, dissolve: 0, turb: 0.2, threat: 0, mouse: [0, 0], mouseOn: 0, sel: -1, hover: -1, pulseT: -10, pulseCol: [1, 1, 1], rect: { x: 0, y: 0, w: innerWidth, h: innerHeight } };
    const T = { turb: 0.2, threat: 0 };                // smoothed targets
    let groups = [], t0 = performance.now(), ema = 16, slow = 0, last = t0;
    const groupCols = new Float32Array(32 * 3);

    function resize() {
      const dpr = Math.min(devicePixelRatio || 1, innerWidth * innerHeight > 2.5e6 ? 1.25 : 2);
      canvas.width = Math.round(innerWidth * dpr); canvas.height = Math.round(innerHeight * dpr); S.dpr = dpr;
    }
    resize(); addEventListener("resize", resize);

    /* Re-target the constellation to real data: files = [{loc, status, ai}] */
    function setData(files) {
      const list = files.slice(0, 32);
      const weight = list.map((f) => 0.45 + Math.sqrt(Math.max(1, f.loc)) * 0.14);
      const total = weight.reduce((a, b) => a + b, 0) || 1, clustered = Math.floor(MAXN * 0.8);
      groups = []; const r = rng(23), n = list.length;
      list.forEach((f, i) => {
        const ga = Math.PI * (3 - Math.sqrt(5)), y = n > 1 ? 1 - (i / (n - 1)) * 2 : 0, rad = Math.sqrt(Math.max(0, 1 - y * y)), th = i * ga;
        const R = 1.28, c = [Math.cos(th) * rad * R * 1.15, y * R * 0.82, Math.sin(th) * rad * R * 1.15];
        const col = f.status === "ok" ? (f.ai ? GROUP_COL.ai : GROUP_COL.ok) : GROUP_COL[f.status] || GROUP_COL.ok;
        groups.push({ c, r: 0.15 + 0.09 * Math.sqrt(weight[i]), n: Math.floor(clustered * weight[i] / total) });
        groupCols.set(col, i * 3);
      });
      let idx = 0;
      groups.forEach((g, gi) => {
        for (let k = 0; k < g.n && idx < MAXN; k++, idx++) {
          const th = r() * TAU, ph = Math.acos(2 * r() - 1), rd = g.r * (0.35 + 0.65 * Math.cbrt(r()));
          B.set([g.c[0] + rd * Math.sin(ph) * Math.cos(th), g.c[1] + rd * Math.cos(ph), g.c[2] + rd * Math.sin(ph) * Math.sin(th)], idx * 3);
          M[idx * 4 + 2] = gi;
        }
      });
      for (; idx < MAXN; idx++) {                         // remaining particles: dim dust halo
        const th = r() * TAU, ph = Math.acos(2 * r() - 1), R = 1.7 + r() * 1.0;
        B.set([R * Math.sin(ph) * Math.cos(th), R * Math.cos(ph) * 0.75, R * Math.sin(ph) * Math.sin(th)], idx * 3); M[idx * 4 + 2] = -1;
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, bufs.aB); gl.bufferSubData(gl.ARRAY_BUFFER, 0, B);
      gl.bindBuffer(gl.ARRAY_BUFFER, bufs.aM); gl.bufferSubData(gl.ARRAY_BUFFER, 0, M);
    }

    function proj(aspect) {
      const f = 1 / Math.tan((36 * Math.PI) / 360), n = 0.1, fa = 60;
      return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (fa + n) / (n - fa), -1, 0, 0, (2 * fa * n) / (n - fa), 0]);
    }
    /* screen position (px, relative to the stage rect) of each cluster: used for DOM labels */
    function project() {
      const { w, h } = S.rect, aspect = w / h, f = 1 / Math.tan((36 * Math.PI) / 360), cy = Math.cos(S.yaw), sy = Math.sin(S.yaw), cp = Math.cos(S.pitch), sp = Math.sin(S.pitch);
      return groups.map((g) => {
        let [x, y, z] = g.c;
        [x, z] = [cy * x + sy * z, -sy * x + cy * z]; [y, z] = [cp * y - sp * z, sp * y + cp * z]; z -= S.cam;
        const wv = -z; if (wv <= 0.05) return { visible: false };
        return { visible: true, x: ((f / aspect * x) / wv * 0.5 + 0.5) * w, y: (1 - ((f * y) / wv * 0.5 + 0.5)) * h, depth: wv };
      });
    }

    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      ema += (dt * 1000 - ema) * 0.05;
      if (ema > 38 && count > 22000) { slow += dt; if (slow > 2.2) { count = Math.floor(count * 0.7); slow = 0; ema = 20; } } else slow = 0;
      S.turb += (T.turb - S.turb) * Math.min(1, dt * 1.6); S.threat += (T.threat - S.threat) * Math.min(1, dt * 2.2);
      const r = S.rect, dpr = S.dpr;
      gl.disable(gl.SCISSOR_TEST); gl.viewport(0, 0, canvas.width, canvas.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      if (r.w < 8 || r.h < 8) return;
      const vx = Math.round(r.x * dpr), vy = Math.round((innerHeight - r.y - r.h) * dpr), vw = Math.round(r.w * dpr), vh = Math.round(r.h * dpr);
      gl.viewport(vx, vy, vw, vh); gl.enable(gl.SCISSOR_TEST); gl.scissor(vx, vy, vw, vh);
      gl.uniformMatrix4fv(U.uProj, false, proj(r.w / r.h));
      gl.uniform1f(U.uTime, (now - t0) / 1000); gl.uniform1f(U.uMix, S.mix); gl.uniform1f(U.uCam, S.cam); gl.uniform1f(U.uYaw, S.yaw); gl.uniform1f(U.uPitch, S.pitch);
      gl.uniform1f(U.uDissolve, S.dissolve); gl.uniform1f(U.uTurb, S.turb); gl.uniform1f(U.uThreat, S.threat); gl.uniform1f(U.uAspect, r.w / r.h); gl.uniform1f(U.uDpr, dpr);
      gl.uniform1f(U.uSize, 6.6 * (r.h / 820)); gl.uniform1f(U.uPulseT, S.pulseT); gl.uniform1f(U.uMouseOn, S.mouseOn); gl.uniform1f(U.uSel, S.sel); gl.uniform1f(U.uHover, S.hover);
      gl.uniform2f(U.uMouse, S.mouse[0], S.mouse[1]); gl.uniform3fv(U.uGroupCol, groupCols); gl.uniform3fv(U.uPulseCol, S.pulseCol);
      gl.drawArrays(gl.POINTS, 0, count);
    }
    return {
      S, T, frame, setData, project, resize,
      setMood(turb, threat) { T.turb = turb; T.threat = threat; },
      pulse(color) { S.pulseT = (performance.now() - t0) / 1000; S.pulseCol = color || [1, 1, 1]; },
      get count() { return count; }, get groups() { return groups; },
    };
  }
  window.RB3D = { create };
})();
