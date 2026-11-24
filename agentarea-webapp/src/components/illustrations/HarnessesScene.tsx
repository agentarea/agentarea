"use client";

import { ClaudeIcon, CodexIcon } from "@/components/brand-icons";
import {
  Bar,
  Card,
  Hub,
  Lifted,
  Parcel,
  Route,
  Scene,
  Typing,
  Window,
} from "./kit";

const D = 3.6;

const WINDOWS = [
  {
    x: 340,
    Icon: ClaudeIcon,
    accent: "#D97757",
    at: 0.5,
    lines: [52, 34, 60, 44, 28, 50],
  },
  {
    x: 434,
    Icon: CodexIcon,
    accent: "#8B9CFF",
    at: 0.02,
    lines: [40, 58, 30, 52, 46, 24],
  },
] as const;

/** AgentArea sends tasks to Claude Code and Codex on your laptop, where each window types its work. */
export default function HarnessesScene() {
  return (
    <Scene>
      <Lifted>
        {[62, 92, 122].map((y, i) => (
          <Card
            key={y}
            x={28}
            y={y}
            w={66}
            h={24}
            rx={7}
            opacity={1 - i * 0.25}
          />
        ))}
      </Lifted>
      {[62, 92, 122].map((y, i) => (
        <g key={y} opacity={1 - i * 0.25}>
          <rect
            x={36}
            y={y + 8}
            width="8"
            height="8"
            rx="2.5"
            className="fill-primary"
            opacity="0.8"
          />
          <Bar x={50} y={y + 9.5} w={36} />
        </g>
      ))}
      <Route
        d="M94 104 C 110 104, 112 104, 120 104"
        dur={D}
        ring={false}
        faint
      />

      <Route d="M182 96 C 240 50, 318 44, 383 64" end={[383, 64]} dur={D}>
        <Parcel />
      </Route>
      <Route
        d="M182 90 C 262 0, 418 0, 477 62"
        end={[477, 62]}
        dur={D}
        begin={D / 2}
      >
        <Parcel />
      </Route>
      <Hub x={152} y={100} />

      <Lifted>
        <rect x="324" y="40" width="212" height="140" rx="12" fill="#1c1c21" />
        <path
          d="M300 180 H560 L548 194 Q546 196 542 196 H318 Q314 196 312 194 Z"
          className="fill-muted stroke-border"
        />
      </Lifted>
      <rect x="332" y="48" width="196" height="124" rx="6" fill="#0e0e12" />
      <rect
        x="410"
        y="180"
        width="40"
        height="4"
        rx="2"
        className="fill-border"
      />
      {WINDOWS.map(({ x, Icon, accent, at, lines }) => (
        <g key={x}>
          <Window
            x={x}
            y={58}
            w={86}
            h={104}
            mark={<Icon x={x + 72} y={60.5} width={9} height={9} />}
          />
          <Typing
            x={x + 8}
            y={79}
            widths={lines}
            dur={D}
            at={at}
            accent={accent}
            bullet={accent}
          />
        </g>
      ))}
    </Scene>
  );
}
