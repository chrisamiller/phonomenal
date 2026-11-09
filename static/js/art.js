// Aquarium artwork: one inline SVG per shop item, all facing right, in one style:
// dark outline, toon shading (the shared "aq-shade" gradient), a highlight and big eyes.
// Parts with a class (tail, fin, arms, bell…) are animated by style.css.
//   w     = width as a percentage of the tank
//   move  = "swim" (moves around the water) or "bottom" (sits on the sand)
//   kind  = swimming personality (see aquarium.js); speed = share of the tank width per second
//   clip  = body outline, used to keep stripes and spots inside the body

const OUT = "#1d2a44";
const r1 = (n) => Math.round(n * 10) / 10;
const ell = (cx, cy, rx, ry) => `M${cx - rx} ${cy}a${rx} ${ry} 0 1 0 ${2 * rx} 0a${rx} ${ry} 0 1 0 ${-2 * rx} 0Z`;
const fill = (d, c, extra = "") => `<path d="${d}" fill="${c}" ${extra}/>`;
const ink = (d, sw = 3) => `<path d="${d}" fill="url(#aq-shade)" stroke="${OUT}" stroke-width="${sw}" stroke-linejoin="round" stroke-linecap="round"/>`;
const part = (d, c, sw) => fill(d, c) + ink(d, sw);                  // filled, shaded, outlined
const line = (d, c, w, extra = "") => `<path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" ${extra}/>`;
const tube = (d, c, w) => line(d, OUT, w + 3.5) + line(d, c, w);      // outlined thick stroke
const hi = (cx, cy, rx, ry, rot = -20) => `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="#fff" opacity=".55" transform="rotate(${rot} ${cx} ${cy})"/>`;
const g = (cls, ox, oy, inner) => `<g class="${cls}" style="transform-origin:${ox}px ${oy}px">${inner}</g>`;
const clip = (id, inner) => `<g clip-path="url(#aq-clip-${id})">${inner}</g>`;
const eye = (x, y, r) => g("eye", x, y,
  `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${OUT}" stroke-width="${r1(Math.max(1.6, r * 0.32))}"/>` +
  `<circle cx="${r1(x + r * 0.28)}" cy="${r1(y + r * 0.08)}" r="${r1(r * 0.6)}" fill="#16213a"/>` +
  `<circle cx="${r1(x + r * 0.45)}" cy="${r1(y - r * 0.22)}" r="${r1(r * 0.24)}" fill="#fff"/>`);
const smile = (x, y, s = 1) => line(`M${x - 3 * s} ${y} q${3 * s} ${2.6 * s} ${6 * s} 0`, OUT, 2);

// A wavy, tapering ribbon growing up from (x0, y0): seaweed and kelp.
function ribbon(x0, y0, len, width, waves, amp, phase) {
  const n = 18, L = [], R = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, y = y0 - len * t;
    const x = x0 + Math.sin(t * waves * Math.PI * 2 + phase) * amp * t;
    const w = (width / 2) * (1 - t * 0.7) * (i === n ? 0.2 : 1);
    L.push(`${r1(x - w)} ${r1(y)}`);
    R.push(`${r1(x + w)} ${r1(y)}`);
  }
  return `M${L.join("L")}L${R.reverse().join("L")}Z`;
}

// A plump, round-tipped star.
function star(cx, cy, R, r, n = 5, rot = -90) {
  const pt = (rad, k) => { const a = ((rot + (k * 360) / (n * 2)) * Math.PI) / 180; return [r1(cx + Math.cos(a) * rad), r1(cy + Math.sin(a) * rad)]; };
  let d = `M${pt(r, -1).join(" ")}`;
  for (let k = 0; k < n; k++) d += `Q${pt(R * 1.18, 2 * k).join(" ")} ${pt(r, 2 * k + 1).join(" ")}`;
  return d + "Z";
}

const BODY = {
  guppy: "M34 32C40 18 70 16 86 27C91 30 91 35 86 37C70 46 42 46 34 32Z",
  tetra: "M22 25C30 13 64 11 86 20C92 23 92 28 86 30C64 39 30 37 22 25Z",
  gold: "M34 38C36 15 70 7 91 22C101 29 101 45 91 52C70 67 36 61 34 38Z",
  clown: "M24 33C30 12 66 8 94 22C102 27 102 39 94 44C66 58 30 54 24 33Z",
  tang: "M26 38C28 12 70 4 98 22C110 30 110 46 98 54C70 72 28 64 26 38Z",
  angel: "M30 60C34 34 50 26 68 34C82 42 88 54 88 60C88 66 82 78 68 86C50 94 34 86 30 60Z",
  puffer: ell(52, 46, 28, 27),
  turtle: "M24 46C26 20 60 12 84 16C104 20 116 34 116 46C116 56 100 66 70 68C40 70 24 62 24 46Z",
  octo: "M22 50C16 18 38 4 55 4C72 4 94 18 88 50C86 60 74 66 55 66C36 66 24 60 22 50Z",
  shark: "M30 56C70 18 150 14 210 22C250 28 272 44 274 56C272 70 250 82 210 86C150 92 70 92 30 56Z",
  jelly: "M10 50C8 16 30 4 45 4C60 4 82 16 80 50C72 46 64 53 56 48C50 53 40 53 34 48C26 53 18 46 10 50Z",
  brain: "M8 78C6 30 30 10 60 10C90 10 114 30 112 78Z",
  fan: "M60 76C14 72 4 40 14 20C30 2 50 6 60 10C70 6 90 2 106 20C116 40 106 72 60 76Z",
  castle: "M14 150V30H48V60H122V30H156V150Z",
  hull: "M10 46L64 50L66 70L252 84C246 108 230 126 208 136L56 136C34 120 18 90 10 46Z",
};

