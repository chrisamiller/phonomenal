import { ART, SAND_TOP, artSvg, sceneSvg } from "./art.js";
import { $, api, celebrate, closeSheet, el, notify, onLeave, openSheet, setBalance, show } from "./ui.js";

const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
const BOTTOM = 7;            // bottom items stand this far (% of tank height) above the bottom edge
const rand = (a, b) => a + Math.random() * (b - a);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

let view = null;
let moving = false;
let night = isNightTime();
let anim = null;
let world = null;            // the live tank: size, fish, food, decorations
let taps = { uid: null, n: 0 };

function isNightTime() {
  const h = new Date().getHours();
  return h >= 19 || h < 7;
}

export async function openAquarium() {
  view = await api("/api/aquarium");
  show("aquarium");
  render();
}

function render(arrival = null) {
  const p = view.project;
  $("aq-name").textContent = p.name;
  setBalance(view.balance);
  $("aq-capacity").textContent = `${p.items.length} of ${view.capacity} spaces used`;
  $("aq-move").textContent = moving ? "✓ Done moving" : "✋ Move things";
  $("aq-night").textContent = night ? "☀️ Daytime" : "🌙 Night-time";
  drawTank($("tank"), p, !still);
  if (arrival) arrive(arrival);
}

// ---------------------------------------------------------------- drawing

// Draws a project into `tank`. Live tanks animate; gallery tanks and shop previews are still.
function drawTank(tank, p, live) {
  tank.className = "tank" + (live && moving ? " moving" : "") + (tank.id === "tank" && night ? " night" : "");
  const fx = el("div", { class: "fx" });
  tank.replaceChildren(el("div", { class: "scene", html: sceneSvg(p.tank?.background, p.tank?.sand) }),
    el("div", { class: "night-overlay" }), fx,
    ...(tank.id === "tank" ? [el("div", { class: "plankton" }, ...Array.from({ length: 14 }, (_, i) =>
      el("span", { style: `left:${(i * 37) % 100}%;top:${10 + ((i * 29) % 70)}%;animation-delay:-${i * 0.9}s` })))] : []));
  if (tank === $("tank")) {
    cancelAnimationFrame(anim);
    world = live ? { tank, fx, fish: [], food: [], decor: [], W: 0, H: 0 } : null;
  }

  for (const it of p.items) {
    const a = ART[it.item];
    if (!a) continue;
    const node = el("div", { class: `item ${a.move === "swim" ? "swimmer" : "bottom"} kind-${a.kind || it.item}${a.glow ? " glow" : ""}`,
                             "data-uid": it.uid, html: artSvg(it.item) });
    node.style.width = `${a.w}%`;
    node.style.setProperty("--blink", `-${rand(0, 5).toFixed(1)}s`);   // don't all blink at once
    if (a.move === "swim") {
      if (live && world) {
        const shadow = el("div", { class: "fish-shadow" });
        tank.append(shadow, node);
        world.fish.push(newFish(it, a, node, shadow));
        node.addEventListener("pointerdown", (e) => { e.stopPropagation(); tapFish(it.uid); });
      } else {
        node.style.left = `${it.x}%`;
        node.style.top = `${Math.min(it.y, 60)}%`;
        tank.append(node);
      }
    } else {
      node.style.left = `${it.x}%`;
      node.style.bottom = `${BOTTOM}%`;
      if (a.bubbles) node.append(...[0, 1, 2, 3].map((i) => el("span", { class: `bubble b${i}` })));
      tank.append(node);
      if (live && world) {
        world.decor.push({ it, a, node });
        node.addEventListener("pointerdown", (e) => moving ? startDrag(e, node, it) : poke(e, node));
      }
    }
  }
  if (live && world) {
    tank.onpointerdown = (e) => { if (!moving) dropFood(e); };
    measure();
    startAnimation();
  }
}

function measure() {
  const r = world.tank.getBoundingClientRect();
  const [oldW, oldH] = [world.W, world.H];
  world.W = r.width;
  world.H = r.height;
  for (const f of world.fish) {
    const [, , vw, vh] = f.a.vb.split(" ").map(Number);
    f.w = (f.a.w / 100) * world.W;
    f.h = f.w * (vh / vw);
    if (oldW) {
      f.x *= world.W / oldW; f.y *= world.H / oldH; f.tx *= world.W / oldW; f.ty *= world.H / oldH;
    } else {
      f.x = (f.it.x / 100) * world.W;
      f.y = clamp((f.it.y / 100) * world.H, top(), floor(f));
      pickTarget(f);
    }
  }
}

