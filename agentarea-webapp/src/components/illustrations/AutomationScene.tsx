"use client";

import { ClipboardList, Zap } from "lucide-react";
import {
  Bar,
  Card,
  Done,
  Glyph,
  Hub,
  Lifted,
  Loop,
  Parcel,
  Route,
  Scene,
  Tile,
  useScene,
} from "./kit";

const D = 5;

function Clock({ x, y }: { x: number; y: number }) {
  const { moving } = useScene();
  const hand = (len: number, dur: number, width: number) => (
    <line
      x1={x}
      y1={y}
      x2={x}
      y2={y - len}
      className="stroke-foreground"
      strokeWidth={width}
      strokeLinecap="round"
      opacity="0.75"
    >
      {moving && (
        <animateTransform
          attributeName="transform"
          type="rotate"
          from={`0 ${x} ${y}`}
          to={`360 ${x} ${y}`}
          dur={`${dur}s`}
          repeatCount="indefinite"
        />
      )}
    </line>
  );
  return (
    <Tile x={x} y={y} size={56}>
      <circle
        cx={x}
        cy={y}
        r="15"
        className="fill-none stroke-muted-foreground"
        strokeWidth="1.5"
        opacity="0.6"
      />
      {hand(7, D * 6, 2)}
      {hand(11, D, 1.4)}
      <circle cx={x} cy={y} r="1.8" className="fill-primary" />
    </Tile>
  );
}

/** A schedule and an event each wake AgentArea, which starts a task and sees it through. */
export default function AutomationScene() {
  return (
    <Scene>
      <Route
        d="M118 64 C 190 64, 220 96, 262 100"
        end={[262, 100]}
        dur={D}
        from={0.04}
        to={0.32}
      >
        <Parcel />
      </Route>
      <Route
        d="M118 156 C 190 156, 220 116, 262 110"
        end={[262, 110]}
        dur={D}
        begin={D / 2}
        from={0.04}
        to={0.32}
      >
        <Parcel icon={Zap} className="fill-amber-500" />
      </Route>
      <Route
        d="M318 100 C 350 90, 372 76, 404 76"
        end={[404, 76]}
        dur={D}
        from={0.34}
        to={0.44}
      />
      <Route
        d="M318 112 C 350 122, 372 136, 404 136"
        end={[404, 136]}
        dur={D}
        begin={D / 2}
        from={0.34}
        to={0.44}
      />

      <Clock x={90} y={64} />
      <Tile
        x={90}
        y={156}
        size={56}
        icon={Zap}
        iconClassName="text-amber-500"
      />
      <Hub x={290} y={104} />

      <Lifted>
        <Card x={404} y={42} w={146} h={130} />
      </Lifted>
      <line x1="404" y1="106" x2="550" y2="106" className="stroke-border" />
      {[0, 1].map((k) => {
        const y = 60 + k * 60;
        return (
          <g key={k}>
            <Glyph icon={ClipboardList} x={420} y={y + 6} size={14} />
            <Bar x={434} y={y + 3} w={k ? 64 : 80} tone="strong" />
            <rect
              x="420"
              y={y + 22}
              width="96"
              height="5"
              rx="2.5"
              className="fill-muted"
            />
            <rect
              x="420"
              y={y + 22}
              width="96"
              height="5"
              rx="2.5"
              className="fill-primary"
            >
              <Loop
                attr="width"
                values={[0, 0, 96, 96, 0]}
                times={[0, 0.44, 0.78, 0.97, 1]}
                dur={D}
                begin={k * (D / 2)}
              />
            </rect>
            <Done x={532} y={y + 14} dur={D} at={0.8} begin={k * (D / 2)} />
          </g>
        );
      })}
    </Scene>
  );
}
