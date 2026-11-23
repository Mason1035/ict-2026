<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const props = defineProps<{
  score: number;
  sensors: {
    moisture: number | null;
    tilt: number | null;
    vibration: number | null;
    rain: number | null;
    crack: number | null;
  };
  running: boolean;
  elapsed: number;
  resetKey?: string;
  gatewayOnline?: boolean;
  unknown?: boolean;
  platform?: boolean;
  deviceLabel?: string;
}>();
const emit = defineEmits<{ select: [node: string] }>();
const surface = ref<HTMLDivElement>();
const mode = ref<"standard" | "heatmap" | "sensors">("standard");
const selected = ref<string | null>(null);
const fallback = ref(false);
const overhead = ref(false);
const markerElements = new Map<string, HTMLElement>();
const nodes = [
  {
    id: "soil",
    name: "SOIL-1",
    detail: "土壤湿度",
    device: "SEN0193 · ADS1115",
    x: -2.0,
    z: 1.6,
  },
  {
    id: "imu",
    name: "IMU-1",
    detail: "地表倾斜",
    device: "ICM-42688-P",
    x: 0.55,
    z: -0.1,
  },
  {
    id: "vibration",
    name: "VIB-1",
    detail: "微振动",
    device: "ICM-42688-P",
    x: 2.8,
    z: 1.25,
  },
  {
    id: "rain",
    name: "RAIN",
    detail: "降雨强度",
    device: "场景模拟数据",
    x: -3.4,
    z: -1.75,
  },
  {
    id: "crack",
    name: "CRACK",
    detail: "裂缝变化",
    device: "场景模拟数据",
    x: 2.35,
    z: -1.35,
  },
  {
    id: "gateway",
    name: "GW-01",
    detail: "网关上行",
    device: "模拟网关",
    x: -4.4,
    z: 3.15,
  },
];
const activeNode = computed(() => nodes.find((n) => n.id === selected.value));
const riskColor = computed(() =>
  props.unknown ? "#929c95" : props.score < 30
    ? "#438668"
    : props.score < 60
      ? "#c49b38"
      : props.score < 80
        ? "#ce7548"
        : "#bf4b48",
);
const detailValue = computed(() => {
  if (!activeNode.value) return "";
  const format = (value: number | null, unit: string, decimals = 1) => value == null ? "—" : `${value.toFixed(decimals)} ${unit}`;
  const values: Record<string, string> = {
    soil: format(props.sensors.moisture, "%"),
    imu: format(props.sensors.tilt, "°"),
    vibration: format(props.sensors.vibration, "g", 3),
    rain: format(props.sensors.rain, "mm/h"),
    crack: format(props.sensors.crack, "mm"),
    gateway: props.platform && props.gatewayOnline == null ? "状态未知" : props.gatewayOnline === false ? "上行未就绪" : "上行可用",
  };
  return values[activeNode.value.id];
});
function selectNode(id: string) {
  selected.value = selected.value === id ? null : id;
  emit("select", id);
  requestRender();
}
function registerMarker(id: string, el: unknown) {
  if (el instanceof HTMLElement) markerElements.set(id, el);
  else markerElements.delete(id);
}

let renderer: THREE.WebGLRenderer | undefined;
let scene: THREE.Scene | undefined;
let camera: THREE.OrthographicCamera | undefined;
let controls: OrbitControls | undefined;
let resizeObserver: ResizeObserver | undefined;
let frame: number | undefined;
let lastFrame = 0;
let width = 1,
  height = 1;
let reducedMotion = false;
let mediaQuery: MediaQueryList | undefined;
let disposed = false;
let visualScore = props.score;
let visualTime = props.elapsed;
let weatherTime = props.elapsed;
let sampleStamp = 0;
let observedSpeed = 1;
let paintedScore = -1,
  paintedDisplacement = -1;
let mesh: THREE.Mesh | undefined;
let geometry: THREE.BufferGeometry | undefined;
let basePositions = new Float32Array();
let weights = new Float32Array();
let baseColors = new Float32Array();
let rain: THREE.Points | undefined;
let treeCrowns: THREE.InstancedMesh | undefined;
let treeTops: THREE.InstancedMesh | undefined;
let treeTrunks: THREE.InstancedMesh | undefined;
let trees: {
  x: number;
  z: number;
  y: number;
  size: number;
  weight: number;
  rotation: number;
}[] = [];
let sensorObjects: {
  node: (typeof nodes)[number];
  group: THREE.Group;
  y: number;
  weight: number;
}[] = [];
const deformLines: {
  geometry: THREE.BufferGeometry;
  base: Float32Array;
  weights: Float32Array;
}[] = [];
const crackMaterials: THREE.LineBasicMaterial[] = [];
const rainSeeds: { x: number; z: number; offset: number; speed: number }[] = [];
const matrix = new THREE.Object3D();
const tempVector = new THREE.Vector3();
const green = new THREE.Color("#81a783"),
  yellow = new THREE.Color("#d5b55e");
const orange = new THREE.Color("#d68b57"),
  red = new THREE.Color("#ca6760");
const currentRiskColor = new THREE.Color();