const top = () => world.H * 0.07;
const floor = (f) => world.H * SAND_TOP - f.h * 0.85;

// ---------------------------------------------------------------- fish behaviour

function newFish(it, a, node, shadow) {
  return { it, a, node, shadow, kind: a.kind, x: 0, y: 0, vx: 0, vy: 0, tx: 0, ty: 0, w: 0, h: 0,
           face: Math.random() < 0.5 ? 1 : -1, wait: rand(0, 2), boost: 0, phase: rand(0, 6), path: [],
           near: Math.random() < 0.65, eaten: 0, fullUntil: 0, hideUntil: 0, pulse: rand(0, 1.8) };
}

// Where a fish heads next, by personality.
function pickTarget(f) {
  const { W, H } = world;
  const maxX = W - f.w;
  const anyWhere = () => [rand(0, maxX), rand(top(), floor(f))];
  let [tx, ty] = anyWhere();
  const plants = world.decor.filter((d) => ["seaweed", "kelp-forest", "fan-coral", "anemone"].includes(d.it.item));
  const anemone = world.decor.find((d) => d.it.item === "anemone");
  switch (f.kind) {
    case "clown":       // stays close to its anemone
      if (anemone) {
        const ax = (anemone.it.x / 100) * W + (anemone.a.w / 200) * W;
        tx = clamp(ax - f.w / 2 + rand(-1.2, 1.2) * f.w, 0, maxX);
        ty = clamp(H * SAND_TOP - H * 0.22 + rand(-0.6, 0.6) * f.h, top(), floor(f));
      }
      break;
    case "seahorse":    // drifts between plants
      if (plants.length) {
        const pl = plants[Math.floor(Math.random() * plants.length)];
        tx = clamp((pl.it.x / 100) * W + rand(-0.5, 1.5) * f.w, 0, maxX);
      }
      ty = rand(H * 0.35, floor(f));
      break;
    case "turtle":      // long glides, sometimes up to the surface for air
      ty = Math.random() < 0.25 ? top() : rand(top(), floor(f));
      tx = f.x < W / 2 ? rand(W * 0.5, maxX) : rand(0, W * 0.4);
      break;
    case "shark":       // slow, wide, mid-water
      tx = f.x < W / 2 ? rand(W * 0.45, maxX) : rand(0, W * 0.2);
      ty = rand(H * 0.18, Math.max(H * 0.2, floor(f) - H * 0.1));
      break;
    case "octopus":     // sometimes hides behind a decoration for a while
      if (world.decor.length && Math.random() < 0.5) {
        const d = world.decor[Math.floor(Math.random() * world.decor.length)];
        tx = clamp((d.it.x / 100) * W + (d.a.w / 200) * W - f.w / 2, 0, maxX);
        ty = H * (1 - BOTTOM / 100) - f.h * 0.95;
        f.hiding = true;
      } else {
        f.hiding = false;
        ty = rand(H * 0.3, floor(f));
      }
      break;
  }
  f.tx = tx;
  f.ty = ty;
}

function leaderOf(f) {
  return world.fish.find((o) => o.it.item === f.it.item);
}

