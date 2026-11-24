"use client";

import { ArrowUp, Bot } from "lucide-react";
import {
  Appear,
  Bar,
  Card,
  Done,
  Glyph,
  Lifted,
  Loop,
  Parcel,
  Route,
  Scene,
  Spinner,
  Tick,
  Typing,
} from "./kit";

const D = 6;

function Row({ y, children }: { y: number; children?: React.ReactNode }) {
  return (
    <g>
      <circle cx="350" cy={y} r="10" className="fill-primary" opacity="0.14" />
      <Glyph icon={Bot} x={350} y={y} size={12} className="text-primary" />
      <Bar x={368} y={y - 7} w={92} tone="strong" />
      <Bar x={368} y={y + 3} w={60} />
      {children}
    </g>
  );
}

/** A task typed into AgentArea joins the list, runs and finishes while others carry on. */
export default function TasksScene() {
  return (
    <Scene>
      <Lifted>
        <Card x={36} y={76} w={180} h={68} rx={14} />
      </Lifted>
      <Typing
        x={52}
        y={94}
        widths={[120, 84]}
        dur={D}
        at={0.02}
        gap={12}
        color="hsl(var(--foreground))"
      />
      <circle cx="196" cy="126" r="10" className="fill-primary" />
      <Glyph
        icon={ArrowUp}
        x={196}
        y={126}
        size={12}
        className="text-white"
        strokeWidth={2.5}
      />

      <Route
        d="M216 110 C 270 110, 290 64, 330 64"
        end={[330, 64]}
        dur={D}
        from={0.14}
        to={0.32}
      >
        <Parcel />
      </Route>

      <Lifted>
        <Card x={330} y={34} w={214} h={156} />
      </Lifted>
      {[86, 138].map((y) => (
        <line
          key={y}
          x1="330"
          y1={y}
          x2="544"
          y2={y}
          className="stroke-border"
        />
      ))}
      <Appear at={0.32} dur={D}>
        <Row y={60}>
          <Appear at={0.32} until={0.74} dur={D}>
            <Spinner x={524} y={60} />
          </Appear>
        </Row>
      </Appear>
      <Done x={524} y={60} dur={D} at={0.75} />
      <Row y={112}>
        <Spinner x={524} y={112} />
        <rect
          x="368"
          y="122"
          width="120"
          height="4"
          rx="2"
          className="fill-muted"
        />
        <rect
          x="368"
          y="122"
          width="40"
          height="4"
          rx="2"
          className="fill-primary"
        >
          <Loop
            attr="width"
            values={[40, 112, 40]}
            times={[0, 0.97, 1]}
            dur={D}
          />
        </rect>
      </Row>
      <Row y={164}>
        <Tick x={524} y={164} />
      </Row>
    </Scene>
  );
}
