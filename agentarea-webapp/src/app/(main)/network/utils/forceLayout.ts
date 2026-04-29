interface SimNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  anchorX: number;
  anchorY?: number;
  fixed?: boolean;
}

interface SimLink {
  source: string;
  target: string;
}

interface SimOptions {
  iterations?: number;
  repulsion?: number;
  linkLength?: number;
  linkStrength?: number;
  xStrength?: number;
  yStrength?: number;
  collideRadius?: number;
  damping?: number;
  centerY?: number;
}

export function runForceLayout(
  nodes: SimNode[],
  links: SimLink[],
  opts: SimOptions = {}
) {
  const iterations = opts.iterations ?? 450;
  const REPULSION = opts.repulsion ?? 36000;
  const LINK_LEN = opts.linkLength ?? 260;
  const LINK_STR = opts.linkStrength ?? 0.04;
  const X_STR = opts.xStrength ?? 0.22;
  const Y_STR = opts.yStrength ?? 0.012;
  const COLLIDE = opts.collideRadius ?? 140;
  const DAMP = opts.damping ?? 0.86;
  const CY = opts.centerY ?? 0;
  const MAX_V = 32;

  const byId: Record<string, SimNode> = {};
  for (const n of nodes) byId[n.id] = n;

  for (let i = 0; i < iterations; i++) {
    for (let a = 0; a < nodes.length; a++) {
      for (let b = a + 1; b < nodes.length; b++) {
        const A = nodes[a];
        const B = nodes[b];
        const dx = B.x - A.x;
        const dy = B.y - A.y;
        const distSq = dx * dx + dy * dy + 1;
        const dist = Math.sqrt(distSq);
        const force = REPULSION / distSq;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        if (!A.fixed) {
          A.vx -= fx;
          A.vy -= fy;
        }
        if (!B.fixed) {
          B.vx += fx;
          B.vy += fy;
        }
      }
    }

    for (const l of links) {
      const A = byId[l.source];
      const B = byId[l.target];
      if (!A || !B) continue;
      const dx = B.x - A.x;
      const dy = B.y - A.y;
      const dist = Math.sqrt(dx * dx + dy * dy) + 0.001;
      const offset = dist - LINK_LEN;
      const force = offset * LINK_STR;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      if (!A.fixed) {
        A.vx += fx;
        A.vy += fy;
      }
      if (!B.fixed) {
        B.vx -= fx;
        B.vy -= fy;
      }
    }

    for (const n of nodes) {
      if (n.fixed) continue;
      n.vx += (n.anchorX - n.x) * X_STR;
      const targetY = n.anchorY ?? CY;
      // Stronger Y pull when an explicit cluster anchor is set so bands hold.
      const yStr = n.anchorY !== undefined ? Math.max(Y_STR, 0.05) : Y_STR;
      n.vy += (targetY - n.y) * yStr;
    }

    for (let a = 0; a < nodes.length; a++) {
      for (let b = a + 1; b < nodes.length; b++) {
        const A = nodes[a];
        const B = nodes[b];
        const dx = B.x - A.x;
        const dy = B.y - A.y;
        const dist = Math.sqrt(dx * dx + dy * dy) + 0.001;
        if (dist < COLLIDE) {
          const overlap = (COLLIDE - dist) / 2;
          const ox = (dx / dist) * overlap;
          const oy = (dy / dist) * overlap;
          if (!A.fixed) {
            A.x -= ox;
            A.y -= oy;
          }
          if (!B.fixed) {
            B.x += ox;
            B.y += oy;
          }
        }
      }
    }

    for (const n of nodes) {
      if (n.fixed) continue;
      n.vx = Math.max(-MAX_V, Math.min(MAX_V, n.vx)) * DAMP;
      n.vy = Math.max(-MAX_V, Math.min(MAX_V, n.vy)) * DAMP;
      n.x += n.vx;
      n.y += n.vy;
    }
  }
}