function step(dt, now) {
  const { W, H } = world;
  for (const f of world.fish) {
    f.phase += dt;
    f.boost = Math.max(0, f.boost - dt);
    let speed = f.a.speed * W * (night ? 0.55 : 1);

    // Food first (jellyfish just drift).
    const hungry = f.kind !== "jelly" && now > f.fullUntil && world.food.length;
    let chasing = false;
    if (hungry) {
      const mouthX = f.face > 0 ? f.w * 0.92 : f.w * 0.08;
      let best = null, bestD = Infinity;
      for (const p of world.food) {
        const d = Math.hypot(p.x - (f.x + mouthX), p.y - (f.y + f.h / 2));
        if (d < bestD) { best = p; bestD = d; }
      }
      if (best) {
        chasing = true;
        f.tx = clamp(best.x - mouthX, 0, W - f.w);
        f.ty = clamp(best.y - f.h / 2, top(), floor(f));
        speed *= 1.8;
        if (bestD < Math.max(10, f.h * 0.4)) eat(f, best, now);
      }
    } else if (f.path.length) {
      [f.tx, f.ty] = f.path[0];
      speed *= 2.4;
    } else if (f.kind === "school" && leaderOf(f) !== f) {
      const lead = leaderOf(f);
      f.off ??= [rand(-1.6, 1.6), rand(-1.4, 1.4)];
      f.tx = clamp(lead.x - lead.face * f.w * 1.1 + f.off[0] * f.w, 0, W - f.w);
      f.ty = clamp(lead.y + f.off[1] * f.h, top(), floor(f));
      speed *= 1.25;
    } else if (f.wait > 0) {
      f.wait -= dt;
      if (f.wait <= 0) pickTarget(f);
    }
    if (f.puffed) speed *= 0.3;
    if (f.boost) speed *= 3;

    if (f.kind === "jelly") {
      // Pulses upward, then sinks slowly; drifts sideways toward its target.
      f.pulse -= dt;
      if (f.pulse <= 0) { f.pulse = 1.8; f.vy -= H * 0.05; }
      f.vy += H * 0.012 * dt;
      f.vy *= 1 - Math.min(1, dt * 1.2);
      f.vx += ((Math.sign(f.tx - f.x) * speed) - f.vx) * Math.min(1, dt);
      if (f.y <= top()) f.vy = Math.abs(f.vy) * 0.3;
      if (Math.abs(f.tx - f.x) < 8 && f.wait <= 0) f.wait = rand(1, 4);
    } else {
      const dx = f.tx - f.x, dy = f.ty - f.y, dist = Math.hypot(dx, dy) || 1;
      const sp = speed * Math.min(1, dist / (f.w * 0.8));      // ease in to the target
      const steer = Math.min(1, dt * (f.boost ? 6 : 2.2));
      f.vx += ((dx / dist) * sp - f.vx) * steer;
      f.vy += ((dy / dist) * sp - f.vy) * steer;
      if (dist < Math.max(4, f.w * 0.1) && !chasing) {
        if (f.path.length) f.path.shift();
        else if (f.wait <= 0) f.wait = f.kind === "octopus" && f.hiding ? rand(6, 12) : rand(0.4, 3);
      }
    }
    f.x = clamp(f.x + f.vx * dt, 0, W - f.w);
    f.y = clamp(f.y + f.vy * dt, f.kind === "turtle" ? 0 : top(), f.kind === "octopus" ? H : floor(f));

    // Turn smoothly to face the way it's going (octopus and jellyfish don't turn).
    if (!["octopus", "jelly"].includes(f.kind) && Math.abs(f.vx) > speed * 0.12) {
      f.face += (Math.sign(f.vx) - f.face) * Math.min(1, dt * 5);
    }
    const tilt = ["octopus", "jelly", "seahorse"].includes(f.kind) ? 0 : clamp((f.vy / (speed + 1)) * 22, -22, 22);
    const bob = Math.sin(f.phase * (f.kind === "seahorse" ? 1.2 : 2)) * f.h * (f.kind === "seahorse" ? 0.08 : 0.04);
    const scale = f.near ? 1 : 0.82;
    const face = Math.abs(f.face) < 0.08 ? Math.sign(f.face || 1) * 0.08 : f.face;
    f.node.style.transform = `translate(${f.x}px, ${f.y + bob}px) rotate(${tilt * Math.sign(face)}deg) scale(${face * scale}, ${scale})`;
    f.node.style.zIndex = f.kind === "octopus" && f.hiding && f.wait > 0 ? 1 : f.near ? 5 : 1;
    f.node.classList.toggle("fast", f.boost > 0 || chasing || f.path.length > 0);
    // A soft shadow on the sand, fainter the higher the fish swims.
    const height = 1 - f.y / (H * SAND_TOP);
    f.shadow.style.transform = `translate(${f.x + f.w * 0.1}px, ${H * (SAND_TOP + 0.02)}px) scale(${1 - height * 0.5})`;
    f.shadow.style.width = `${f.w * 0.8}px`;
    f.shadow.style.opacity = String(clamp(0.5 - height * 0.45, 0.05, 0.5));
  }
  stepFood(dt);
}

