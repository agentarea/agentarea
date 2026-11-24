"use client";

import { Server } from "lucide-react";
import {
  Appear,
  Bar,
  Card,
  Lifted,
  Loop,
  Parcel,
  Route,
  Scene,
  Tile,
  useScene,
} from "./kit";

const D = 6;
const BARS = [34, 52, 28, 60, 44, 70];

/** A connection's data comes in and an app's screen builds itself from it. */
export default function AppsScene() {
  const { moving } = useScene();
  return (
    <Scene>
      <Route
        d="M112 110 C 140 110, 150 110, 176 110"
        end={[176, 110]}
        dur={D}
        from={0.04}
        to={0.16}
      >
        <Parcel />
      </Route>
      <Tile
        x={88}
        y={110}
        size={48}
        icon={Server}
        iconClassName="text-emerald-600"
      />

      <Lifted>
        <Card x={176} y={26} w={330} h={176} rx={12} />
      </Lifted>
      {["#ff5f57", "#febc2e", "#28c840"].map((fill, i) => (
        <circle key={fill} cx={192 + i * 10} cy="42" r="3" fill={fill} />
      ))}
      <rect
        x="236"
        y="36"
        width="160"
        height="12"
        rx="6"
        className="fill-muted"
      />
      <line x1="176" y1="56" x2="506" y2="56" className="stroke-border" />
      {[70, 84, 98, 112].map((y, i) => (
        <Bar
          key={y}
          x={190}
          y={y}
          w={[44, 36, 40, 30][i]}
          h={5}
          tone={i === 0 ? "primary" : "faint"}
        />
      ))}
      <line x1="246" y1="56" x2="246" y2="202" className="stroke-border" />

      <Appear at={0.18} dur={D}>
        <Bar x={260} y={68} w={90} h={7} tone="strong" />
        <rect
          x="260"
          y="84"
          width="232"
          height="66"
          rx="8"
          className="fill-muted"
          opacity="0.6"
        />
      </Appear>
      {BARS.map((h, i) => {
        const x = 276 + i * 34;
        const at = 0.24 + i * 0.04;
        return (
          <rect
            key={x}
            x={x}
            y={moving ? 144 : 144 - h * 0.8}
            width="18"
            height={moving ? 0 : h * 0.8}
            rx="3"
            className="fill-primary"
            opacity={0.35 + i * 0.1}
          >
            <Loop
              attr="height"
              values={[0, 0, h * 0.8, h * 0.8, 0]}
              times={[0, at, at + 0.1, 0.97, 1]}
              dur={D}
              spline
            />
            <Loop
              attr="y"
              values={[144, 144, 144 - h * 0.8, 144 - h * 0.8, 144]}
              times={[0, at, at + 0.1, 0.97, 1]}
              dur={D}
              spline
            />
          </rect>
        );
      })}
      {[160, 176].map((y, i) => (
        <Appear key={y} at={0.5 + i * 0.08} dur={D}>
          <Bar x={260} y={y} w={120} h={5} tone="soft" />
          <Bar x={400} y={y} w={40} h={5} tone="faint" />
          <Bar x={456} y={y} w={30} h={5} tone="primary" opacity={0.5} />
        </Appear>
      ))}
    </Scene>
  );
}
