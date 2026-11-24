"use client";

import {
  Bot,
  Cpu,
  FileText,
  Server,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import {
  Appear,
  Bar,
  Card,
  Glyph,
  Lifted,
  Parcel,
  Route,
  Scene,
  Tile,
} from "./kit";

const D = 6;

const PARTS: {
  icon: LucideIcon;
  tile: [number, number];
  d: string;
  tint: string;
}[] = [
  {
    icon: FileText,
    tile: [92, 62],
    d: "M116 62 C 170 62, 180 104, 230 104",
    tint: "text-muted-foreground",
  },
  {
    icon: Cpu,
    tile: [92, 158],
    d: "M116 158 C 170 158, 180 122, 230 122",
    tint: "text-primary",
  },
  {
    icon: Sparkles,
    tile: [488, 62],
    d: "M464 62 C 410 62, 400 140, 350 140",
    tint: "text-amber-500",
  },
  {
    icon: Server,
    tile: [488, 158],
    d: "M464 158 C 410 158, 400 158, 350 158",
    tint: "text-emerald-600",
  },
];

/** An agent put together from instructions, a model, skills and connections, slotting in one by one. */
export default function AgentsScene() {
  return (
    <Scene>
      {PARTS.map((part, k) => (
        <Route
          key={k}
          d={part.d}
          dur={D}
          from={0.04 + k * 0.17}
          to={0.18 + k * 0.17}
          ring={false}
        >
          <Parcel icon={part.icon} />
        </Route>
      ))}
      {PARTS.map((part, k) => (
        <Tile
          key={k}
          x={part.tile[0]}
          y={part.tile[1]}
          size={46}
          icon={part.icon}
          iconClassName={part.tint}
        />
      ))}

      <Lifted>
        <Card x={210} y={40} w={160} h={140} rx={14} />
      </Lifted>
      <circle cx="238" cy="68" r="15" className="fill-primary" opacity="0.14" />
      <Glyph icon={Bot} x={238} y={68} size={17} className="text-primary" />
      <Bar x={260} y={61} w={74} h={6} tone="strong" />
      <Bar x={260} y={72} w={50} />
      {PARTS.map((part, k) => {
        const y = 98 + k * 18;
        return (
          <g key={k}>
            <rect
              x="224"
              y={y}
              width="132"
              height="13"
              rx="6.5"
              className="fill-none stroke-border"
              strokeDasharray="3 3"
            />
            <Appear at={0.18 + k * 0.17} dur={D}>
              <rect
                x="224"
                y={y}
                width="132"
                height="13"
                rx="6.5"
                className="fill-primary"
                opacity="0.1"
              />
              <Glyph
                icon={part.icon}
                x={234}
                y={y + 6.5}
                size={9}
                className={part.tint}
              />
              <Bar x={244} y={y + 4.5} w={[60, 48, 72, 54][k]} h={4} />
            </Appear>
          </g>
        );
      })}
    </Scene>
  );
}