function startAnimation() {
  cancelAnimationFrame(anim);
  let last = performance.now();
  const loop = (now) => {
    if (!world) return;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (world.tank.clientWidth !== Math.round(world.W)) measure();
    step(dt, now);
    anim = requestAnimationFrame(loop);
  };
  anim = requestAnimationFrame(loop);
}

onLeave("aquarium", () => { cancelAnimationFrame(anim); world = null; });

// ---------------------------------------------------------------- effects

function fxAt(cls, x, y, life = 1200, extra = {}) {
  const n = el("div", { class: cls, ...extra });
  n.style.left = `${x}px`;
  n.style.top = `${y}px`;
  world.fx.append(n);
  setTimeout(() => n.remove(), life);
  return n;
}

function bubbles(x, y, count = 3) {
  for (let i = 0; i < count; i++) {
    const b = fxAt("pop-bubble", x + rand(-6, 6), y, 1800);
    b.style.animationDelay = `${i * 0.12}s`;
    b.style.setProperty("--s", rand(0.6, 1.2).toFixed(2));
  }
}

// ---------------------------------------------------------------- tapping

async function tapFish(uid) {
  if (moving || !world) return;
  const f = world.fish.find((x) => x.it.uid === uid);
  taps = taps.uid === uid ? { uid, n: taps.n + 1 } : { uid, n: 1 };
  const svg = f.node.querySelector("svg");
  svg.classList.remove("wiggle");
  void svg.getBoundingClientRect();
  svg.classList.add("wiggle");
  const cx = f.x + f.w / 2, cy = f.y + f.h / 2;
  if (f.kind === "puffer") {
    f.puffed = true;
    f.node.classList.add("puffed");
    clearTimeout(f.puffTimer);
    f.puffTimer = setTimeout(() => { f.puffed = false; f.node.classList.remove("puffed"); }, 3500);
  } else if (f.kind === "octopus") {
    fxAt("ink", cx, cy, 2200);
    f.boost = 1.5;
    f.wait = 0;
    pickTarget(f);
  } else if (f.kind === "jelly") {
    f.node.classList.remove("flash");
    void f.node.offsetWidth;
    f.node.classList.add("flash");
    clearTimeout(f.flashTimer);   // drop the class afterwards so the steady glow comes back
    f.flashTimer = setTimeout(() => f.node.classList.remove("flash"), 900);
    f.vy -= world.H * 0.08;
  } else if (f.kind === "turtle" || f.kind === "seahorse") {
    fxAt("heart", cx, f.y, 1600, { html: "💗" });
  } else {
    // Startled: darts off the other way.
    f.boost = 1.1;
    f.path = [];
    f.tx = clamp(f.x - f.face * world.W * rand(0.25, 0.4), 0, world.W - f.w);
    f.ty = clamp(f.y + rand(-1, 1) * f.h * 2, top(), floor(f));
    f.wait = 0;
    bubbles(f.face > 0 ? f.x + f.w : f.x, cy, 3);
  }
  if (taps.n === 10) celebrate((await api("/api/fish-whisperer", {})).awards);
}

function poke(e, node) {
  e.stopPropagation();
  node.classList.remove("poked");
  void node.offsetWidth;
  node.classList.add("poked");
  const r = node.getBoundingClientRect(), t = world.tank.getBoundingClientRect();
  if (node.querySelector(".lid, .twinkle")) bubbles(r.left - t.left + r.width / 2, r.top - t.top + r.height * 0.3, 4);
}

// ---------------------------------------------------------------- feeding

function dropFood(e) {
  if (!world.fish.length) return;
  const t = world.tank.getBoundingClientRect();
  const x = e.clientX - t.left;
  if (e.clientY - t.top > world.H * SAND_TOP) return;
  fxAt("plop", x, world.H * 0.04, 700);
  for (let i = 0; i < 5; i++) {
    const node = el("span", { class: "flake" });
    world.fx.append(node);
    world.food.push({ node, x: x + rand(-14, 14), y: world.H * 0.05 + rand(0, 8), vy: rand(14, 24), phase: rand(0, 6), age: 0 });
  }
}

function stepFood(dt) {
  const bottom = world.H * (SAND_TOP + 0.03);
  for (const p of [...world.food]) {
    p.age += dt;
    p.phase += dt * 2;
    if (p.y < bottom) {
      p.y += p.vy * dt * (world.H / 300);
      p.x += Math.sin(p.phase) * 6 * dt;
    }
    p.node.style.transform = `translate(${p.x}px, ${p.y}px) rotate(${p.phase * 40}deg)`;
    if (p.age > 14) removeFood(p);
    else if (p.age > 12) p.node.style.opacity = String((14 - p.age) / 2);
  }
}