// Deterministic fictional topography. This is a model specimen, not a geographic DEM.
function terrainHeight(x: number, z: number) {
  const hill =
    3.75 * Math.exp(-(((x + 1.1) / 3.5) ** 2 + ((z + 1.05) / 3.0) ** 2));
  const ridge =
    1.85 * Math.exp(-(((x + 3.75) / 1.65) ** 2 + ((z - 0.25) / 2.5) ** 2));
  const shoulder =
    0.86 * Math.exp(-(((x - 1.65) / 2.1) ** 2 + ((z + 2.65) / 1.1) ** 2));
  const rough =
    0.13 * Math.sin(x * 2.1 + z * 0.9) +
    0.075 * Math.cos(z * 3.35 - x * 1.15) +
    0.038 * Math.sin(x * 7.2 + z * 4.1) +
    0.032 * Math.cos(x * 4.7 - z * 8);
  return 0.46 + hill + ridge + shoulder + rough;
}
function influence(x: number, z: number) {
  return Math.exp(-(((x - 1.65) / 2.1) ** 2 + ((z - 0.9) / 1.7) ** 2) * 1.35);
}
function displacement(score = visualScore) {
  if (props.unknown) return 0;
  const severity = Math.max(0, (score - 60) / 40);
  return (
    severity *
    (0.36 + (score >= 80 ? 0.28 * (1 - Math.exp(-visualTime / 42)) : 0))
  );
}
function riskTint(score: number) {
  if (props.unknown) return currentRiskColor.set("#9baa9b");
  if (score < 30)
    currentRiskColor.copy(green).lerp(yellow, Math.max(0, score - 18) / 40);
  else if (score < 60)
    currentRiskColor.copy(yellow).lerp(orange, (score - 30) / 40);
  else if (score < 80)
    currentRiskColor.copy(orange).lerp(red, (score - 60) / 30);
  else currentRiskColor.copy(red);
  return currentRiskColor;
}
function requestRender() {
  if (
    !disposed &&
    !document.hidden &&
    renderer &&
    !fallback.value &&
    frame === undefined
  )
    frame = requestAnimationFrame(renderFrame);
}
function makeSurface() {
  const nx = 132,
    nz = 96;
  const positions: number[] = [],
    colors: number[] = [],
    indices: number[] = [],
    patch: number[] = [];
  const c = new THREE.Color();
  for (let i = 0; i <= nx; i++)
    for (let j = 0; j <= nz; j++) {
      const x = (i / nx) * 12 - 6,
        z = (j / nz) * 9 - 4.5,
        y = terrainHeight(x, z);
      positions.push(x, y, z);
      const dx =
        (terrainHeight(x + 0.06, z) - terrainHeight(x - 0.06, z)) / 0.12;
      const dz =
        (terrainHeight(x, z + 0.06) - terrainHeight(x, z - 0.06)) / 0.12;
      const slope = Math.sqrt(dx * dx + dz * dz);
      const mineral = Math.max(0, Math.min(1, (slope - 0.64) * 1.7));
      const mottling =
        (Math.sin(x * 4.4 + z * 5.7) * Math.sin(x * 7.6 - z * 3.3) + 1) * 0.5;
      c.set("#9daf89")
        .lerp(new THREE.Color("#71896b"), y / 7)
        .lerp(new THREE.Color("#b4b4a0"), mineral * 0.7);
      c.lerp(new THREE.Color("#c8c5b2"), mottling * 0.13);
      // Exposed pale limestone across the upper shoulder makes the cutaway legible.
      const limestone =
        Math.max(0, Math.sin(x * 0.82 - z * 0.63 + 2.2) - 0.67) *
        2.7 *
        Math.min(1, slope);
      c.lerp(new THREE.Color("#c6c6b4"), limestone);
      colors.push(c.r, c.g, c.b);
      patch.push(influence(x, z));
      if (i < nx && j < nz) {
        const a = i * (nz + 1) + j,
          b = a + nz + 1;
        indices.push(a, a + 1, b, b, a + 1, b + 1);
      }
    }
  geometry = new THREE.BufferGeometry();
  basePositions = new Float32Array(positions);
  baseColors = new Float32Array(colors);
  weights = new Float32Array(patch);
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  mesh = new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.98,
      metalness: 0,
    }),
  );
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  scene!.add(mesh);

  // Four exposed sediment bands around the specimen, with natural upper edges.
  const perimeter: [number, number][] = [];
  for (let i = 0; i <= nx; i++) perimeter.push([-6 + (i / nx) * 12, -4.5]);
  for (let i = 1; i <= nz; i++) perimeter.push([6, -4.5 + (i / nz) * 9]);
  for (let i = nx - 1; i >= 0; i--) perimeter.push([-6 + (i / nx) * 12, 4.5]);
  for (let i = nz - 1; i >= 0; i--) perimeter.push([-6, -4.5 + (i / nz) * 9]);
  const strata = [-1.03, -0.69, -0.3, 0.08];
  const strataColors = ["#a7a08c", "#b6ae97", "#c0b7a1", "#ccc4ad"];
  for (let layer = 0; layer < 4; layer++) {
    const p: number[] = [],
      idx: number[] = [];
    perimeter.forEach(([x, z], i) => {
      const upper = layer === 3 ? terrainHeight(x, z) : strata[layer + 1]!;
      p.push(x, strata[layer]!, z, x, upper, z);
      const next = ((i + 1) % perimeter.length) * 2,
        a = i * 2;
      idx.push(a, next, a + 1, next, next + 1, a + 1);
    });
    const side = new THREE.BufferGeometry();
    side.setAttribute("position", new THREE.Float32BufferAttribute(p, 3));
    side.setIndex(idx);
    side.computeVertexNormals();
    const band = new THREE.Mesh(
      side,
      new THREE.MeshStandardMaterial({
        color: strataColors[layer],
        roughness: 1,
        side: THREE.DoubleSide,
      }),
    );
    band.castShadow = true;
    band.receiveShadow = true;
    scene!.add(band);
    if (layer) {
      const seamPoints = perimeter.map(
        ([x, z]) => new THREE.Vector3(x * 1.0002, strata[layer]!, z * 1.0002),
      );
      seamPoints.push(seamPoints[0]!.clone());
      scene!.add(
        new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(seamPoints),
          new THREE.LineBasicMaterial({
            color: "#8b8675",
            opacity: 0.35,
            transparent: true,
          }),
        ),
      );
    }
  }
  const base = new THREE.Mesh(
    new THREE.BoxGeometry(12.18, 0.16, 9.18),
    new THREE.MeshStandardMaterial({ color: "#c5c3b6", roughness: 0.92 }),
  );
  base.position.y = -1.12;
  base.receiveShadow = true;
  base.castShadow = true;
  scene!.add(base);
}
function addFollowingLine(
  points: THREE.Vector3[],
  material: THREE.LineBasicMaterial,
  segments = false,
) {
  const lineGeometry = new THREE.BufferGeometry().setFromPoints(points);
  const line = segments
    ? new THREE.LineSegments(lineGeometry, material)
    : new THREE.Line(lineGeometry, material);
  deformLines.push({
    geometry: lineGeometry,
    base: new Float32Array(lineGeometry.getAttribute("position").array),
    weights: new Float32Array(points.map((p) => influence(p.x, p.z))),
  });
  scene!.add(line);
  return line;
}
function makeContours() {
  const resolution = 0.15;
  const material = new THREE.LineBasicMaterial({
    color: "#e0e3cd",
    transparent: true,
    opacity: 0.27,
    depthWrite: false,
  });
  const points: THREE.Vector3[] = [];
  for (let level = 0.9; level <= 5.15; level += 0.36) {
    for (let x = -5.95; x < 5.9; x += resolution)
      for (let z = -4.45; z < 4.4; z += resolution) {
        const corners: [number, number][] = [
          [x, z],
          [x + resolution, z],
          [x + resolution, z + resolution],
          [x, z + resolution],
        ];
        const crossings: THREE.Vector3[] = [];
        for (let k = 0; k < 4; k++) {
          const a = corners[k]!,
            b = corners[(k + 1) % 4]!,
            ya = terrainHeight(a[0], a[1]),
            yb = terrainHeight(b[0], b[1]);
          if (ya < level !== yb < level) {
            const t = (level - ya) / (yb - ya);
            crossings.push(
              new THREE.Vector3(
                a[0] + (b[0] - a[0]) * t,
                level + 0.022,
                a[1] + (b[1] - a[1]) * t,
              ),
            );
          }
        }
        if (crossings.length >= 2) points.push(crossings[0]!, crossings[1]!);
        if (crossings.length === 4) points.push(crossings[2]!, crossings[3]!);
      }
  }
  addFollowingLine(points, material, true);
}
function makeRoad() {
  const anchors = [
    new THREE.Vector2(-6, 2.55),
    new THREE.Vector2(-4.6, 2.8),
    new THREE.Vector2(-3.35, 2.8),
    new THREE.Vector2(-2.4, 2.45),
    new THREE.Vector2(-1.4, 2.8),
    new THREE.Vector2(-0.4, 3.3),
    new THREE.Vector2(1.15, 3.25),
    new THREE.Vector2(2.65, 2.95),
    new THREE.Vector2(4.2, 3.25),
    new THREE.Vector2(6, 2.75),
  ];
  const path = new THREE.SplineCurve(anchors).getPoints(180);
  const positions: number[] = [],
    indices: number[] = [];
  path.forEach((p, i) => {
    const next = path[Math.min(i + 1, path.length - 1)]!,
      prev = path[Math.max(0, i - 1)]!;
    const dir = next.clone().sub(prev).normalize(),
      side = new THREE.Vector2(-dir.y, dir.x).multiplyScalar(0.105);
    for (const sign of [-1, 1]) {
      const x = p.x + side.x * sign,
        z = p.y + side.y * sign;
      positions.push(x, terrainHeight(x, z) + 0.032, z);
    }
    if (i < path.length - 1) {
      const a = i * 2;
      indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
    }
  });
  const roadGeometry = new THREE.BufferGeometry();
  roadGeometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
  roadGeometry.setIndex(indices);
  roadGeometry.computeVertexNormals();
  const road = new THREE.Mesh(
    roadGeometry,
    new THREE.MeshStandardMaterial({
      color: "#d4cebb",
      roughness: 1,
      side: THREE.DoubleSide,
    }),
  );
  road.receiveShadow = true;
  scene!.add(road);
  deformLines.push({
    geometry: roadGeometry,
    base: new Float32Array(positions),
    weights: new Float32Array(
      path.flatMap((p) => [influence(p.x, p.y), influence(p.x, p.y)]),
    ),
  });
  addFollowingLine(
    path.map(
      (p) => new THREE.Vector3(p.x, terrainHeight(p.x, p.y) + 0.045, p.y),
    ),
    new THREE.LineBasicMaterial({
      color: "#e8e3d4",
      opacity: 0.75,
      transparent: true,
    }),
  );
}
function makeTrees() {
  // A fixed seed avoids new vegetation appearing on rerender or simulation reset.
  let seed = 47281;
  const random = () => {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  trees = [];
  for (let i = 0; i < 70; i++) {
    let x = 0,
      z = 0;
    for (let tries = 0; tries < 40; tries++) {
      x = random() * 10.8 - 5.4;
      z = random() * 7.6 - 3.8;
      if (
        influence(x, z) < 0.55 &&
        !(z > 2.2 && z < 3.6) &&
        nodes.every((n) => Math.hypot(n.x - x, n.z - z) > 0.5)
      )
        break;
    }
    trees.push({
      x,
      z,
      y: terrainHeight(x, z),
      size: 0.72 + random() * 0.6,
      weight: influence(x, z),
      rotation: random() * Math.PI,
    });
  }
  treeTrunks = new THREE.InstancedMesh(
    new THREE.CylinderGeometry(0.028, 0.045, 0.4, 5),
    new THREE.MeshStandardMaterial({ color: "#807b60", roughness: 1 }),
    trees.length,
  );
  treeCrowns = new THREE.InstancedMesh(
    new THREE.ConeGeometry(0.22, 0.57, 6),
    new THREE.MeshStandardMaterial({
      color: "#567458",
      roughness: 1,
      flatShading: true,
    }),
    trees.length,
  );
  treeTops = new THREE.InstancedMesh(
    new THREE.ConeGeometry(0.175, 0.47, 6),
    new THREE.MeshStandardMaterial({
      color: "#6a8967",
      roughness: 1,
      flatShading: true,
    }),
    trees.length,
  );
  for (const object of [treeTrunks, treeCrowns, treeTops]) {
    object.castShadow = true;
    object.receiveShadow = true;
    scene!.add(object);
  }
  updateTrees(0);
}
function updateTrees(shift: number) {
  if (!treeCrowns || !treeTops || !treeTrunks) return;
  trees.forEach((tree, i) => {
    const x = tree.x + tree.weight * shift * 0.62,
      z = tree.z + tree.weight * shift * 0.74,
      y = tree.y - tree.weight * shift;
    matrix.scale.setScalar(tree.size);
    matrix.rotation.set(0, tree.rotation, -tree.weight * shift * 0.16);
    matrix.position.set(x, y + 0.14 * tree.size, z);
    matrix.updateMatrix();
    treeTrunks!.setMatrixAt(i, matrix.matrix);
    matrix.position.set(x, y + 0.43 * tree.size, z);
    matrix.updateMatrix();
    treeCrowns!.setMatrixAt(i, matrix.matrix);
    matrix.position.set(x, y + 0.64 * tree.size, z);
    matrix.updateMatrix();
    treeTops!.setMatrixAt(i, matrix.matrix);
  });
  treeCrowns.instanceMatrix.needsUpdate = true;
  treeTops.instanceMatrix.needsUpdate = true;
  treeTrunks.instanceMatrix.needsUpdate = true;
}
function makeSensors() {
  const metal = new THREE.MeshStandardMaterial({
    color: "#ecf1e8",
    metalness: 0.2,
    roughness: 0.58,
  });
  const pole = new THREE.MeshStandardMaterial({
    color: "#738477",
    metalness: 0.45,
    roughness: 0.45,
  });
  sensorObjects = nodes.map((node) => {
    const group = new THREE.Group(),
      y = terrainHeight(node.x, node.z);
    if (node.id === "gateway") {
      const cabinet = new THREE.Mesh(
        new THREE.BoxGeometry(0.34, 0.43, 0.25),
        metal,
      );
      cabinet.position.y = 0.22;
      cabinet.castShadow = true;
      group.add(cabinet);
      const solar = new THREE.Mesh(
        new THREE.BoxGeometry(0.57, 0.04, 0.33),
        new THREE.MeshStandardMaterial({
          color: "#657c7d",
          metalness: 0.3,
          roughness: 0.45,
        }),
      );
      solar.rotation.z = -0.25;
      solar.position.set(0.02, 0.59, 0);
      solar.castShadow = true;
      group.add(solar);
      const aerial = new THREE.Mesh(
        new THREE.CylinderGeometry(0.014, 0.014, 0.64, 5),
        pole,
      );
      aerial.position.set(-0.15, 0.5, 0.05);
      group.add(aerial);
    } else {
      const stake = new THREE.Mesh(
        new THREE.CylinderGeometry(0.025, 0.037, 0.52, 6),
        pole,
      );
      stake.position.y = 0.23;
      group.add(stake);
      const head = new THREE.Mesh(
        new THREE.BoxGeometry(0.18, 0.13, 0.16),
        metal,
      );
      head.position.y = 0.48;
      head.castShadow = true;
      group.add(head);
    }
    const halo = new THREE.Mesh(
      new THREE.RingGeometry(0.145, 0.2, 32),
      new THREE.MeshBasicMaterial({
        color: "#387f65",
        transparent: true,
        opacity: 0.78,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    halo.rotation.x = -Math.PI / 2;
    halo.position.y = 0.035;
    group.add(halo);
    group.position.set(node.x, y, node.z);
    scene!.add(group);
    return { node, group, y, weight: influence(node.x, node.z) };
  });
  for (let i = 0; i < 5; i++) {
    const points: THREE.Vector3[] = [];
    for (let j = 0; j < 11; j++) {
      const x = 0.1 + i * 0.52 + j * 0.085 + Math.sin(j * 2.8 + i) * 0.085,
        z = -0.7 + j * 0.155 + i * 0.075;
      points.push(new THREE.Vector3(x, terrainHeight(x, z) + 0.047, z));
    }
    const mat = new THREE.LineBasicMaterial({
      color: "#685046",
      transparent: true,
      opacity: 0,
      depthWrite: false,
    });
    crackMaterials.push(mat);
    addFollowingLine(points, mat);
  }
}
function makeRain() {
  const positions: number[] = [];
  for (let i = 0; i < 94; i++) {
    const x = Math.sin(i * 9.782) * 5.5,
      z = Math.cos(i * 6.543) * 4.0;
    rainSeeds.push({
      x,
      z,
      offset: (i * 0.61803) % 1,
      speed: 1.7 + (i % 5) * 0.22,
    });
    positions.push(x, 6, z);
  }
  const rainGeometry = new THREE.BufferGeometry();
  rainGeometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
  rain = new THREE.Points(
    rainGeometry,
    new THREE.PointsMaterial({
      color: "#93afb8",
      transparent: true,
      opacity: 0.35,
      size: 0.042,
      depthWrite: false,
    }),
  );
  scene!.add(rain);
}
function updateTerrain() {
  if (!geometry || !mesh) return;
  const shift = displacement();
  const updateShape = Math.abs(paintedDisplacement - shift) > 0.0005;
  const updateColor = Math.abs(paintedScore - visualScore) > 0.025;
  if (updateShape) {
    const p = geometry.getAttribute("position") as THREE.BufferAttribute;
    for (let i = 0; i < weights.length; i++) {
      const w = weights[i]!,
        k = i * 3;
      p.setXYZ(
        i,
        basePositions[k]! + w * shift * 0.62,
        basePositions[k + 1]! - w * shift,
        basePositions[k + 2]! + w * shift * 0.74,
      );
    }
    p.needsUpdate = true;
    geometry.computeVertexNormals();
    deformLines.forEach((line) => {
      const p = line.geometry.getAttribute("position") as THREE.BufferAttribute;
      for (let i = 0; i < line.weights.length; i++) {
        const w = line.weights[i]!,
          k = i * 3;
        p.setXYZ(
          i,
          line.base[k]! + w * shift * 0.62,
          line.base[k + 1]! - w * shift,
          line.base[k + 2]! + w * shift * 0.74,
        );
      }
      p.needsUpdate = true;
    });
    updateTrees(shift);
    sensorObjects.forEach((sensor) =>
      sensor.group.position.set(
        sensor.node.x + sensor.weight * shift * 0.62,
        sensor.y - sensor.weight * shift,
        sensor.node.z + sensor.weight * shift * 0.74,
      ),
    );
    paintedDisplacement = shift;
  }
  if (updateColor) {
    const tint = riskTint(visualScore),
      c = geometry.getAttribute("color") as THREE.BufferAttribute;
    const wetness = Math.max(0, (props.sensors.moisture ?? 0) - 42) / 170;
    for (let i = 0; i < weights.length; i++) {
      const k = i * 3,
        w = weights[i]!;
      const strength =
        mode.value === "heatmap"
          ? 0.22 + w * 0.71
          : mode.value === "sensors"
            ? w * 0.17
            : w * 0.68;
      const dim = 1 - wetness;
      c.setXYZ(
        i,
        baseColors[k]! * dim * (1 - strength) + tint.r * strength,
        baseColors[k + 1]! * dim * (1 - strength) + tint.g * strength,
        baseColors[k + 2]! * dim * (1 - strength) + tint.b * strength,
      );
    }
    c.needsUpdate = true;
    crackMaterials.forEach(
      (mat) => (mat.opacity = Math.max(0, (visualScore - 77) / 23) * 0.72),
    );
    sensorObjects.forEach((sensor) => {
      const halo = sensor.group.children[
        sensor.group.children.length - 1
      ] as THREE.Mesh;
      const mat = halo.material as THREE.MeshBasicMaterial;
      mat.color.copy(props.unknown || sensor.weight > 0.2 ? tint : green);
      mat.opacity = mode.value === "sensors" ? 1 : 0.78;
    });
    paintedScore = visualScore;
  }
  if (rain) {
    const count = Math.round(
      Math.min(94, Math.max(0, (props.sensors.rain ?? 0) - 9) * 1.45),
    );
    rain.visible = count > 0 && !reducedMotion;
    rain.geometry.setDrawRange(0, count);
    const p = rain.geometry.getAttribute("position") as THREE.BufferAttribute;
    rainSeeds.forEach((seed, i) => {
      const cycle = (weatherTime * seed.speed * 0.28 + seed.offset) % 1,
        y = 7.25 - cycle * 7;
      p.setXYZ(
        i,
        seed.x + cycle * 0.45,
        Math.max(terrainHeight(seed.x, seed.z) + 0.03, y),
        seed.z + cycle * 0.08,
      );
    });
    p.needsUpdate = true;
  }
}
function placeLabels() {
  if (!camera) return;
  sensorObjects.forEach(({ node, group }) => {
    const element = markerElements.get(node.id);
    if (!element) return;
    tempVector.copy(group.position);
    tempVector.y += node.id === "gateway" ? 0.92 : 0.77;
    tempVector.project(camera!);
    const x = ((tempVector.x + 1) * width) / 2,
      y = ((-tempVector.y + 1) * height) / 2;
    element.style.left = `${x}px`;
    element.style.top = `${y}px`;
    element.style.visibility =
      x > 12 && x < width - 12 && y > 36 && y < height - 40
        ? "visible"
        : "hidden";
  });
}
function renderFrame(now: number) {
  frame = undefined;
  if (
    disposed ||
    document.hidden ||
    !renderer ||
    !scene ||
    !camera ||
    fallback.value
  )
    return;
  const dt = Math.min(0.07, (now - lastFrame) / 1000 || 0.016);
  lastFrame = now;
  const ease = reducedMotion ? 1 : 1 - Math.exp(-dt * 11);
  visualScore += (props.score - visualScore) * ease;
  visualTime =
    props.running && !reducedMotion
      ? visualTime + (props.elapsed - visualTime) * ease
      : props.elapsed;
  const weatherAnimated =
    props.running && (props.sensors.rain ?? 0) > 9 && !reducedMotion;
  if (weatherAnimated)
    weatherTime = Math.min(
      props.elapsed + 0.98,
      weatherTime + dt * observedSpeed,
    );
  const controlsChanged = controls?.update();
  updateTerrain();
  placeLabels();
  renderer.render(scene, camera);
  if (
    controlsChanged ||
    weatherAnimated ||
    Math.abs(props.score - visualScore) > 0.04 ||
    (props.running && Math.abs(props.elapsed - visualTime) > 0.015)
  )
    requestRender();
}
function resize() {
  if (!surface.value || !camera || !renderer) return;
  width = surface.value.clientWidth;
  height = surface.value.clientHeight;
  const aspect = width / Math.max(1, height),
    view = Math.max(6.0, 9.8 / aspect);
  camera.left = -view * aspect;
  camera.right = view * aspect;
  camera.top = view;
  camera.bottom = -view;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
  requestRender();
}
function resetCamera() {
  if (!camera || !controls) return;
  overhead.value = false;
  camera.position.set(12.8, 11.4, 15.2);
  controls.target.set(0, 0.9, 0);
  camera.zoom = 1;
  camera.updateProjectionMatrix();
  controls.update();
  requestRender();
}
function alternateView() {
  if (!camera || !controls) return;
  overhead.value = !overhead.value;
  camera.position.set(
    overhead.value ? -0.05 : 12.8,
    overhead.value ? 22 : 11.4,
    overhead.value ? 4.2 : 15.2,
  );
  controls.target.set(0, 0.9, 0);
  controls.update();
  requestRender();
}
function zoom(direction: number) {
  if (camera) {
    camera.zoom = THREE.MathUtils.clamp(
      camera.zoom * (direction > 0 ? 1.13 : 0.885),
      0.65,
      2.5,
    );
    camera.updateProjectionMatrix();
    requestRender();
  }
}
function visibilityChanged() {
  if (document.hidden && frame !== undefined) {
    cancelAnimationFrame(frame);
    frame = undefined;
  } else {
    lastFrame = performance.now();
    requestRender();
  }
}
function motionChanged(event: MediaQueryListEvent) {
  reducedMotion = event.matches;
  controls && (controls.enableDamping = !reducedMotion);
  requestRender();
}
function contextLost(event: Event) {
  event.preventDefault();
  fallback.value = true;
  if (frame !== undefined) cancelAnimationFrame(frame);
  frame = undefined;
}
function contextRestored() {
  fallback.value = false;
  paintedScore = -1;
  paintedDisplacement = -1;
  resize();
  requestRender();
}

onMounted(() => {
  try {
    mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    reducedMotion = mediaQuery.matches;
    mediaQuery.addEventListener("change", motionChanged);
    scene = new THREE.Scene();
    renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "low-power",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setClearColor(0xffffff, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.setAttribute(
      "aria-label",
      "可旋转的模拟山区边坡三维沙盘",
    );
    renderer.domElement.setAttribute("role", "img");
    surface.value!.prepend(renderer.domElement);
    renderer.domElement.addEventListener("webglcontextlost", contextLost);
    renderer.domElement.addEventListener(
      "webglcontextrestored",
      contextRestored,
    );
    camera = new THREE.OrthographicCamera(-10, 10, 7, -7, 0.1, 100);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = !reducedMotion;
    controls.dampingFactor = 0.085;
    controls.minZoom = 0.65;
    controls.maxZoom = 2.5;
    controls.enablePan = false;
    controls.minPolarAngle = 0.12;
    controls.maxPolarAngle = Math.PI / 2.22;
    controls.rotateSpeed = 0.55;
    controls.zoomSpeed = 0.72;
    controls.addEventListener("change", requestRender);
    scene.add(new THREE.HemisphereLight("#fffef3", "#b9c2ad", 2.25));
    const sunlight = new THREE.DirectionalLight("#fff7e6", 3.0);
    sunlight.position.set(-6, 12, 8);
    sunlight.castShadow = true;
    sunlight.shadow.mapSize.set(1024, 1024);
    sunlight.shadow.camera.left = -10;
    sunlight.shadow.camera.right = 10;
    sunlight.shadow.camera.top = 10;
    sunlight.shadow.camera.bottom = -10;
    sunlight.shadow.bias = -0.0004;
    sunlight.shadow.normalBias = 0.035;
    sunlight.shadow.radius = 4;
    scene.add(sunlight);
    const fill = new THREE.DirectionalLight("#ecf2f7", 0.6);
    fill.position.set(7, 6, -8);
    scene.add(fill);
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(50, 50),
      new THREE.ShadowMaterial({ color: "#5d6d55", opacity: 0.16 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -1.215;
    ground.receiveShadow = true;
    scene.add(ground);
    makeSurface();
    makeContours();
    makeRoad();
    makeTrees();
    makeSensors();
    makeRain();
    resetCamera();
    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(surface.value!);
    resize();
    document.addEventListener("visibilitychange", visibilityChanged);
  } catch {
    fallback.value = true;
    releaseGraphics();
  }
});
watch(
  () => [
    props.score,
    props.unknown,
    props.sensors.moisture,
    props.sensors.rain,
    props.elapsed,
    props.running,
  ],
  () => {
    paintedScore = -1;
    requestRender();
  },
);
watch(
  () => props.elapsed,
  (value, previous) => {
    const now = performance.now(),
      interval = (now - sampleStamp) / 1000;
    if (sampleStamp && value > previous && interval > 0.08 && interval < 3)
      observedSpeed = THREE.MathUtils.clamp(
        (value - previous) / interval,
        0.5,
        4,
      );
    sampleStamp = now;
    weatherTime = value;
    requestRender();
  },
);
watch(mode, () => {
  paintedScore = -1;
  requestRender();
});
watch(
  () => props.resetKey,
  () => {
    selected.value = null;
    mode.value = "standard";
    visualScore = props.score;
    visualTime = 0;
    weatherTime = 0;
    observedSpeed = 1;
    sampleStamp = 0;
    paintedScore = -1;
    paintedDisplacement = -1;
    resetCamera();
  },
);
function releaseGraphics() {
  if (frame !== undefined) cancelAnimationFrame(frame);
  frame = undefined;
  resizeObserver?.disconnect();
  controls?.removeEventListener("change", requestRender);
  controls?.dispose();
  document.removeEventListener("visibilitychange", visibilityChanged);
  mediaQuery?.removeEventListener("change", motionChanged);
  renderer?.domElement.removeEventListener("webglcontextlost", contextLost);
  renderer?.domElement.removeEventListener(
    "webglcontextrestored",
    contextRestored,
  );
  const geometries = new Set<THREE.BufferGeometry>(),
    materials = new Set<THREE.Material>();
  scene?.traverse((object) => {
    if (
      object instanceof THREE.Mesh ||
      object instanceof THREE.Line ||
      object instanceof THREE.Points
    ) {
      geometries.add(object.geometry);
      (Array.isArray(object.material)
        ? object.material
        : [object.material]
      ).forEach((m) => materials.add(m));
    }
  });
  geometries.forEach((g) => g.dispose());
  materials.forEach((m) => m.dispose());
  renderer?.dispose();
  renderer?.domElement.remove();
}
onBeforeUnmount(() => {
  disposed = true;
  releaseGraphics();
});
</script>

<template>
  <div
    class="terrain-scene"
    :class="{ 'sensor-mode': mode === 'sensors', 'has-selection': selected, 'risk-unknown': unknown }"
    :style="{ '--terrain-risk': riskColor }"
  >
    <div class="terrain-modes" role="group" aria-label="地形展示模式">
      <button
        :class="{ active: mode === 'standard' }"
        :aria-pressed="mode === 'standard'"
        @click="mode = 'standard'"
      >
        标准地形
      </button>
      <button
        :class="{ active: mode === 'heatmap' }"
        :aria-pressed="mode === 'heatmap'"
        @click="mode = 'heatmap'"
      >
        风险热力
      </button>
      <button
        :class="{ active: mode === 'sensors' }"
        :aria-pressed="mode === 'sensors'"
        @click="mode = 'sensors'"
      >
        传感器
      </button>
    </div>
    <div class="terrain-coordinate">
      <span class="coordinate-dot"></span> {{ deviceLabel || "NODE-01" }} 监测区
      <span>{{ nodes.length }} 个节点</span>
    </div>
    <div ref="surface" class="terrain-canvas">
      <svg
        v-if="fallback"
        class="terrain-fallback"
        viewBox="0 0 700 390"
        role="img"
        aria-label="模拟山区地形静态视图"
      >
        <defs>
          <linearGradient id="land" x2=".4" y2="1">
            <stop stop-color="#aec09b" />
            <stop offset="1" stop-color="#7c9977" />
          </linearGradient>
          <linearGradient id="strata" x2="0" y2="1">
            <stop stop-color="#d4cbb5" />
            <stop offset="1" stop-color="#aaa28e" />
          </linearGradient>
        </defs>
        <ellipse
          cx="350"
          cy="318"
          rx="229"
          ry="35"
          fill="#8b9785"
          opacity=".13"
        />
        <path d="M112 254 349 342 604 248 366 174Z" fill="url(#strata)" />
        <path
          d="M112 223 349 311 604 217 366 142 280 102 246 92 215 133 177 148Z"
          fill="url(#land)"
        />
        <path
          d="m112 223 237 88 255-94v31l-255 94-237-88Z"
          fill="url(#strata)"
        />
        <path
          d="m112 238 237 88 255-94M112 246l237 88 255-94"
          fill="none"
          stroke="#938d7b"
          opacity=".4"
        />
        <path
          d="m179 167 47-33 39-17 70 54 126 41M159 186l72-37 38-17 62 54 170 46M151 202l93-40 46 3 113 70 124 2"
          stroke="#e0e4cf"
          stroke-width="1"
          fill="none"
        />
        <path
          d="m282 216 59-31 90 20 39 43-101 37-82-24Z"
          :fill="riskColor"
          opacity=".65"
        />
        <path
          d="m165 248 62 22 41-4 45 13 78-1 97-24 62-9"
          stroke="#e7dfca"
          stroke-width="7"
          fill="none"
        />
        <g fill="#587456">
          <path
            v-for="i in 18"
            :key="i"
            :d="`M${160 + ((i * 37) % 370)} ${180 + ((i * 19) % 65)} l-7 18 h14Z`"
          />
        </g>
      </svg>
      <div
        class="sensor-labels"
        :class="{ 'fallback-labels': fallback }"
        aria-label="监测节点"
      >
        <button
          v-for="(node, i) in nodes"
          :key="node.id"
          :ref="(el) => registerMarker(node.id, el)"
          class="sensor-marker"
          :class="{
            selected: selected === node.id,
            gateway: node.id === 'gateway',
          }"
          :style="
            fallback
              ? {
                  left: `${27 + ((i * 13) % 52)}%`,
                  top: `${37 + ((i * 11) % 37)}%`,
                }
              : {}
          "
          :aria-label="`查看 ${node.name} ${node.detail}`"
          :aria-pressed="selected === node.id"
          @click.stop="selectNode(node.id)"
        >
          <span
            class="sensor-dot"
            :class="{
              'gateway-offline':
                node.id === 'gateway' && gatewayOnline === false,
            }"
          ></span
          ><span class="sensor-name">{{ node.name }}</span
          ><span class="sensor-desc">{{ node.detail }}</span>
        </button>
      </div>
    </div>
    <div class="terrain-north" aria-hidden="true">
      <span>N</span
      ><svg width="30" height="35" viewBox="0 0 30 35">
        <path d="m15 3-8 25 8-6 8 6Z" fill="#607569" />
        <path d="m15 3 0 19 8 6Z" fill="#bdc9be" />
      </svg>
    </div>
    <div class="terrain-camera" role="group" aria-label="相机控制">
      <button
        aria-label="放大地形"
        title="放大"
        :disabled="fallback"
        @click="zoom(1)"
      >
        <svg viewBox="0 0 20 20"><path d="M10 4v12M4 10h12" /></svg>
      </button>
      <button
        aria-label="缩小地形"
        title="缩小"
        :disabled="fallback"
        @click="zoom(-1)"
      >
        <svg viewBox="0 0 20 20"><path d="M4 10h12" /></svg>
      </button>
      <span></span>
      <button
        aria-label="切换俯视视角"
        title="切换视角"
        :aria-pressed="overhead"
        :disabled="fallback"
        @click="alternateView"
      >
        <svg viewBox="0 0 20 20">
          <path d="m10 3 7 4-7 4-7-4ZM3 10l7 4 7-4M3 13l7 4 7-4" />
        </svg>
      </button>
      <button
        aria-label="复位相机"
        title="复位相机"
        :disabled="fallback"
        @click="resetCamera"
      >
        <svg viewBox="0 0 20 20"><path d="M4 8a6 6 0 1 1 1 7M4 3v5h5" /></svg>
      </button>
    </div>
    <Transition name="node-detail">
      <div
        v-if="activeNode"
        class="terrain-detail"
        role="region"
        :aria-label="`${activeNode.name} 节点详情`"
      >
        <div class="detail-heading">
          <div>
            <span
              class="detail-online"
              :class="{
                'gateway-offline':
                  activeNode.id === 'gateway' && gatewayOnline === false,
              }"
            ></span
            ><strong>{{ activeNode.name }}</strong
            ><span>{{
              platform ? "通道示意" : activeNode.id === "gateway" ? "模拟网关" : "本地监测"
            }}</span>
          </div>
          <button aria-label="关闭节点详情" @click="selected = null">×</button>
        </div>
        <div class="detail-measurement">
          <span>{{ activeNode.detail }}</span
          ><strong>{{ detailValue }}</strong>
        </div>
        <div class="detail-meta">
          <span>{{ platform ? "设备型号以接入配置为准" : activeNode.device }}</span
          ><span>{{ platform ? unknown ? "无有效风险分数" : "后端数据" : running ? "刚刚更新" : "仿真已暂停" }}</span>
        </div>
      </div>
    </Transition>
    <div class="terrain-footer">
      <div class="terrain-scale">
        <span></span> 20 m <small>示意比例</small>
      </div>
      <div class="terrain-hints">
        <svg viewBox="0 0 16 16">
          <path
            d="M5 7V3a1 1 0 0 1 2 0v3-4a1 1 0 0 1 2 0v4-3a1 1 0 0 1 2 0v4-2a1 1 0 0 1 2 0v5c0 3-2 5-4 5H7L3 9a1 1 0 0 1 1-1l2 2"
          />
        </svg>
        拖拽旋转 <span>·</span> 滚轮缩放
      </div>
      <span class="terrain-demo"
        >{{ fallback ? "静态兼容视图" : "DEMO" }} <span>模拟地形</span></span
      >
    </div>
    <div v-if="mode === 'heatmap' && !unknown" class="terrain-legend">
      <span>低风险</span><i></i><span>高风险</span>
    </div>
  </div>
</template>

<style scoped>
.risk-unknown .sensor-dot, .risk-unknown .detail-online, .risk-unknown .coordinate-dot { background: #a6aea8; box-shadow: none; }
.terrain-scene {
  position: relative;
  height: 100%;
  min-height: 320px;
  overflow: hidden;
  isolation: isolate;
  background: radial-gradient(ellipse at 46% 47%, #f1f4ed 0%, #f7f9f5 70%);
}
.terrain-canvas {
  position: absolute;
  inset: 0;
}
.terrain-canvas :deep(canvas) {
  display: block;
  width: 100%;
  height: 100%;
  cursor: grab;
  touch-action: none;
}
.terrain-canvas :deep(canvas:active) {
  cursor: grabbing;
}
.terrain-modes {
  position: absolute;
  z-index: 3;
  left: 23px;
  top: 18px;
  display: flex;
  align-items: center;
  padding: 3px;
  gap: 2px;
  border: 1px solid #dfe6dd;
  border-radius: 9px;
  background: #eaf0e8c2;
}
.terrain-modes button {
  border: 0;
  border-radius: 6px;
  padding: 7px 12px;
  background: transparent;
  color: #788575;
  font: inherit;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition:
    color 0.18s,
    background 0.18s,
    box-shadow 0.18s;
}
.terrain-modes button.active {
  color: #355846;
  background: #fff;
  box-shadow: 0 1px 4px #3e533916;
}
.terrain-modes button:hover {
  color: #2d5640;
}
.terrain-coordinate {
  position: absolute;
  right: 23px;
  top: 30px;
  z-index: 2;
  font-size: 10px;
  color: #627365;
  display: flex;
  align-items: center;
  gap: 7px;
}
.terrain-coordinate > span:last-child {
  font-size: 9px;
  color: #95a291;
  margin-left: 8px;
}
.coordinate-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #589370;
}
.terrain-north {
  position: absolute;
  right: 28px;
  top: 68px;
  z-index: 2;
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 2px;
  color: #667b6a;
  font-size: 9px;
  font-weight: 600;
}
.terrain-camera {
  position: absolute;
  right: 19px;
  bottom: 67px;
  z-index: 3;
  display: flex;
  flex-direction: column;
  padding: 3px;
  border: 1px solid #dde5db;
  border-radius: 10px;
  background: #fffffff0;
  box-shadow: 0 3px 13px #54654b08;
}
.terrain-camera button {
  display: grid;
  place-items: center;
  width: 31px;
  height: 30px;
  background: transparent;
  color: #748371;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}
.terrain-camera button:hover,
.terrain-camera button[aria-pressed="true"] {
  color: #3d6d53;
  background: #edf2e9;
}
.terrain-camera button:disabled {
  opacity: 0.35;
  cursor: default;
}
.terrain-camera svg {
  height: 17px;
  width: 17px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.35;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.terrain-camera > span {
  display: block;
  height: 1px;
  background: #e6ebe3;
  margin: 3px 6px;
}
.sensor-labels {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 2;
}
.sensor-marker {
  position: absolute;
  z-index: 1;
  display: flex;
  gap: 5px;
  align-items: center;
  height: 22px;
  padding: 3px 7px 3px 5px;
  border: 1px solid #dce5d9;
  border-radius: 5px;
  color: #46604c;
  background: #fffffff0;
  box-shadow: 0 2px 5px #3c4e2f0e;
  font: inherit;
  font-size: 8px;
  font-weight: 600;
  transform: translate(-50%, -100%);
  pointer-events: auto;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background 0.2s,
    box-shadow 0.2s;
}
.sensor-marker::after {
  content: "";
  width: 1px;
  height: 8px;
  position: absolute;
  top: 100%;
  left: 50%;
  background: #859980;
}
.sensor-marker:hover,
.sensor-marker.selected {
  z-index: 4;
  background: #fff;
  border-color: #749379;
  box-shadow: 0 2px 9px #3d593424;
}
.sensor-dot {
  height: 4px;
  width: 4px;
  flex-shrink: 0;
  border-radius: 50%;
  background: #589a77;
}
.sensor-marker:not(.gateway) .sensor-dot {
  background: var(--terrain-risk);
}
.sensor-dot.gateway-offline,
.detail-online.gateway-offline {
  background: #bd6251;
}
.sensor-desc {
  display: none;
  border-left: 1px solid #dfe6dc;
  padding-left: 5px;
  font-size: 8px;
  color: #7b8b76;
  font-weight: 400;
}
.sensor-mode .sensor-desc {
  display: inline;
}
.sensor-mode .sensor-marker {
  height: 25px;
}
.terrain-detail {
  position: absolute;
  z-index: 5;
  width: 230px;
  left: 22px;
  bottom: 62px;
  padding: 13px 14px;
  border: 1px solid #dce5d8;
  border-radius: 11px;
  background: #fffffff5;
  box-shadow: 0 8px 32px #405d3514;
}
.detail-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-heading > div {
  display: flex;
  align-items: center;
  gap: 6px;
}
.detail-heading strong {
  font-size: 11px;
  font-weight: 650;
  color: #354f3c;
}
.detail-heading > div > span:last-child {
  color: #92a08e;
  font-size: 9px;
  margin-left: 3px;
}
.detail-heading button {
  border: 0;
  background: transparent;
  color: #82917b;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}
.detail-online {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #489275;
}
.detail-measurement {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-top: 17px;
}
.detail-measurement > span {
  font-size: 10px;
  color: #7d8a79;
}
.detail-measurement > strong {
  font-size: 21px;
  font-weight: 550;
  letter-spacing: -0.7px;
  color: #314d39;
  font-variant-numeric: tabular-nums;
}
.detail-meta {
  display: flex;
  justify-content: space-between;
  font-size: 8px;
  color: #96a08f;
  padding-top: 13px;
  margin-top: 11px;
  border-top: 1px solid #ebefe8;
  gap: 10px;
}
.terrain-footer {
  position: absolute;
  left: 23px;
  right: 23px;
  bottom: 21px;
  z-index: 2;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  color: #7f8e79;
  font-size: 9px;
}
.terrain-scale {
  display: flex;
  align-items: center;
  gap: 7px;
}
.terrain-scale > span {
  display: block;
  width: 36px;
  height: 5px;
  border: solid #8c9a82;
  border-width: 0 1px 1px;
}
.terrain-scale small {
  font-size: 8px;
  color: #a4af9e;
  margin-left: 1px;
}
.terrain-hints {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #95a18c;
}
.terrain-hints svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.terrain-hints > span {
  margin: 0 1px;
}
.terrain-demo {
  font-size: 8px;
  font-weight: 550;
  letter-spacing: 0.7px;
  color: #778b75;
  white-space: nowrap;
}
.terrain-demo > span {
  font-weight: 400;
  letter-spacing: 0;
  margin-left: 5px;
  color: #97a28f;
}
.terrain-legend {
  position: absolute;
  left: 23px;
  bottom: 51px;
  display: flex;
  align-items: center;
  gap: 7px;
  color: #85937d;
  font-size: 8px;
}
.terrain-legend > i {
  width: 77px;
  height: 4px;
  border-radius: 2px;
  background: linear-gradient(
    90deg,
    #81a783,
    #d5b55e 40%,
    #d68b57 70%,
    #ca6760
  );
}
.terrain-fallback {
  width: 100%;
  height: 100%;
  display: block;
}
button:focus-visible {
  outline: 2px solid #5b9274;
  outline-offset: 3px;
}
.node-detail-enter-active,
.node-detail-leave-active {
  transition:
    opacity 0.18s,
    transform 0.18s;
}
.node-detail-enter-from,
.node-detail-leave-to {
  opacity: 0;
  transform: translateY(5px);
}
@media (max-width: 720px) {
  .terrain-coordinate {
    display: none;
  }
  .terrain-hints {
    display: none;
  }
  .terrain-modes {
    left: 15px;
    top: 14px;
  }
  .terrain-modes button {
    padding: 7px 9px;
  }
  .terrain-footer {
    left: 17px;
    right: 17px;
  }
  .terrain-north {
    right: 20px;
    top: 22px;
  }
  .terrain-scale small {
    display: none;
  }
  .terrain-detail {
    left: 15px;
    width: 218px;
  }
}
@media (prefers-reduced-motion: reduce) {
  * {
    transition: none !important;
  }
}
</style>
