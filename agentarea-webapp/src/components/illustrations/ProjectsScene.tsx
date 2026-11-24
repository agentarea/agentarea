"use client";

import { Bot, Server, Sparkles, type LucideIcon } from "lucide-react";
import { Bar, Glyph, Lifted, Loop, Scene, useScene } from "./kit";

const D = 5;

const ITEMS: { icon: LucideIcon; x: number; tint: string; at: number }[] = [
  { icon: Bot, x: 222, tint: "text-primary", at: 0.05 },
  { icon: Sparkles, x: 268, tint: "text-amber-500", at: 0.25 },
  { icon: Server, x: 314, tint: "text-emerald-600", at: 0.45 },
];

function Item({ icon, x, tint, at }: (typeof ITEMS)[number]) {
  const { moving } = useScene();
  const rest = 84;
  return (
    <g opacity={moving ? 0 : 1}>
      <Loop
        attr="opacity"
        values={[0, 0, 1, 1, 0, 0]}
        times={[0, at, at + 0.03, 0.93, 0.95, 1]}
        dur={D}
      />
      <g transform={moving ? undefined : `translate(0 ${rest})`}>
        <Lifted>
          <rect
            x={x}
            y="0"
            width="40"
            height="52"
            rx="8"
            className="fill-background stroke-border"
          />
        </Lifted>
        <Glyph icon={icon} x={x + 20} y={16} size={14} className={tint} />
        <Bar x={x + 8} y={30} w={24} h={4} />
        <Bar x={x + 8} y={38} w={16} h={4} tone="faint" />
        {moving && (
          <animateTransform
            attributeName="transform"
            type="translate"
            values={`0 -70;0 -70;0 ${rest};0 ${rest};0 -70`}
            keyTimes={`0;${at};${at + 0.18};0.96;1`}
            calcMode="spline"
            keySplines="0 0 1 1;0.3 0 0.2 1;0 0 1 1;0 0 1 1"
            dur={`${D}s`}
            repeatCount="indefinite"
          />
        )}
      </g>
    </g>
  );
}

/** Agents, skills and connections dropping into one project folder. */
export default function ProjectsScene() {
  return (
    <Scene>
      <Lifted>
        <path
          d="M196 98 Q196 88 206 88 H246 Q252 88 256 94 L262 102 H374 Q384 102 384 112 V196 H196 Z"
          className="fill-primary"
          opacity="0.35"
        />
      </Lifted>
      {ITEMS.map((item) => (
        <Item key={item.x} {...item} />
      ))}
      <path
        d="M190 130 Q190 122 198 122 H382 Q390 122 390 130 L384 194 Q383 202 375 202 H205 Q197 202 196 194 Z"
        className="fill-primary"
      />
      <rect
        x="214"
        y="140"
        width="56"
        height="5"
        rx="2.5"
        fill="white"
        opacity="0.8"
      />
      <rect
        x="214"
        y="151"
        width="36"
        height="5"
        rx="2.5"
        fill="white"
        opacity="0.5"
      />
    </Scene>
  );
}
