// WebGL water sheet: a band of water whose leading and trailing surfaces sweep up
// the screen. Refraction samples the page background; caustics, a fresnel-weighted
// mirror of the scene above the waterline, specular glints and foam sit on top.

const VERTEX = `
attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

const FRAGMENT = `
precision highp float;

uniform vec2 uRes;
uniform vec2 uTexRes;
uniform float uTime;
uniform float uFront;
uniform float uBack;
uniform float uCrash;
uniform float uRotate;
uniform sampler2D uTex;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

// Spray droplets thrown above the crest when the water crashes into the top.
float spray(vec2 p, float front, float t) {
  float lift = p.y - front;
  if (lift < 0.0 || lift > 0.22) return 0.0;
  vec2 cell = floor(p * 38.0 + vec2(0.0, -t * 9.0));
  float h = hash(cell);
  if (h < 0.82) return 0.0;
  vec2 local = fract(p * 38.0 + vec2(0.0, -t * 9.0)) - 0.5 - (vec2(hash(cell + 3.1), hash(cell + 7.7)) - 0.5) * 0.5;
  float r = 0.12 + 0.18 * hash(cell + 1.3);
  return smoothstep(r, r * 0.4, length(local)) * smoothstep(0.22, 0.0, lift);
}

// Sum of travelling sines: the wave profile of a surface.
float wave(float x, float t, float seed) {
  return 0.034 * sin(x * 3.1 + t * 1.3 + seed)
       + 0.021 * sin(x * 7.3 - t * 1.9 + seed * 2.0)
       + 0.011 * sin(x * 13.7 + t * 2.7 + seed * 3.0)
       + 0.005 * sin(x * 23.0 - t * 3.6 + seed * 5.0);
}

// Small-scale height field used for normals, refraction and glints.
float ripples(vec2 p, float t) {
  return 0.50 * sin(p.x * 5.0 + t * 1.1) * sin(p.y * 4.0 - t * 0.8)
       + 0.25 * sin((p.x + p.y) * 9.0 + t * 1.7)
       + 0.15 * sin((p.x - p.y * 1.3) * 15.0 - t * 2.3);
}

// Warped interference lines that read as caustic light ribbons.
float caustics(vec2 p, float t) {
  p *= 3.2;
  float c = 0.0;
  for (int i = 0; i < 3; i++) {
    p += vec2(sin(p.y * 1.7 + t * 0.9), cos(p.x * 1.3 - t * 0.7)) * 0.62;
    c += abs(sin(p.x) * cos(p.y));
  }
  return pow(1.0 - c / 3.0, 7.0) * 2.2;
}