function removeFood(p) {
  p.node.remove();
  world.food = world.food.filter((x) => x !== p);
}

function eat(f, p, now) {
  removeFood(p);
  f.eaten += 1;
  f.node.classList.remove("gulp");
  void f.node.offsetWidth;
  f.node.classList.add("gulp");
  if (f.eaten % 3 === 0) {           // full for a while; leaves food for the others
    f.fullUntil = now + 20000;
    f.wait = 0;
    pickTarget(f);
  }
}

// ---------------------------------------------------------------- arrivals

// A newly bought item makes an entrance: fish splash in and swim a happy lap,
// decorations sink to the sand with a puff.
function arrive(uid) {
  if (!world) return;
  const f = world.fish.find((x) => x.it.uid === uid);
  const { W, H } = world;
  if (f) {
    f.y = -f.h;
    f.x = clamp(f.x, W * 0.1, W * 0.9 - f.w);
    fxAt("splash", f.x + f.w / 2, 0, 1000);
    const right = f.x < W / 2;
    f.path = [[f.x, H * 0.35], [right ? W * 0.85 - f.w : W * 0.15, H * 0.3], [right ? W * 0.85 - f.w : W * 0.15, H * 0.6],
              [right ? W * 0.1 : W * 0.9 - f.w, H * 0.55], [W / 2 - f.w / 2, H * 0.4]];
    f.vy = H * 0.4;
    // The other fish come over to say hello.
    for (const o of world.fish) if (o !== f && !o.path.length) {
      o.tx = clamp(W / 2 + rand(-0.25, 0.25) * W, 0, W - o.w);
      o.ty = clamp(H * 0.45 + rand(-0.15, 0.15) * H, top(), floor(o));
      o.wait = 0;
    }
    return;
  }
  const d = world.decor.find((x) => x.it.uid === uid);
  if (d) {
    const r = d.node.getBoundingClientRect(), t = world.tank.getBoundingClientRect();
    fxAt("splash", r.left - t.left + r.width / 2, 0, 1000);
    d.node.classList.add("sinking");
    setTimeout(() => {
      d.node.classList.remove("sinking");
      fxAt("sand-puff", r.left - t.left + r.width / 2, H * (1 - BOTTOM / 100), 1000);
    }, 900);
  }
}

// ---------------------------------------------------------------- moving things on the sand

function startDrag(e, node, it) {
  e.preventDefault();
  e.stopPropagation();
  const tank = $("tank").getBoundingClientRect();
  const offset = e.clientX - node.getBoundingClientRect().left;
  node.setPointerCapture(e.pointerId);
  node.classList.add("dragging");
  const move = (ev) => {
    const pct = ((ev.clientX - offset - tank.left) / tank.width) * 100;
    it.x = Math.round(clamp(pct, 0, 100 - ART[it.item].w) * 10) / 10;
    node.style.left = `${it.x}%`;
  };
  const up = () => {
    node.classList.remove("dragging");
    node.removeEventListener("pointermove", move);
    node.removeEventListener("pointerup", up);
  };
  node.addEventListener("pointermove", move);
  node.addEventListener("pointerup", up);
}

async function toggleMove() {
  moving = !moving;
  if (!moving) {
    const positions = Object.fromEntries(view.project.items.map((i) => [i.uid, { x: i.x, y: i.y }]));
    celebrate((await api("/api/aquarium/layout", { positions })).awards);
  }
  render();
}

function toggleNight() {
  night = !night;
  $("tank").classList.toggle("night", night);
  $("aq-night").textContent = night ? "☀️ Daytime" : "🌙 Night-time";
}

// ---------------------------------------------------------------- shop

const TABS = [
  { id: "fish", label: "🐟 Fish" }, { id: "coral", label: "🪸 Coral" },
  { id: "decor", label: "🏰 Decorations" }, { id: "tank", label: "🪟 Tank" },
];