export const ART = {
  // ---------------- fish ----------------
  "guppy": { w: 8, move: "swim", kind: "school", speed: 0.09, vb: "0 0 100 60", clip: BODY.guppy, svg: `
    ${fill("M50 21C54 9 66 8 72 19Z", "#ff9a3c")}${ink("M50 21C54 9 66 8 72 19Z")}
    ${g("tail", 37, 32, part("M38 32C28 16 12 4 4 10C9 22 9 42 4 54C12 60 28 48 38 32Z", "#a46cf5") +
      line("M30 30L10 14M30 34L10 50M32 32L8 32", "#7c4ddb", 2))}
    ${fill(BODY.guppy, "#ffc84a")}${clip("guppy", fill(ell(64, 44, 30, 9), "#fff1b8"))}${ink(BODY.guppy)}
    ${g("fin", 62, 36, part("M62 36C58 45 50 48 48 43C50 39 56 36 62 36Z", "#ffb347", 2.4))}
    ${hi(62, 25, 9, 3)}${eye(76, 28, 5)}${line("M86 34q2 1 3 0", OUT, 1.8)}` },
  "neon-tetra": { w: 7, move: "swim", kind: "school", speed: 0.11, vb: "0 0 100 50", clip: BODY.tetra, svg: `
    ${part("M46 15C50 6 59 6 62 13Z", "#cfd9e6", 2.5)}
    ${g("tail", 24, 25, part("M26 25C18 16 8 10 3 12C7 20 7 30 3 38C8 40 18 34 26 25Z", "#e8eef6", 2.5))}
    ${fill(BODY.tetra, "#dce7f2")}
    ${clip("neon-tetra", fill("M10 20Q55 15 95 18L95 24Q55 22 10 27Z", "#22e3ff") + fill("M10 27Q40 29 64 27L66 40L10 40Z", "#ff3b5c"))}
    ${ink(BODY.tetra, 2.6)}${hi(56, 18, 8, 2.4, -6)}${eye(78, 22, 4.2)}` },
  "goldfish": { w: 10, move: "swim", kind: "wander", speed: 0.07, vb: "0 0 110 76", clip: BODY.gold, svg: `
    ${part("M54 16C58 2 76 0 82 15Z", "#ffb05c")}
    ${g("tail", 38, 38, part("M40 38C28 18 10 6 2 14C14 26 12 34 6 38C12 42 14 50 2 62C10 70 28 58 40 38Z", "#ffb05c") +
      line("M32 34L12 18M32 42L12 58M34 38L14 38", "#f08a2c", 2))}
    ${fill(BODY.gold, "#ff8a1f")}${clip("goldfish", fill(ell(70, 56, 34, 12), "#ffc06b") +
      [[56, 30], [64, 40], [72, 30], [58, 46], [80, 42]].map(([x, y]) => line(`M${x} ${y}q3 -3 6 0`, "#f07a10", 1.6)).join(""))}${ink(BODY.gold)}
    ${g("fin", 70, 52, part("M70 52C66 63 58 66 55 60C58 55 64 52 70 52Z", "#ffb05c", 2.5))}
    ${hi(66, 22, 11, 4)}${eye(87, 32, 6)}${line("M97 41q2 1 3 -1", OUT, 2)}` },
  "clownfish": { w: 10, move: "swim", kind: "clown", speed: 0.08, vb: "0 0 110 66", clip: BODY.clown, svg: `
    ${part("M44 14C50 2 70 2 76 14Z", "#ff7a1a")}
    ${g("tail", 26, 33, part("M28 33C20 20 10 12 4 16C8 26 8 40 4 50C10 54 20 46 28 33Z", "#ff7a1a"))}
    ${fill(BODY.clown, "#ff7a1a")}
    ${clip("clownfish", [[74, 82], [50, 60], [28, 35]].map(([a, b]) =>
      `<path d="M${a} 0Q${a + 6} 33 ${a} 66L${b} 66Q${b + 6} 33 ${b} 0Z" fill="#fff" stroke="${OUT}" stroke-width="2.5"/>`).join(""))}
    ${ink(BODY.clown)}
    ${g("fin", 66, 42, part("M66 42C62 52 54 55 52 50C54 45 60 42 66 42Z", "#ff9a4a", 2.4))}
    ${hi(64, 18, 10, 3)}${eye(89, 27, 5.2)}${smile(95, 36, 0.8)}` },
  "blue-tang": { w: 11, move: "swim", kind: "wander", speed: 0.1, vb: "0 0 120 76", clip: BODY.tang, svg: `
    ${part("M38 20C58 2 86 4 98 20C80 12 58 12 38 20Z", "#0d1f4f")}${part("M38 58C58 74 86 72 98 56C80 64 58 64 38 58Z", "#0d1f4f")}
    ${g("tail", 28, 38, part("M30 38L6 18C12 30 12 46 6 58Z", "#ffd23f"))}
    ${fill(BODY.tang, "#2b6cf0")}${clip("blue-tang", fill("M34 30C52 12 80 10 98 24C80 26 70 32 64 46C58 36 46 32 34 30Z", "#0d1f4f") +
      fill("M24 30C34 36 36 46 26 50Z", "#0d1f4f"))}${ink(BODY.tang)}
    ${g("fin", 76, 44, part("M76 44C72 56 64 59 61 53C64 48 70 44 76 44Z", "#ffd23f", 2.4))}
    ${hi(72, 18, 9, 3)}${eye(96, 32, 5.6)}${smile(104, 42, 0.7)}` },
  "angelfish": { w: 9, move: "swim", kind: "wander", speed: 0.06, vb: "0 0 100 120", clip: BODY.angel, svg: `
    ${part("M46 34C40 14 34 4 30 2C42 6 58 18 66 33Z", "#e6dcc0")}${part("M46 86C40 106 34 116 30 118C42 114 58 102 66 87Z", "#e6dcc0")}
    ${line("M58 86L46 114M64 84L56 112", "#e6dcc0", 2.4)}
    ${g("tail", 32, 60, part("M34 60C24 48 12 44 6 46C10 56 10 64 6 74C12 76 24 72 34 60Z", "#e6dcc0"))}
    ${fill(BODY.angel, "#f4efdd")}${clip("angelfish", fill("M42 0H50V120H42Z", "#2a2a35") + fill("M60 0H66V120H60Z", "#2a2a35") +
      fill("M30 0H35V120H30Z", "#2a2a35"))}${ink(BODY.angel)}
    ${g("fin", 64, 64, part("M64 64C62 74 56 77 53 72C55 68 60 64 64 64Z", "#fff6d8", 2.4))}
    ${hi(62, 42, 8, 3)}${eye(76, 54, 5.4)}` },
  "pufferfish": { w: 9, move: "swim", kind: "puffer", speed: 0.05, vb: "0 0 100 92", clip: BODY.puffer, svg: `
    ${g("tail", 26, 46, part("M28 46L8 33C11 42 11 50 8 59Z", "#f2b53a"))}
    ${g("pbody", 52, 46, `<g class="spikes">${Array.from({ length: 16 }, (_, i) => {
      const a = (i / 16) * Math.PI * 2;
      return line(`M${r1(52 + Math.cos(a) * 25)} ${r1(46 + Math.sin(a) * 24)}L${r1(52 + Math.cos(a) * 34)} ${r1(46 + Math.sin(a) * 33)}`, "#a8661b", 2.6);
    }).join("")}</g>
      ${fill(BODY.puffer, "#f5c64e")}${clip("pufferfish", fill(ell(52, 64, 26, 14), "#fff4cf") +
        [[40, 30], [54, 24], [64, 34], [36, 44], [48, 40]].map(([x, y]) => fill(ell(x, y, 3, 2.4), "#c88a2a")).join(""))}
      ${ink(BODY.puffer)}${hi(42, 28, 9, 4)}${eye(66, 38, 6.4)}
      <circle cx="80" cy="52" r="3" fill="#e0607e" stroke="${OUT}" stroke-width="1.8"/>`)}
    ${g("fin", 56, 54, part("M56 54C54 63 47 65 45 60C47 56 51 54 56 54Z", "#f2b53a", 2.4))}` },
  "seahorse": { w: 6, move: "swim", kind: "seahorse", speed: 0.025, vb: "0 0 70 124", svg: `
    ${g("fin", 22, 60, part("M24 46C10 50 8 64 14 72C18 66 22 62 26 62Z", "#ffd27a", 2.4))}
    ${part("M32 16Q48 12 54 22L60 24Q62 30 56 30L44 30Q44 42 38 54Q32 70 40 82Q46 94 34 104Q22 110 24 98Q30 96 30 88Q18 72 24 54Q26 40 24 30Q22 18 32 16Z", "#ffb238")}
    ${line("M30 58h8M28 66h9M30 74h8M33 82h7M36 90h5", "#e08a1e", 2)}
    ${part("M30 16L26 4L34 10L37 2L39 13Z", "#ff8a3d", 2.4)}
    ${hi(32, 40, 3, 8, 10)}${eye(40, 22, 4.2)}` },
  "jellyfish": { w: 9, move: "swim", kind: "jelly", speed: 0.03, glow: true, vb: "0 0 90 124", clip: BODY.jelly, svg: `
    ${g("tentacles", 45, 50, [18, 28, 38, 52, 62, 72].map((x, i) =>
      line(`M${x} 48Q${x + (i % 2 ? 7 : -7)} 68 ${x} 86Q${x + (i % 2 ? -7 : 7)} 102 ${x} ${114 - (i % 3) * 6}`, "#f9a8d4", 3, `opacity=".85"`)).join("") +
      part("M38 48C34 66 42 80 36 96C44 88 48 70 46 48Z", "#f472b6", 2.4) + part("M50 48C54 70 46 84 54 100C58 84 58 66 54 48Z", "#f472b6", 2.4))}
    ${g("bell", 45, 6, fill(BODY.jelly, "#fbb6dc", `opacity=".92"`) + clip("jellyfish", fill(ell(45, 40, 26, 12), "#f8d5ea") +
      line("M24 18Q45 8 66 18", "#fff", 3, `opacity=".5"`)) + ink(BODY.jelly, 2.8) +
      hi(30, 18, 8, 4) + `<circle cx="36" cy="32" r="2.6" fill="${OUT}"/><circle cx="54" cy="32" r="2.6" fill="${OUT}"/>` + smile(45, 37, 0.8) +
      `<circle cx="29" cy="37" r="3" fill="#f472b6" opacity=".6"/><circle cx="61" cy="37" r="3" fill="#f472b6" opacity=".6"/>`)}` },
  "sea-turtle": { w: 15, move: "swim", kind: "turtle", speed: 0.035, vb: "0 0 140 90", clip: BODY.turtle, svg: `
    ${g("fin back", 96, 30, part("M92 26C104 10 116 4 120 10C116 18 104 26 96 32Z", "#6e9d3e"))}
    ${part("M36 34C28 26 20 22 14 24C18 30 26 36 34 40Z", "#6e9d3e")}
    ${part("M112 40C118 28 136 30 138 42C138 52 124 56 114 50Z", "#9ccc65")}${hi(124, 34, 5, 2)}${eye(127, 40, 4.4)}${smile(132, 48, 0.6)}
    ${fill(BODY.turtle, "#4e8f3e")}${clip("sea-turtle", fill("M0 56Q70 76 140 52L140 90L0 90Z", "#8fbf5a") +
      line("M70 18L84 30L78 48L62 48L56 30Z M38 38L56 30M38 38L44 54L62 48M102 38L84 30M102 38L94 54L78 48M70 18L70 8", "#2f5d2b", 2.6))}
    ${ink(BODY.turtle)}${hi(56, 24, 12, 4, -10)}
    ${g("fin", 96, 56, part("M96 54C104 70 112 82 104 86C94 84 86 72 86 58Z", "#8bc34a"))}
    ${part("M36 58C30 70 22 76 16 72C18 64 26 58 34 54Z", "#8bc34a")}` },
  "octopus": { w: 12, move: "swim", kind: "octopus", speed: 0.03, vb: "0 0 110 112", clip: BODY.octo, svg: `
    ${g("arms", 55, 60, [[26, -12], [34, -8], [44, -4], [52, -1], [60, 2], [68, 5], [78, 9], [86, 13]].map(([x, c], i) =>
      tube(`M${x} 56Q${x + c} 80 ${x + c * 0.4} 92Q${x - c * 0.3} 102 ${x + c * 0.7} ${104 - (i % 2) * 6}`, i % 2 ? "#b15cf0" : "#a14ce0", 7)).join(""))}
    ${fill(BODY.octo, "#b15cf0")}${clip("octopus", fill(ell(55, 64, 34, 10), "#9a46d6") +
      [[34, 20], [44, 12], [72, 18], [76, 30], [30, 34]].map(([x, y], i) => fill(ell(x, y, 3 + (i % 2), 2.6 + (i % 2)), "#cf96ff")).join(""))}
    ${ink(BODY.octo)}${hi(40, 16, 10, 4)}
    ${eye(42, 40, 7)}${eye(66, 40, 7)}${smile(54, 52, 1.2)}
    <circle cx="32" cy="50" r="4" fill="#ff8fc8" opacity=".6"/><circle cx="78" cy="50" r="4" fill="#ff8fc8" opacity=".6"/>` },
  "whale-shark": { w: 32, move: "swim", kind: "shark", speed: 0.03, vb: "0 0 280 110", clip: BODY.shark, svg: `
    ${part("M120 22C128 6 140 0 146 0C144 10 146 18 152 22Z", "#3d5d7d")}
    ${g("tail", 34, 56, part("M36 56C24 40 12 20 6 12C14 32 14 44 10 56C14 66 16 84 8 100C18 92 28 72 36 56Z", "#3d5d7d"))}
    ${fill(BODY.shark, "#4d6f91")}
    ${clip("whale-shark", fill("M0 62Q140 98 280 58L280 110L0 110Z", "#dbe6f0") +
      Array.from({ length: 48 }, (_, i) => {
        const col = i % 12, row = Math.floor(i / 12);
        return `<circle cx="${70 + col * 15 + (row % 2) * 7 + ((i * 7) % 5)}" cy="${28 + row * 9 + ((i * 3) % 4)}" r="${2.2 + ((i * 5) % 3) * 0.5}" fill="#e8f0f7"/>`;
      }).join("") +
      line("M90 24V68M120 20V70M150 18V72M180 20V74", "#e8f0f7", 1.6, `opacity=".6"`))}
    ${ink(BODY.shark, 3.4)}${line("M226 40q4 10 0 22M232 40q4 10 0 22M238 40q4 10 0 22", "#2c4560", 2)}
    ${hi(170, 26, 30, 4, -3)}
    ${g("fin", 196, 72, part("M196 72C190 88 178 100 168 100C172 88 180 78 190 70Z", "#3d5d7d"))}
    ${line("M244 68Q258 72 272 63", OUT, 3)}${eye(250, 48, 4)}` },

  // ---------------- coral & plants (sit on the sand) ----------------
  "seaweed": { w: 6, move: "bottom", vb: "0 0 60 130", svg: `
    ${[[18, 120, 9, 1.2, 0, "#2f9e44"], [40, 104, 8, 1.4, 2, "#40c057"], [30, 84, 7, 1, 4, "#51cf66"]].map(([x, len, w, wv, ph, c], i) =>
      g("sway", x, 128, part(ribbon(x, 128, len, w, wv, 7, ph), c, 2.6) + line(ribbon(x, 128, len * 0.8, 0.1, wv, 7, ph), "#2b8a3e", 1.2, `opacity=".5"`))).join("")}` },
  "brain-coral": { w: 10, move: "bottom", vb: "0 0 120 80", clip: BODY.brain, svg: `
    ${fill(BODY.brain, "#f4a261")}
    ${clip("brain-coral", [22, 32, 42, 52, 62, 72].map((y, i) =>
      line(`M0 ${y}` + Array.from({ length: 8 }, (_, k) => `q7.5 ${(k + i) % 2 ? 7 : -7} 15 0`).join(""), "#c96a2c", 3)).join(""))}
    ${ink(BODY.brain)}${hi(40, 24, 14, 5)}` },
  "fan-coral": { w: 11, move: "bottom", vb: "0 0 120 120", clip: BODY.fan, svg: `
    ${tube("M60 118L60 72M60 96L48 84", "#9d4edd", 6)}
    ${g("sway", 60, 118, fill(BODY.fan, "#d17bff") + clip("fan-coral",
      [-70, -45, -22, 0, 22, 45, 70].map((a) => line(`M60 76L${r1(60 + Math.sin((a * Math.PI) / 180) * 80)} ${r1(76 - Math.cos((a * Math.PI) / 180) * 80)}`, "#8a3fd1", 2.4)).join("") +
      [24, 40, 56].map((r) => line(`M${60 - r * 1.3} 76A${r * 1.3} ${r} 0 0 1 ${60 + r * 1.3} 76`, "#8a3fd1", 2)).join("")) +
      ink(BODY.fan) + hi(36, 22, 10, 4))}` },
  "staghorn-coral": { w: 10, move: "bottom", vb: "0 0 110 120", svg: `
    ${tube("M55 118L55 74L34 48L28 16M34 48L14 34M55 74L76 44L72 10M76 44L94 28M55 74L55 30", "#f08c4a", 11)}
    ${[[28, 16], [14, 34], [72, 10], [94, 28], [55, 30]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="5" fill="#ffd0a8"/>`).join("")}
    ${line("M52 100L52 78M32 44L28 22M74 40L72 16", "#fff", 2.4, `opacity=".45"`)}` },
  "anemone": { w: 9, move: "bottom", vb: "0 0 110 100", svg: `
    ${g("sway", 55, 74, Array.from({ length: 11 }, (_, i) => {
      const x = 15 + i * 8, tx = x + (i - 5) * 3 + (i % 2 ? 5 : -5), ty = 10 + Math.abs(i - 5) * 4;
      return tube(`M${x} 70Q${x - 10 + (i % 3) * 10} 40 ${tx} ${ty}`, i % 2 ? "#ff6fae" : "#ff9ecb", 6) +
        `<circle cx="${tx}" cy="${ty}" r="4.4" fill="#c084fc" stroke="${OUT}" stroke-width="2"/>`;
    }).join(""))}
    ${part("M14 72Q55 58 96 72L90 96Q55 104 20 96Z", "#e85d9c")}${line("M30 76L32 96M46 74L47 98M62 74L62 98M78 76L77 96", "#c2417a", 2)}` },
  "kelp-forest": { w: 16, move: "bottom", vb: "0 0 170 214", svg: `
    ${[[26, 196, "#6b8e23", 0], [64, 176, "#8aa53a", 1.5], [104, 204, "#6b8e23", 3], [142, 168, "#8aa53a", 4.5]].map(([x, len, c, ph], i) =>
      g("sway", x, 212, part(ribbon(x, 212, len, 10, 1.1, 14, ph), c, 2.6) +
        [0.35, 0.55, 0.75].map((t, j) => {
          const y = 212 - len * t, cx = x + Math.sin(t * 1.1 * Math.PI * 2 + ph) * 14 * t;
          return part(ell(r1(cx + (j % 2 ? 11 : -11)), r1(y), 11, 4.5), "#a3c25a", 2) + `<circle cx="${r1(cx)}" cy="${r1(y + 6)}" r="3.6" fill="#d4e27a" stroke="${OUT}" stroke-width="1.6"/>`;
        }).join(""))).join("")}` },

  // ---------------- decorations ----------------
  "pebbles": { w: 9, move: "bottom", vb: "0 0 110 46", svg: `
    ${[[22, 32, 17, 11, "#94a3b8"], [50, 34, 13, 9, "#cbd5e1"], [72, 30, 16, 12, "#64748b"], [94, 35, 11, 8, "#e2c9a6"], [38, 38, 8, 5.5, "#b6a28a"]].map(([x, y, rx, ry, c]) =>
      part(ell(x, y, rx, ry), c, 2.6) + hi(x - rx * 0.35, y - ry * 0.45, rx * 0.35, ry * 0.25)).join("")}` },
  "starfish": { w: 6, move: "bottom", vb: "0 0 90 90", svg: `
    ${part(star(45, 48, 40, 17), "#ff7b54")}
    ${[[45, 24], [26, 42], [64, 42], [34, 64], [56, 64], [45, 46]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.8" fill="#ffd3b6"/>`).join("")}
    ${hi(38, 34, 6, 3)}` },
  "bubbler": { w: 7, move: "bottom", bubbles: true, vb: "0 0 90 70", svg: `
    ${part("M8 52Q45 34 82 52Q80 68 45 68Q10 68 8 52Z", "#f2a7c9")}
    ${line("M24 50L22 64M36 46L35 66M48 45L48 67M60 46L61 66M72 49L74 64", "#d77aa6", 2)}
    <circle cx="45" cy="48" r="9" fill="#fff" stroke="${OUT}" stroke-width="2.4"/><circle cx="42" cy="45" r="3" fill="#fff" opacity=".9"/>
    <circle cx="45" cy="48" r="9" fill="url(#aq-shade)"/>
    ${g("lid", 10, 50, part("M8 50Q10 16 45 14Q80 16 82 50Q45 38 8 50Z", "#f7b9d6") +
      line("M20 44L28 22M34 40L38 17M48 39L48 15M62 40L58 17M74 44L66 22", "#d77aa6", 2))}` },
  "treasure-chest": { w: 11, move: "bottom", vb: "0 0 120 96", svg: `
    ${part("M14 40L22 8Q60 -2 98 8L106 40Z", "#8b5a2b")}${line("M30 40L34 8M86 40L82 8", "#ffd166", 4)}
    ${[[38, 34], [52, 28], [66, 32], [80, 34], [46, 38], [60, 38], [74, 39]].map(([x, y]) =>
      `<circle cx="${x}" cy="${y}" r="7" fill="#ffd166" stroke="#c99a1e" stroke-width="2"/>`).join("")}
    ${g("twinkle", 52, 22, fill(star(52, 22, 7, 2, 4, 0), "#fff"))}${g("twinkle t2", 78, 26, fill(star(78, 26, 5, 1.5, 4, 0), "#fff"))}
    ${part("M10 40H110V92H10Z", "#a0522d")}${line("M10 56H110M10 74H110", "#7a3e1d", 2)}
    ${line("M10 40H110M30 40V92M90 40V92", "#ffd166", 5)}
    ${part("M52 46H68V64H52Z", "#ffd166", 2.4)}<circle cx="60" cy="54" r="2.6" fill="${OUT}"/>
    ${hi(24, 50, 8, 2.5, 0)}` },
  "diver": { w: 9, move: "bottom", bubbles: true, vb: "0 0 100 136", svg: `
    ${tube("M20 30Q2 30 6 60Q10 84 26 80", "#3f3f46", 4)}
    ${part("M26 62H74L78 104H22Z", "#7d8fa6")}${line("M34 70V100M66 70V100", "#5c6c82", 2)}
    ${part("M24 102H46V128H24Z", "#7d8fa6")}${part("M54 102H76V128H54Z", "#7d8fa6")}
    ${part("M18 122H48V134H18Z", "#3f3f46")}${part("M52 122H82V134H52Z", "#3f3f46")}
    ${part("M8 64H28V78H8Z", "#d08b3e", 2.4)}${part("M72 64H92V78H72Z", "#d08b3e", 2.4)}
    ${part("M20 58H80V68H20Z", "#b8762e")}
    ${part(ell(50, 34, 28, 27), "#d08b3e")}${hi(36, 18, 8, 4)}
    ${part(ell(54, 36, 13, 13), "#9ad8ef", 4)}${hi(50, 31, 4, 2.6)}
    ${[[24, 34], [50, 10], [76, 34], [50, 56]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="3" fill="#ffd27a" stroke="${OUT}" stroke-width="1.6"/>`).join("")}` },
  "crystals": { w: 9, move: "bottom", glow: true, vb: "0 0 110 100", svg: `
    ${[["M18 98L14 54L26 30L38 52L34 98Z", "M26 30L38 52L34 98L26 98Z", "#67e8f9", "#22b8cf"],
       ["M42 98L40 34L56 4L72 32L68 98Z", "M56 4L72 32L68 98L55 98Z", "#c4b5fd", "#8b5cf6"],
       ["M70 98L70 58L84 38L96 58L92 98Z", "M84 38L96 58L92 98L83 98Z", "#f5b8fb", "#d946ef"],
       ["M30 98L28 76L38 64L46 76L44 98Z", "M38 64L46 76L44 98L37 98Z", "#a5f3fc", "#06b6d4"]].map(([d, facet, c, dark]) =>
      fill(d, c) + fill(facet, dark, `opacity=".55"`) + ink(d, 2.6)).join("")}
    ${hi(50, 30, 3, 9, 15)}${hi(22, 52, 2.4, 7, 15)}` },
  "castle": { w: 16, move: "bottom", vb: "0 0 170 160", clip: BODY.castle, svg: `
    ${g("flag", 85, 24, part("M85 24L85 4L108 10L85 18", "#ef4444", 2.4))}${line("M85 26V4", OUT, 2.6)}
    ${fill(BODY.castle, "#c3cbd6")}
    ${clip("castle", Array.from({ length: 12 }, (_, r) =>
      line(`M0 ${40 + r * 10}H170` + Array.from({ length: 9 }, (_, k) => `M${(k * 20 + (r % 2) * 10)} ${40 + r * 10}v10`).join(""), "#9aa4b2", 1.6)).join("") +
      fill("M14 136Q40 126 60 140L60 160L14 160Z", "#7fb069"))}
    ${ink(BODY.castle)}
    ${part("M8 30L31 2L54 30Z", "#4f7cd6")}${part("M116 30L139 2L162 30Z", "#4f7cd6")}
    ${[56, 70, 84, 98, 112].map((x) => part(`M${x - 2} 60V50H${x + 8}V60`, "#c3cbd6", 2.4)).join("")}
    ${part("M68 150V112Q85 92 102 112V150Z", "#3d405b")}${line("M85 100V150", "#2a2c40", 2)}
    ${part("M26 52Q31 44 36 52V68H26Z", "#3d405b", 2.2)}${part("M134 52Q139 44 144 52V68H134Z", "#3d405b", 2.2)}
    ${hi(28, 18, 6, 2.4, -40)}` },
  "sunken-ship": { w: 26, move: "bottom", vb: "0 0 280 150", clip: BODY.hull, svg: `
    <g transform="rotate(-7 130 110)">
      ${tube("M150 80L160 6", "#6b4423", 6)}${tube("M136 30L184 34", "#6b4423", 4)}
      ${g("sway", 160, 34, part("M158 36L190 38Q178 54 188 66Q170 62 154 70Q160 52 158 36Z", "#efe6d2", 2.6) + line("M166 44L172 60", "#d6cbb2", 2))}
      ${fill(BODY.hull, "#8b5a2b")}
      ${clip("sunken-ship", [60, 76, 92, 108, 124].map((y) => line(`M0 ${y}L280 ${y + 14}`, "#6b4423", 2.4)).join("") +
        fill("M0 112L280 126L280 150L0 150Z", "#5e3b23") + fill("M10 40H66V72H10Z", "#9c6a38") +
        line("M10 40H66M10 56H66", "#6b4423", 2.4))}
      ${ink(BODY.hull, 3.2)}
      ${line("M10 46L64 50L66 70L252 84", "#5e3b23", 5)}
      ${[[22, 58], [42, 60]].map(([x, y]) => part(`M${x} ${y}h10v8h-10Z`, "#ffd166", 2)).join("")}
      ${[96, 132, 168, 204].map((x) => `<circle cx="${x}" cy="${98 + x * 0.05}" r="7" fill="#2b2117" stroke="#d4a373" stroke-width="2.6"/>`).join("")}
      ${part("M226 92L250 70L254 78L234 98Z", "#7a4a22", 2.4)}
      ${g("sway", 214, 108, part(ribbon(214, 108, 46, 6, 1, 6, 1), "#40c057", 2.2))}
      ${g("sway", 80, 120, part(ribbon(80, 120, 40, 6, 1, 6, 3), "#2f9e44", 2.2))}
      ${hi(40, 48, 14, 2.4, 3)}
    </g>
    ${part("M0 150Q30 136 80 140Q140 146 190 140Q240 136 280 150Z", "#e5c48e", 2.6)}` },
};

// Water and sand palettes for the tank upgrades.
const WATER = {
  default: ["#a5e6ff", "#2ea8e4", "#0b5d9c", "#0c4f86"],
  "bg-reef": ["#a0f4ff", "#14a6c6", "#0e5f78", "#0d6a83"],
  "bg-deep": ["#3a64c4", "#13286a", "#060c26", "#0a1640"],
  "bg-lagoon": ["#d2fdff", "#4fe0d2", "#128c84", "#0f7f78"],
};
const SAND = {
  default: ["#f7e0b0", "#e5c48e", "#c9a46b"],
  "sand-pink": ["#fbd3df", "#f0aec3", "#d98aa5"],
  "sand-black": ["#5c5c6c", "#424250", "#2a2a34"],
};
export const SAND_TOP = 0.86;   // where the seabed starts, as a share of tank height

// Shared gradients and body clip paths, defined once for every SVG on the page.
(function defs() {
  if (document.getElementById("aq-defs")) return;
  const grad = (id, stops, attrs = `x1="0" y1="0" x2="0" y2="1"`) =>
    `<linearGradient id="${id}" ${attrs}>${stops.map(([o, c, a = 1]) => `<stop offset="${o}" stop-color="${c}" stop-opacity="${a}"/>`).join("")}</linearGradient>`;
  const svg = `<svg id="aq-defs" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
    ${grad("aq-shade", [[0, "#fff", 0.3], [0.32, "#fff", 0], [0.58, "#0a1630", 0], [0.6, "#0a1630", 0.18], [1, "#0a1630", 0.3]])}
    ${grad("aq-ray", [[0, "#fff", 0.55], [1, "#fff", 0]])}
    ${Object.entries(WATER).map(([k, [a, b, c]]) => grad(`aq-water-${k}`, [[0, a], [0.55, b], [1, c]])).join("")}
    ${Object.entries(SAND).map(([k, [a, b]]) => grad(`aq-sand-${k}`, [[0, a], [1, b]])).join("")}
    <radialGradient id="aq-shadow"><stop offset="0" stop-color="#000" stop-opacity=".35"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
    ${Object.entries(ART).filter(([, a]) => a.clip).map(([id, a]) => `<clipPath id="aq-clip-${id}"><path d="${a.clip}"/></clipPath>`).join("")}
  </defs></svg>`;
  document.body.insertAdjacentHTML("afterbegin", svg);
})();

// The tank backdrop: water, light rays, surface ripples, distant rocks, drifting specks and the seabed.
// Drawn in a 160×100 box, the same shape as the tank, so nothing is stretched.
export function sceneSvg(bg, sand) {
  const w = WATER[bg] ? bg : "default", s = SAND[sand] ? sand : "default";
  const [, , , back] = WATER[w];
  const [s1, s2, s3] = SAND[s];
  const extras = {
    "bg-reef": [[14, "#ff9ec7"], [44, "#ffb37a"], [118, "#c9a0ff"], [146, "#ff9ec7"]].map(([x, c]) =>
      `<path d="M${x} 84Q${x - 8} 70 ${x - 6} 62M${x} 84Q${x + 2} 66 ${x + 1} 58M${x} 84Q${x + 9} 72 ${x + 8} 64" stroke="${c}" stroke-width="2.4" fill="none" stroke-linecap="round" opacity=".45"/>`).join(""),
    "bg-deep": `<path d="M0 86L6 50L12 60L18 34L26 86ZM120 86L128 56L134 64L142 40L152 86Z" fill="#020617" opacity=".55"/>`,
    "bg-lagoon": `<path d="M0 30Q40 26 80 30T160 30" stroke="#fff" stroke-width=".6" fill="none" opacity=".3"/>`,
    default: [[12, 1], [34, 3], [126, 2], [150, 4]].map(([x, p]) =>
      `<path d="${ribbon(x, 86, 24 + p * 3, 2.4, 1, 3, p)}" fill="${back}" opacity=".3"/>`).join(""),
  }[w];
  const rays = [18, 50, 84, 116, 146].map((x, i) =>
    `<path class="ray" style="animation-delay:-${i * 2.3}s" d="M${x} -2L${x + 7} -2L${x + 26} 90L${x + 8} 90Z" fill="url(#aq-ray)"/>`).join("");
  const motes = Array.from({ length: 16 }, (_, i) =>
    `<circle class="mote" style="animation-delay:-${(i * 1.7) % 14}s" cx="${(i * 37) % 160}" cy="${20 + ((i * 23) % 60)}" r="${0.35 + (i % 3) * 0.2}" fill="#fff"/>`).join("");
  const wave = Array.from({ length: 10 }, () => "q5 -1.6 10 0q5 1.6 10 0").join("");
  const pebbles = [[20, 93, "#94a3b8"], [23, 94.5, "#cbd5e1"], [70, 95, "#a8a29e"], [104, 92.5, "#94a3b8"], [138, 95, "#d6d3d1"], [141, 96, "#78716c"]].map(([x, y, c]) =>
    `<ellipse cx="${x}" cy="${y}" rx="2" ry="1.2" fill="${c}"/>`).join("");
  const shells = [[48, 96], [122, 97]].map(([x, y]) =>
    `<path d="M${x - 2} ${y}Q${x} ${y - 3.4} ${x + 2} ${y}Z" fill="#fde2e4" stroke="${s3}" stroke-width=".3"/>`).join("");
  return `<svg class="scene-svg" viewBox="0 0 160 100" preserveAspectRatio="none" aria-hidden="true">
    <rect width="160" height="100" fill="url(#aq-water-${w})"/>
    <g class="rays">${rays}</g>
    <path d="M0 88L0 70Q14 60 28 70T60 66Q78 58 96 68T130 64Q146 58 160 66L160 88Z" fill="${back}" opacity=".35"/>
    <path d="M0 88L0 78Q22 70 44 78T88 76Q112 70 136 78T160 76L160 88Z" fill="${back}" opacity=".3"/>
    ${extras}
    <g class="motes">${motes}</g>
    <g class="surface"><path d="M0 3${wave}${wave}V0H0Z" transform="translate(0 0)" fill="#fff" opacity=".35"/>
      <path d="M0 5${wave}${wave}" stroke="#fff" stroke-width=".5" fill="none" opacity=".35"/></g>
    <path d="M0 100V88Q20 82 44 86T92 84Q120 80 160 86V100Z" fill="${s2}"/>
    <path d="M0 100V91Q30 86 64 90T120 89Q140 87 160 90V100Z" fill="url(#aq-sand-${s})"/>
    <path d="M10 95q6 -1.4 12 0M60 97q6 -1.4 12 0M100 94q6 -1.4 12 0M140 97q5 -1.2 10 0" stroke="${s3}" stroke-width=".5" fill="none" opacity=".6"/>
    ${pebbles}${shells}
  </svg>`;
}

export function artSvg(id, cls = "") {
  const a = ART[id];
  return a ? `<svg class="${cls}" viewBox="${a.vb}" xmlns="http://www.w3.org/2000/svg">${a.svg}</svg>` : "";
}
