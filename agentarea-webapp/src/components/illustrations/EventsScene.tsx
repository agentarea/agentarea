"use client";

import { GitBranch, Mail, Rss, Webhook } from "lucide-react";
import { Bar, Card, Lifted, Parcel, Route, Scene, Tile, useScene } from "./kit";

const D = 6;
const ROW = 26;
const TOP = 64;

const SOURCES = [
  { y: 40, icon: Webhook, color: "#2252B3" },
  { y: 86, icon: Mail, color: "#ef4444" },
  { y: 132, icon: Rss, color: "#f97316" },
  { y: 178, icon: GitBranch, color: "#8b5cf6" },
];

const ARRIVALS = SOURCES.map((_, k) => 0.06 + k * 0.24 + 0.14);

/** Signals from everywhere land in one log, newest on top. */
export default function EventsScene() {
  const { id, moving } = useScene();
  const values = [0];
  const times = [0];
  ARRIVALS.forEach((t, k) => {
    values.push(k * ROW, (k + 1) * ROW);
    times.push(t, t + 0.04);
  });
  values.push(SOURCES.length * ROW);
  times.push(1);

  return (
    <Scene>
      <defs>
        <clipPath id={`${id}-log`}>
          <rect x="300" y={TOP - 12} width="250" height="132" />
        </clipPath>
      </defs>
      {SOURCES.map((s, k) => (
        <Route
          key={s.y}
          d={`M104 ${s.y} C 200 ${s.y}, 220 ${TOP}, 300 ${TOP}`}
          end={[300, TOP]}
          dur={D}
          from={0.06 + k * 0.24}
          to={ARRIVALS[k]}
          ring={false}
        >
          <Parcel className="fill-primary" />
        </Route>
      ))}
      {SOURCES.map((s) => (
        <Tile key={s.y} x={82} y={s.y} size={40} icon={s.icon}>
          <circle cx={98} cy={s.y - 16} r="3" fill={s.color} />
        </Tile>
      ))}

      <Lifted>
        <Card x={300} y={30} w={250} h={170} />
      </Lifted>
      <Bar x={314} y={42} w={64} h={5} tone="strong" />
      <line
        x1="300"
        y1={TOP - 12}
        x2="550"
        y2={TOP - 12}
        className="stroke-border"
      />
      <g clipPath={`url(#${id}-log)`}>
        <g transform={moving ? undefined : `translate(0 ${ROW * 4})`}>
          {Array.from({ length: 9 }, (_, n) => n - 4).map((i) => {
            const y = TOP + i * ROW;
            const source = SOURCES[(((-i - 1) % 4) + 4) % 4];
            return (
              <g key={i}>
                <Bar x={314} y={y + 6} w={22} h={4} tone="faint" />
                <circle
                  cx="350"
                  cy={y + 8}
                  r="4"
                  fill={source.color}
                  opacity="0.85"
                />
                <Bar
                  x={362}
                  y={y + 6}
                  w={[96, 72, 110, 84][((i % 4) + 4) % 4]}
                  h={4}
                  tone="strong"
                  opacity={0.55}
                />
                <rect
                  x="500"
                  y={y + 2}
                  width="36"
                  height="12"
                  rx="6"
                  className="fill-muted"
                />
                <line
                  x1="300"
                  y1={y + 18}
                  x2="550"
                  y2={y + 18}
                  className="stroke-border"
                  opacity="0.6"
                />
              </g>
            );
          })}
          {moving && (
            <animateTransform
              attributeName="transform"
              type="translate"
              values={values.map((v) => `0 ${v}`).join(";")}
              keyTimes={times.map((t) => t.toFixed(3)).join(";")}
              dur={`${D}s`}
              repeatCount="indefinite"
            />
          )}
        </g>
      </g>
    </Scene>
  );
}
