"use client";

import { Bot, MessageCircle } from "lucide-react";
import {
  Appear,
  Bar,
  Card,
  Glyph,
  Hub,
  Lifted,
  Parcel,
  Route,
  Scene,
  Typing,
} from "./kit";

const D = 5;

/** A message in a chat travels through AgentArea to an agent, and its reply lands back in the chat. */
export default function ChannelsScene() {
  return (
    <Scene>
      <Lifted>
        <Card x={56} y={18} w={108} h={184} rx={18} />
      </Lifted>
      <rect
        x="92"
        y="25"
        width="36"
        height="4"
        rx="2"
        className="fill-border"
      />
      <circle cx="76" cy="44" r="7" fill="#229ED9" />
      <Bar x={88} y={38} w={44} tone="strong" />
      <Bar x={88} y={47} w={26} h={4} tone="faint" />
      <line x1="56" y1="58" x2="164" y2="58" className="stroke-border" />

      <rect
        x="66"
        y="66"
        width="62"
        height="16"
        rx="8"
        className="fill-muted"
      />
      <rect
        x="96"
        y="88"
        width="58"
        height="16"
        rx="8"
        className="fill-primary"
        opacity="0.85"
      />
      <Appear at={0.04} dur={D}>
        <rect
          x="66"
          y="110"
          width="74"
          height="16"
          rx="8"
          className="fill-muted"
        />
        <Bar x={73} y={115.5} w={52} />
      </Appear>
      <Appear at={0.5} dur={D} until={0.85}>
        <rect
          x="118"
          y="134"
          width="36"
          height="16"
          rx="8"
          className="fill-primary"
          opacity="0.2"
        />
        {[128, 136, 144].map((cx) => (
          <circle key={cx} cx={cx} cy="142" r="1.8" className="fill-primary" />
        ))}
      </Appear>
      <Appear at={0.86} dur={D}>
        <rect
          x="84"
          y="134"
          width="70"
          height="28"
          rx="10"
          className="fill-primary"
        />
        <rect
          x="92"
          y="141"
          width="50"
          height="4"
          rx="2"
          fill="white"
          opacity="0.9"
        />
        <rect
          x="92"
          y="150"
          width="34"
          height="4"
          rx="2"
          fill="white"
          opacity="0.7"
        />
      </Appear>

      <Route
        d="M166 118 C 220 118, 240 98, 290 98 S 380 98, 418 98"
        end={[418, 98]}
        dur={D}
        from={0.06}
        to={0.42}
      >
        <Parcel icon={MessageCircle} />
      </Route>
      <Route
        d="M430 128 C 400 196, 230 200, 166 150"
        end={[166, 150]}
        dur={D}
        from={0.6}
        to={0.84}
      >
        <Parcel icon={MessageCircle} className="fill-emerald-500" />
      </Route>
      <Hub x={290} y={96} />

      <Lifted>
        <Card x={418} y={66} w={120} h={66} />
      </Lifted>
      <circle cx="442" cy="90" r="13" className="fill-primary" opacity="0.14" />
      <Glyph icon={Bot} x={442} y={90} size={15} className="text-primary" />
      <Bar x={462} y={84} w={56} tone="strong" />
      <Bar x={462} y={94} w={38} />
      <Typing
        x={432}
        y={112}
        widths={[90]}
        dur={D}
        at={0.44}
        color="hsl(var(--primary))"
      />
    </Scene>
  );
}