// The standard looks, always owned, so she can switch back to them.
const STOCK = [
  { id: "bg-default", name: "Standard Water", category: "tank", owned: true, stock: true, before: "bg-" },
  { id: "sand-default", name: "Standard Sand", category: "tank", owned: true, stock: true, before: "sand-" },
];

function shopItems(tab) {
  const items = view.shop.filter((i) => i.category === tab);
  if (tab !== "tank") return items;
  for (const s of STOCK) {
    const at = items.findIndex((i) => i.id.startsWith(s.before));
    items.splice(at < 0 ? items.length : at, 0, s);
  }
  return items;
}

function upgradePreview(id) {
  if (id === "big-tank") return el("span", { class: "shop-emoji" }, "↔️");
  const t = el("div", { class: "tank mini" });
  drawTank(t, { tank: id.startsWith("bg-") ? { background: id } : { sand: id }, items: [] }, false);
  return t;
}

function openShop() {
  const sheet = openSheet("Shop", {
    tabs: TABS,
    render: (tab) => {
      const items = shopItems(tab);
      const full = view.project.items.length >= view.capacity;
      return el("div", { class: "shop-grid" }, ...items.map((i) => {
        const isTank = i.category === "tank";
        const slot = i.id.startsWith("bg-") ? "background" : i.id.startsWith("sand-") ? "sand" : null;
        const current = view.project.tank?.[slot] || null;
        const inUse = slot && (i.stock ? !current : current === i.id);
        let action;
        if (isTank && i.owned) {
          action = !slot ? el("span", { class: "muted" }, "✓ Owned")
            : inUse ? el("button", { class: "primary", disabled: true }, "✓ Using")
            : el("button", { onclick: () => useUpgrade(slot, i.stock ? null : i.id, sheet) }, "Use");
        } else {
          const afford = view.balance >= i.price;
          action = el("button", {
            class: "primary", disabled: !afford || (!isTank && full),
            onclick: () => buy(i.id),
          }, `🪙 ${i.price}`);
        }
        const art = isTank ? upgradePreview(i.id) : el("div", { html: artSvg(i.id) });
        return el("div", { class: "shop-card" },
          el("div", { class: "shop-art" }, art),
          el("strong", {}, i.name),
          !isTank && i.owned ? el("span", { class: "muted" }, `You have ${i.owned}`) : null,
          action);
      }), full ? el("p", { class: "note" }, "Your tank is full. A bigger tank makes more room!") : null);
    },
  });
}

async function buy(id) {
  try {
    const before = new Set(view.project.items.map((i) => i.uid));
    const r = await api("/api/aquarium/buy", { item: id });
    view = r;
    closeSheet();           // so she sees it arrive
    const added = view.project.items.find((i) => !before.has(i.uid));
    render(added?.uid);
    celebrate(r.awards);
  } catch (e) {
    notify(e.message);
  }
}

async function useUpgrade(slot, item, sheet) {
  view = await api("/api/aquarium/use", { slot, item });
  render();
  sheet.redraw();
}

// ---------------------------------------------------------------- gallery & new tank

function openGallery() {
  openSheet("Gallery", {
    render: () => view.gallery.length
      ? view.gallery.map((p) => {
          const t = el("div", { class: "tank small" });
          drawTank(t, p, false);
          return el("div", { class: "gallery-item" }, el("strong", {}, p.name),
            el("span", { class: "muted" }, new Date(p.archived_at).toLocaleDateString()), t);
        })
      : el("p", { class: "muted" }, "Finished tanks will be shown here."),
  });
}

function openNewTank() {
  openSheet("Start a new tank?", {
    render: () => {
      const name = el("input", { class: "text-input", maxlength: 40, value: view.project.name });
      return [
        el("p", {}, "Your current tank will go into the gallery, and you'll start fresh with an empty tank. You keep all your credits."),
        el("label", {}, "Name your finished tank:", name),
        el("button", { class: "big primary", onclick: async () => {
          try {
            view = await api("/api/aquarium/archive", { name: name.value });
            celebrate(view.awards);
            closeSheet();
            render();
          } catch (e) {
            name.after(el("p", { class: "note" }, e.message));
          }
        } }, "✨ Start a new tank"),
      ];
    },
  });
}

$("aq-shop").onclick = openShop;
$("aq-move").onclick = toggleMove;
$("aq-night").onclick = toggleNight;
$("aq-gallery").onclick = openGallery;
$("aq-new").onclick = openNewTank;