// object-fit: cover mapping from screen uv (y up) to texture uv (y down). On tall
// screens the background is turned 90 degrees clockwise, matching the page CSS.
vec3 scene(vec2 uv) {
  vec2 q = uRotate > 0.5 ? vec2(1.0 - uv.y, uv.x) : uv;
  float sr = uRotate > 0.5 ? uRes.y / uRes.x : uRes.x / uRes.y;
  float tr = uTexRes.x / uTexRes.y;
  vec2 s = sr > tr ? vec2(1.0, tr / sr) : vec2(sr / tr, 1.0);
  vec2 t = (q - 0.5) * s + 0.5;
  return texture2D(uTex, vec2(t.x, 1.0 - t.y)).rgb;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  float aspect = uRes.x / uRes.y;
  float ax = uv.x * aspect;
  float t = uTime;
  float px = 1.5 / uRes.y;

  // The crest surges and grows choppy as it crashes into the top edge.
  float front = uFront + wave(ax, t, 0.0) * (1.0 + 2.5 * uCrash)
              + uCrash * 0.03 * sin(ax * 31.0 + t * 12.0);
  float back = uBack + wave(ax, t * 1.1, 4.0);
  float below = front - uv.y;      // depth under the leading surface
  float above = uv.y - back;       // height above the trailing surface

  float inside = smoothstep(-px, px, below) * smoothstep(-px, px, above);

  // Thin bright lines on both surfaces, and a wet sheen behind the trailing edge.
  float frontLine = exp(-pow(below / (2.2 * px), 2.0));
  float backLine = exp(-pow(above / (2.2 * px), 2.0)) * step(-0.2, uBack);
  float sheen = above < 0.0 ? exp(above * 18.0) * 0.18 * step(-0.2, uBack) : 0.0;

  float drops = uCrash > 0.0 ? spray(vec2(ax, uv.y), front, t) * uCrash : 0.0;

  if (inside < 0.002 && frontLine < 0.01 && backLine < 0.01 && sheen < 0.004 && drops < 0.01) {
    gl_FragColor = vec4(0.0);
    return;
  }

  vec2 p = vec2(ax, uv.y);
  float e = 0.0025;
  float h = ripples(p, t);
  vec2 grad = vec2(ripples(p + vec2(e, 0.0), t) - h, ripples(p + vec2(0.0, e), t) - h) / e;
  vec3 n = normalize(vec3(-grad * 0.035, 1.0));
  float depth = clamp(below, 0.0, 2.0);

  // Refraction with slight chromatic dispersion.
  vec2 off = n.xy * (0.018 + 0.03 * min(depth, 1.0));
  vec3 refr = vec3(
    scene(uv + off * 1.00).r,
    scene(uv + off * 1.25).g,
    scene(uv + off * 1.50).b
  );

  // Absorption and tint toward deep teal with depth.
  vec3 deep = vec3(0.015, 0.20, 0.27);
  vec3 col = refr * exp(-depth * vec3(2.4, 1.0, 0.7));
  col = mix(col, deep, 0.42 + 0.38 * smoothstep(0.0, 0.7, depth));

  // Caustic ribbons, brightest near the surface.
  float c = caustics(p + n.xy * 0.4 + vec2(0.0, t * 0.05), t);
  col += vec3(0.75, 1.0, 0.95) * c * (0.12 + 0.30 * exp(-depth * 3.0));

  // Fresnel: near the waterline the surface mirrors the scene above it.
  float grazing = pow(1.0 - clamp(depth / 0.16, 0.0, 1.0), 3.0);
  float fresnel = 0.04 + 0.96 * pow(1.0 - n.z, 5.0);
  float f = clamp(grazing * 0.75 + fresnel * 4.0, 0.0, 0.85);
  vec2 mirror = vec2(uv.x, front + below) + n.xy * 0.05;
  vec3 refl = scene(clamp(mirror, 0.0, 1.0)) * 1.08;
  col = mix(col, refl, f);

  // Specular glints from a light above and to the left.
  vec3 l = normalize(vec3(-0.35, 0.6, 0.72));
  float spec = pow(max(dot(reflect(-l, n), vec3(0.0, 0.0, 1.0)), 0.0), 90.0);
  col += vec3(1.0) * spec * 0.9 * (0.4 + 0.6 * exp(-depth * 4.0));

  // Foam: a broken white band just under each surface.
  float foamNoise = 0.5 + 0.5 * sin(ax * 41.0 + t * 3.0) * sin(ax * 17.0 - t * 2.1 + h * 3.0);
  float foamWidth = 0.022 + 0.12 * uCrash;
  float foam = (smoothstep(foamWidth, 0.0, below) + smoothstep(0.016, 0.0, above) * step(-0.2, uBack))
             * smoothstep(0.35 - 0.3 * uCrash, 0.9, foamNoise) * inside;
  col = mix(col, vec3(0.97, 0.99, 1.0), foam * 0.75);

  // Opaque body; slightly translucent right at each surface.
  float alpha = inside * mix(0.9, 1.0, smoothstep(0.0, 0.08, min(below, above)));
  vec3 outCol = col * alpha;
  float lines = max(frontLine, backLine) * 0.9;
  outCol += vec3(1.0) * lines;
  outCol += vec3(1.0, 0.98, 0.95) * sheen * (0.5 + 0.5 * c);
  outCol += vec3(0.95, 0.99, 1.0) * drops;
  alpha = clamp(alpha + lines + sheen * 0.6 + drops, 0.0, 1.0);

  gl_FragColor = vec4(outCol, alpha);
}
`;

export type WaterLevels = { front: number; back: number; crash?: number };

/** Crest height (0 bottom, 1 top) at screen x, matching the shader's leading surface. */
export function crestAt(xUnit: number, aspect: number, time: number, front: number, crash: number) {
  const x = xUnit * aspect;
  const t = time;
  const wave =
    0.034 * Math.sin(x * 3.1 + t * 1.3) +
    0.021 * Math.sin(x * 7.3 - t * 1.9) +
    0.011 * Math.sin(x * 13.7 + t * 2.7) +
    0.005 * Math.sin(x * 23.0 - t * 3.6);
  return front + wave * (1 + 2.5 * crash) + crash * 0.03 * Math.sin(x * 31.0 + t * 12.0);
}

export type Water = {
  render: (time: number, levels: WaterLevels) => void;
  resize: () => void;
  dispose: () => void;
};

function compile(gl: WebGLRenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("shader");
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(log ?? "shader compile failed");
  }
  return shader;
}

/** Create the water renderer, or return null when WebGL is unavailable. */
export function createWater(canvas: HTMLCanvasElement, textureUrl: string): Water | null {
  const gl = canvas.getContext("webgl", { premultipliedAlpha: true, antialias: false });
  if (!gl) return null;

  let program: WebGLProgram;
  try {
    program = gl.createProgram() as WebGLProgram;
    gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  } catch {
    return null;
  }
  gl.useProgram(program);

  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const aPos = gl.getAttribLocation(program, "aPos");
  gl.enableVertexAttribArray(aPos);
  gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

  const u = (name: string) => gl.getUniformLocation(program, name);
  const uRes = u("uRes");
  const uTexRes = u("uTexRes");
  const uTime = u("uTime");
  const uFront = u("uFront");
  const uBack = u("uBack");
  const uCrash = u("uCrash");
  const uRotate = u("uRotate");

  // A neutral pixel until the background image has loaded.
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([230, 200, 190, 255]));
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.uniform2f(uTexRes, 16, 9);

  const image = new Image();
  image.onload = () => {
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    gl.uniform2f(uTexRes, image.naturalWidth, image.naturalHeight);
  };
  image.src = textureUrl;

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const width = Math.round(canvas.clientWidth * dpr);
    const height = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    gl.viewport(0, 0, width, height);
    gl.uniform2f(uRes, width, height);
    gl.uniform1f(uRotate, height > width ? 1 : 0);
  };
  resize();

  return {
    render(time, { front, back, crash = 0 }) {
      gl.uniform1f(uTime, time);
      gl.uniform1f(uFront, front);
      gl.uniform1f(uBack, back);
      gl.uniform1f(uCrash, crash);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    },
    resize,
    dispose() {
      gl.deleteTexture(texture);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
    },
  };
}
