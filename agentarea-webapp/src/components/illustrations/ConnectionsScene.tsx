"use client";

import { Bot, Calendar, Database, Mail, ShieldCheck } from "lucide-react";
import {
  Bar,
  Card,
  Glyph,
  Hub,
  Lifted,
  Parcel,
  Route,
  Scene,
  Tile,
} from "./kit";

const D = 5.4;

const SERVICES = [
  { y: 50, icon: Database, tint: "text-primary" },
  { y: 110, icon: Mail, tint: "text-red-500" },
  { y: 170, icon: Calendar, tint: "text-emerald-600" },
];

/** An agent's tool calls pass through AgentArea, which lets each reach only the systems it may use. */
export default function ConnectionsScene() {
  return (
    <Scene>
      {SERVICES.map((s, k) => (
        <Route
          key={s.y}
          d={`M150 110 C 210 110, 250 108, 290 108 S 420 ${s.y}, 466 ${s.y}`}
          end={[466, s.y]}
          dur={D}
          begin={(k * D) / 3}
          from={0.04}
          to={0.28}
        >
          <Parcel />
        </Route>
      ))}

      <Lifted>
        <Card x={36} y={80} w={114} h={60} />
      </Lifted>
      <circle cx="60" cy="110" r="13" className="fill-primary" opacity="0.14" />
      <Glyph icon={Bot} x={60} y={110} size={15} className="text-primary" />
      <Bar x={80} y={102} w={52} tone="strong" />
      <Bar x={80} y={113} w={34} />

      <Hub x={290} y={104} />
      <circle
        cx="314"
        cy="80"
        r="10"
        className="fill-background stroke-border"
      />
      <Glyph
        icon={ShieldCheck}
        x={314}
        y={80}
        size={12}
        className="text-emerald-600"
      />

      {SERVICES.map((s) => (
        <Tile
          key={s.y}
          x={490}
          y={s.y}
          size={46}
          icon={s.icon}
          iconClassName={s.tint}
        />
      ))}
    </Scene>
  );
}
