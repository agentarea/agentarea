"use client";

import {
  createContext,
  useContext,
  useId,
  type ReactNode,
  type SVGProps,
} from "react";
import { useReducedMotion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export const W = 580;
export const H = 220;

const SceneContext = createContext({ id: "scene", moving: true });

export function useScene() {
  return useContext(SceneContext);
}

const LOGO =
  "M55.6437 26.7221C56.4347 26.694 57.2553 26.6955 58.0471 26.7029C62.3164 26.7434 66.61 26.6334 70.8766 26.7113C71.01 27.2446 71.5066 28.1757 71.7643 28.6965C72.2244 29.6228 72.673 30.5547 73.1103 31.492L80.7742 47.9005C81.1701 48.7434 81.6496 49.5426 82.053 50.4104C87.5824 62.6124 93.2097 74.7694 98.9344 86.8804L102.851 95.2185C103.524 96.6532 104.423 98.7533 105.247 100.034C103.43 100.057 101.551 100.013 99.7241 100.016L86.6315 100.016C86.2348 99.4378 85.8268 98.4141 85.5196 97.7504C84.7037 95.9838 83.8994 94.2117 83.1069 92.4342C82.8612 91.8887 82.3813 90.7377 82.0555 90.3008C81.5099 90.2229 80.5018 90.2484 79.9172 90.2477L76.2148 90.2468L63.4579 90.2535L60.4458 90.2545C59.9735 90.2545 59.0175 90.2797 58.5909 90.1992C58.4693 89.9377 59.1317 88.4882 59.2877 88.1785C60.3463 86.0773 61.1847 83.8179 62.2596 81.7333C62.9398 80.4141 63.6079 78.4091 64.4302 77.2452C65.3754 77.1524 67.4221 77.2076 68.4344 77.2077C70.9515 77.2166 73.4686 77.2054 75.9855 77.174C75.6768 76.1215 74.5679 74.1643 74.1161 73.1257C73.2221 71.071 72.2893 69.0283 71.3235 67.006C70.9196 66.0286 70.3626 64.936 69.9027 63.9713L67.4102 58.7025C66.0292 55.745 64.7317 52.6321 63.2207 49.7318C62.9731 50.4761 62.1836 51.8103 61.823 52.5892L58.2113 60.4734L46.2691 86.3097C44.8114 89.4359 43.2208 92.5527 41.8174 95.7183C41.1944 97.1238 40.4697 98.5975 39.935 100.039C38.2921 100.086 36.4697 100.038 34.8182 100.029C32.4457 100.018 30.0733 100.021 27.7008 100.038L23.3464 100.044C23.0523 100.044 21.7356 100.063 21.5323 100.013L21.4941 99.9233C21.5501 99.4207 23.5386 95.4073 23.8962 94.6446L32.8245 75.7358L37.9591 64.5834L50.6246 37.4147L53.9914 30.2045C54.2246 29.7012 55.4316 26.941 55.6437 26.7221Z";

/** The stage every empty-page picture is drawn on: a dotted field fading out from a soft glow. */
export function Scene({ children }: { children: ReactNode }) {
  const id = useId().replace(/:/g, "");
  const moving = !(useReducedMotion() ?? false);
  return (
    <SceneContext.Provider value={{ id, moving }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full max-w-[540px]"
        aria-hidden="true"
      >
        <defs>
          <pattern
            id={`${id}-dots`}
            width="14"
            height="14"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" className="fill-muted-foreground" />
          </pattern>
          <radialGradient id={`${id}-fade`} cx="50%" cy="50%" r="55%">
            <stop offset="0%" stopColor="white" stopOpacity="0.5" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <mask id={`${id}-mask`}>
            <rect width={W} height={H} fill={`url(#${id}-fade)`} />
          </mask>
          <filter
            id={`${id}-shadow`}
            x="-30%"
            y="-30%"
            width="160%"
            height="170%"
          >
            <feDropShadow dx="0" dy="6" stdDeviation="8" floodOpacity="0.12" />
          </filter>
          <filter
            id={`${id}-glow`}
            x="-100%"
            y="-100%"
            width="300%"
            height="300%"
          >
            <feGaussianBlur stdDeviation="4" />
          </filter>
        </defs>
        <rect
          width={W}
          height={H}
          fill={`url(#${id}-dots)`}
          mask={`url(#${id}-mask)`}
          opacity="0.35"
        />
        <ellipse
          cx={W / 2}
          cy={H / 2 + 10}
          rx="250"
          ry="86"
          className="fill-primary"
          opacity="0.05"
        />
        {children}
      </svg>
    </SceneContext.Provider>
  );
}

/** Children cast the scene's soft drop shadow. */
export function Lifted({ children }: { children: ReactNode }) {
  const { id } = useScene();
  return <g filter={`url(#${id}-shadow)`}>{children}</g>;
}

/** An `<animate>` on one attribute over the scene's loop; nothing when motion is reduced. */
export function Loop({
  attr,
  values,
  times,
  dur,
  begin = 0,
  spline,
}: {
  attr: string;
  values: (number | string)[];
  times: number[];
  dur: number;
  begin?: number;
  spline?: boolean;
}) {
  const { moving } = useScene();
  if (!moving) return null;
  return (
    <animate
      attributeName={attr}
      values={values.join(";")}
      keyTimes={times.map((t) => t.toFixed(3)).join(";")}
      dur={`${dur}s`}
      begin={`${begin}s`}
      repeatCount="indefinite"
      {...(spline
        ? {
            calcMode: "spline",
            keySplines: times
              .slice(1)
              .map(() => "0.45 0 0.25 1")
              .join(";"),
          }
        : {})}
    />
  );
}

/** A white card with a hairline border. */
export function Card({
  x,
  y,
  w,
  h,
  rx = 12,
  rotate,
  opacity,
  className,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  rx?: number;
  rotate?: number;
  opacity?: number;
  className?: string;
}) {
  return (
    <rect
      x={x}
      y={y}
      width={w}
      height={h}
      rx={rx}
      transform={
        rotate ? `rotate(${rotate} ${x + w / 2} ${y + h / 2})` : undefined
      }
      opacity={opacity}
      className={cn("fill-background stroke-border", className)}
    />
  );
}

const TONES = {
  strong: ["fill-foreground", 0.75],
  soft: ["fill-muted-foreground", 0.35],
  faint: ["fill-muted-foreground", 0.2],
  primary: ["fill-primary", 0.75],
  tint: ["fill-primary", 0.14],
} as const;

/** A line of placeholder text. */
export function Bar({
  x,
  y,
  w,
  h = 5,
  tone = "soft",
  fill,
  opacity,
  children,
}: {
  x: number;
  y: number;
  w: number;
  h?: number;
  tone?: keyof typeof TONES;
  fill?: string;
  opacity?: number;
  children?: ReactNode;
}) {
  const [className, base] = TONES[tone];
  return (
    <rect
      x={x}
      y={y}
      width={w}
      height={h}
      rx={h / 2}
      className={fill ? undefined : className}
      fill={fill}
      opacity={opacity ?? base}
    >
      {children}
    </rect>
  );
}

/** A Lucide glyph centred on (x, y). */
export function Glyph({
  icon: Icon,
  x,
  y,
  size = 16,
  className,
  ...props
}: {
  icon: LucideIcon;
  x: number;
  y: number;
  size?: number;
  className?: string;
} & Omit<SVGProps<SVGSVGElement>, "x" | "y">) {
  return (
    <Icon
      x={x - size / 2}
      y={y - size / 2}
      width={size}
      height={size}
      className={cn("text-muted-foreground", className)}
      {...(props as object)}
    />
  );
}

/** A rounded tile holding a glyph: an entity, a source, a tool. */
export function Tile({
  x,
  y,
  size = 44,
  icon,
  className,
  iconClassName,
  children,
}: {
  x: number;
  y: number;
  size?: number;
  icon?: LucideIcon;
  className?: string;
  iconClassName?: string;
  children?: ReactNode;
}) {
  return (
    <g>
      <Lifted>
        <rect
          x={x - size / 2}
          y={y - size / 2}
          width={size}
          height={size}
          rx={size * 0.28}
          className={cn("fill-background stroke-border", className)}
        />
      </Lifted>
      {icon && (
        <Glyph
          icon={icon}
          x={x}
          y={y}
          size={size * 0.44}
          className={iconClassName}
        />
      )}
      {children}
    </g>
  );
}

/** AgentArea itself: its mark on a dark tile, named underneath. */
export function Hub({
  x,
  y,
  size = 58,
  label = true,
}: {
  x: number;
  y: number;
  size?: number;
  label?: boolean;
}) {
  const left = x - size / 2;
  const top = y - size / 2;
  return (
    <g>
      <Lifted>
        <rect
          x={left}
          y={top}
          width={size}
          height={size}
          rx={size * 0.24}
          fill="#070817"
          className="stroke-border"
        />
      </Lifted>
      <path
        d={LOGO}
        fill="white"
        transform={`translate(${left} ${top}) scale(${size / 126})`}
      />
      {label && (
        <text
          x={x}
          y={y + size / 2 + 16}
          textAnchor="middle"
          fontSize="11"
          fontWeight="600"
          className="fill-foreground"
          opacity="0.7"
        >
          AgentArea
        </text>
      )}
    </g>
  );
}

/** A small rounded parcel: a task, a message, an event in flight. */
export function Parcel({
  icon,
  className = "fill-primary",
  iconClassName = "text-white",
}: {
  icon?: LucideIcon;
  className?: string;
  iconClassName?: string;
}) {
  const { id } = useScene();
  return (
    <>
      <circle
        r="9"
        className={className}
        opacity="0.45"
        filter={`url(#${id}-glow)`}
      />
      <rect
        x="-8"
        y="-6.5"
        width="16"
        height="13"
        rx="4"
        className={className}
      />
      {icon ? (
        <Glyph
          icon={icon}
          x={0}
          y={0}
          size={9}
          className={iconClassName}
          strokeWidth={2.5}
        />
      ) : (
        <>
          <rect
            x="-4.5"
            y="-2.6"
            width="9"
            height="1.6"
            rx="0.8"
            fill="white"
            opacity="0.9"
          />
          <rect
            x="-4.5"
            y="0.9"
            width="6"
            height="1.6"
            rx="0.8"
            fill="white"
            opacity="0.7"
          />
        </>
      )}
    </>
  );
}

/**
 * A dashed route; while motion runs, `children` travels it once per loop
 * between `from` and `to` (fractions of the loop) and rings where it lands.
 */
export function Route({
  d,
  end,
  dur,
  begin = 0,
  from = 0.02,
  to = 0.5,
  ring = true,
  faint,
  children,
}: {
  d: string;
  end?: [number, number];
  dur: number;
  begin?: number;
  from?: number;
  to?: number;
  ring?: boolean;
  faint?: boolean;
  children?: ReactNode;
}) {
  const { moving } = useScene();
  return (
    <g>
      <path
        d={d}
        fill="none"
        className="stroke-primary"
        strokeOpacity={faint ? 0.2 : 0.35}
        strokeWidth="1.5"
        strokeDasharray="4 5"
        strokeLinecap="round"
      >
        {moving && (
          <animate
            attributeName="stroke-dashoffset"
            from="18"
            to="0"
            dur="1s"
            repeatCount="indefinite"
          />
        )}
      </path>
      {moving && children && (
        <g opacity="0">
          {children}
          <animateMotion
            path={d}
            dur={`${dur}s`}
            begin={`${begin}s`}
            repeatCount="indefinite"
            keyPoints="0;0;1;1"
            keyTimes={`0;${from};${to};1`}
            calcMode="spline"
            keySplines="0 0 1 1;0.45 0 0.25 1;0 0 1 1"
          />
          <animate
            attributeName="opacity"
            values="0;0;1;1;0;0"
            keyTimes={`0;${from};${from + 0.03};${to};${Math.min(to + 0.04, 0.99)};1`}
            dur={`${dur}s`}
            begin={`${begin}s`}
            repeatCount="indefinite"
          />
        </g>
      )}
      {moving && ring && end && (
        <circle
          cx={end[0]}
          cy={end[1]}
          r="0"
          className="fill-none stroke-primary"
          strokeWidth="1.5"
          opacity="0"
        >
          <Loop
            attr="r"
            values={[0, 0, 14, 14]}
            times={[0, to - 0.01, Math.min(to + 0.2, 0.99), 1]}
            dur={dur}
            begin={begin}
          />
          <Loop
            attr="opacity"
            values={[0, 0.8, 0, 0]}
            times={[0, to - 0.01, Math.min(to + 0.2, 0.99), 1]}
            dur={dur}
            begin={begin}
          />
        </circle>
      )}
    </g>
  );
}

/** Lines that type themselves out at `at` (fraction of the loop) and clear at its end. */
export function Typing({
  x,
  y,
  widths,
  dur,
  at,
  gap = 12,
  color = "#a1a1aa",
  accent,
  bullet,
  begin = 0,
}: {
  x: number;
  y: number;
  widths: readonly number[];
  dur: number;
  at: number;
  begin?: number;
  gap?: number;
  color?: string;
  accent?: string;
  bullet?: string;
}) {
  const { moving } = useScene();
  return (
    <g>
      {widths.map((w, n) => {
        const start = Math.min(at + n * 0.035, 0.9);
        const tone = accent && n % 3 === 1 ? accent : color;
        return (
          <g key={n}>
            {bullet && (
              <rect
                x={x}
                y={y + n * gap}
                width="6"
                height="4"
                rx="2"
                fill={bullet}
                opacity="0.9"
              />
            )}
            <rect
              x={bullet ? x + 10 : x}
              y={y + n * gap}
              width={moving ? 0 : w}
              height="4"
              rx="2"
              fill={tone}
              opacity={tone === color ? 0.45 : 0.75}
            >
              <Loop
                attr="width"
                values={[0, 0, w, w, 0]}
                times={[0, start, Math.min(start + 0.07, 0.95), 0.97, 1]}
                dur={dur}
                begin={begin}
              />
            </rect>
          </g>
        );
      })}
    </g>
  );
}

/** A dark app window with traffic lights and an optional mark in its title bar. */
export function Window({
  x,
  y,
  w,
  h,
  mark,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  mark?: ReactNode;
}) {
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx="5"
        fill="#1b1b21"
        stroke="#2c2c34"
      />
      <circle cx={x + 7} cy={y + 7} r="1.8" fill="#ff5f57" />
      <circle cx={x + 13} cy={y + 7} r="1.8" fill="#febc2e" />
      <circle cx={x + 19} cy={y + 7} r="1.8" fill="#28c840" />
      {mark}
      <line x1={x} y1={y + 13} x2={x + w} y2={y + 13} stroke="#2c2c34" />
    </g>
  );
}

/** A green tick in a circle. */
export function Tick({ x, y, r = 7 }: { x: number; y: number; r?: number }) {
  return (
    <g>
      <circle cx={x} cy={y} r={r} fill="#10b981" />
      <path
        d={`M${x - r * 0.4} ${y} l${r * 0.28} ${r * 0.3} l${r * 0.5} -${r * 0.6}`}
        fill="none"
        stroke="white"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
  );
}

/** A tick that shows up at `at` and goes at the loop's end. */
export function Done({
  x,
  y,
  r = 7,
  dur,
  at,
  begin = 0,
}: {
  x: number;
  y: number;
  r?: number;
  dur: number;
  at: number;
  begin?: number;
}) {
  return (
    <Appear at={at} dur={dur} begin={begin}>
      <Tick x={x} y={y} r={r} />
    </Appear>
  );
}

/** A ring spinning while something runs. */
export function Spinner({ x, y, r = 6 }: { x: number; y: number; r?: number }) {
  const { moving } = useScene();
  return (
    <circle
      cx={x}
      cy={y}
      r={r}
      fill="none"
      className="stroke-primary"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeDasharray={`${r * 3.6} ${r * 2.8}`}
    >
      {moving && (
        <animateTransform
          attributeName="transform"
          type="rotate"
          from={`0 ${x} ${y}`}
          to={`360 ${x} ${y}`}
          dur="1s"
          repeatCount="indefinite"
        />
      )}
    </circle>
  );
}

/** Fades its children in at `at` and out at the loop's end. */
export function Appear({
  at,
  dur,
  until = 0.97,
  begin = 0,
  children,
}: {
  at: number;
  dur: number;
  until?: number;
  begin?: number;
  children: ReactNode;
}) {
  const { moving } = useScene();
  return (
    <g opacity={moving ? 0 : 1}>
      {children}
      <Loop
        attr="opacity"
        values={[0, 0, 1, 1, 0]}
        times={[0, at, Math.min(at + 0.04, until - 0.01), until, 1]}
        dur={dur}
        begin={begin}
      />
    </g>
  );
}
