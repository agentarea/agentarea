"use client";

import { Bot, Sparkles, SquareTerminal } from "lucide-react";
import { Appear, Bar, Card, Glyph, Lifted, Parcel, Route, Scene } from "./kit";

const D = 5;

const USERS = [
  {
    y: 46,
    icon: Bot,
    d: "M196 100 C 280 100, 320 70, 398 70",
    from: 0.06,
    to: 0.38,
  },
  {
    y: 128,
    icon: SquareTerminal,
    d: "M196 116 C 280 116, 320 152, 398 152",
    from: 0.52,
    to: 0.84,
  },
];

/** A skill written once is handed to every agent and harness that needs it. */
export default function SkillsScene() {
  return (
    <Scene>
      <Lifted>
        <Card x={74} y={44} w={120} h={140} rotate={-10} opacity={0.7} />
        <Card x={74} y={44} w={120} h={140} rotate={-4} />
        <Card x={74} y={44} w={120} h={140} />
      </Lifted>
      <rect
        x="86"
        y="56"
        width="26"
        height="26"
        rx="8"
        className="fill-amber-500"
        opacity="0.15"
      />
      <Glyph
        icon={Sparkles}
        x={99}
        y={69}
        size={14}
        className="text-amber-500"
      />
      <Bar x={120} y={60} w={58} h={6} tone="strong" />
      <Bar x={120} y={72} w={38} />
      {[94, 106, 118, 130, 142, 154, 166].map((y, i) => (
        <Bar
          key={y}
          x={i % 3 === 0 ? 86 : 94}
          y={y}
          w={[88, 70, 80, 92, 64, 76, 52][i]}
          h={4}
          tone={i % 3 === 0 ? "soft" : "faint"}
        />
      ))}

      {USERS.map((u) => (
        <Route
          key={u.y}
          d={u.d}
          end={[398, u.y + 24]}
          dur={D}
          from={u.from}
          to={u.to}
        >
          <Parcel icon={Sparkles} className="fill-amber-500" />
        </Route>
      ))}
      {USERS.map((u) => (
        <g key={u.y}>
          <Lifted>
            <Card x={398} y={u.y} w={150} h={48} />
          </Lifted>
          <circle
            cx="420"
            cy={u.y + 24}
            r="12"
            className="fill-primary"
            opacity="0.14"
          />
          <Glyph
            icon={u.icon}
            x={420}
            y={u.y + 24}
            size={14}
            className="text-primary"
          />
          <Bar x={440} y={u.y + 16} w={54} tone="strong" />
          <Bar x={440} y={u.y + 27} w={34} />
          <Appear at={u.to} dur={D}>
            <rect
              x="504"
              y={u.y + 15}
              width="34"
              height="18"
              rx="9"
              className="fill-amber-500"
              opacity="0.15"
            />
            <Glyph
              icon={Sparkles}
              x={521}
              y={u.y + 24}
              size={11}
              className="text-amber-500"
            />
          </Appear>
        </g>
      ))}
    </Scene>
  );
}
