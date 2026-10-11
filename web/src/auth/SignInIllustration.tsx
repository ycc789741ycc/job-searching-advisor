/**
 * The sign-in screen's picture of how CareerPolaris works, in three labelled
 * stages: 1 your evidence, 2 the strengths scored from it, 3 a target role and
 * a résumé written for it. One SVG on a 680 × 480 grid, so it scales with its
 * column; the values are the 00 Sign in prototype's (option B).
 */

/** The drawing's colours: Organic tokens, as literals like AppIcon's. */
const C = {
  night: "#2e2b25", // neutral-900
  cream: "#f5ead8", // bg
  paper: "#fffdf8",
  ink: "#201e1d", // text
  accent: "#c67139",
  accent300: "#ffc6a5",
  accent500: "#d67f48",
  accent600: "#b2622d",
  accent700: "#8c491a",
  peach: "#ffe1d0", // accent-200
  sage: "#ccdbb2", // accent-2-300
  sage200: "#e1eecc",
  sage800: "#3d472b",
  neutral300: "#dcd3c4",
  neutral500: "#a19786",
  neutral700: "#645c50",
};

const HEADING = { fontFamily: "var(--font-heading)" };

const STAGES = [
  { x: 22, label: "Your evidence" },
  { x: 256, label: "Strengths" },
  { x: 470, label: "Role & résumé" },
];

/** A dot per fact, its title and source beside it. */
const EVIDENCE = [
  { x: 34, y: 92, dot: C.peach, title: "PR #1284 merged", source: "GitHub" },
  {
    x: 58,
    y: 148,
    dot: C.peach,
    title: "RFC-017 author",
    source: "Design doc",
  },
  { x: 32, y: 204, dot: C.sage, title: "PAY-311 rollout lead", source: "Jira" },
  {
    x: 56,
    y: 260,
    dot: C.peach,
    title: "256 commits to ledger",
    source: "GitHub",
  },
  { x: 34, y: 316, dot: C.sage, title: "Incident review", source: "Jira" },
  {
    x: 60,
    y: 372,
    dot: C.accent300,
    title: "Mentored 3 juniors",
    source: "Résumé",
  },
  {
    x: 36,
    y: 428,
    dot: C.accent300,
    title: "6 years backend",
    source: "Résumé",
  },
];

const RADAR = { cx: 337, cy: 268, r: 56 };
const RINGS = [1, 37 / 56, 18.5 / 56];

/** Clockwise from the top; `score` is the share of the outer ring. */
const AXES: {
  label: string;
  score: number;
  x: number;
  y: number;
  anchor: "start" | "middle" | "end";
}[] = [
  { label: "Backend", score: 0.92, x: 337, y: 199, anchor: "middle" },
  { label: "Data", score: 0.78, x: 395, y: 238.5, anchor: "start" },
  { label: "Reliability", score: 0.7, x: 395, y: 305.5, anchor: "start" },
  { label: "Incidents", score: 0.42, x: 337, y: 345, anchor: "middle" },
  { label: "Leadership", score: 0.55, x: 279, y: 305.5, anchor: "end" },
  { label: "Mentoring", score: 0.66, x: 279, y: 238.5, anchor: "end" },
];

function getRadarPoint(axis: number, share: number): [number, number] {
  const angle = ((axis * 60 - 90) * Math.PI) / 180;
  const radius = RADAR.r * share;
  return [
    RADAR.cx + radius * Math.cos(angle),
    RADAR.cy + radius * Math.sin(angle),
  ];
}

function getPolygon(shares: number[]): string {
  return shares
    .map((share, axis) =>
      getRadarPoint(axis, share)
        .map((n) => n.toFixed(1))
        .join(","),
    )
    .join(" ");
}

const SKILLS = [
  { label: "Backend", x: 477, width: 47 },
  { label: "Data", x: 527, width: 34 },
  { label: "Go", x: 564, width: 24 },
];

const FIGURE_LABEL =
  "How CareerPolaris works: 1, evidence from GitHub, Jira and your résumé; 2, scored into a strength profile; 3, a route to a target role and a résumé written for it, every line backed by the evidence";

export function SignInIllustration() {
  return (
    <figure className="sign-in-figure" aria-label={FIGURE_LABEL}>
      <svg
        viewBox="0 0 680 480"
        aria-hidden="true"
        style={{ display: "block", width: "100%", height: "auto" }}
        fontFamily="Figtree, system-ui, sans-serif"
      >
        <defs>
          <filter
            id="sign-in-card-shadow"
            x="-30%"
            y="-20%"
            width="160%"
            height="150%"
          >
            <feDropShadow
              dx="0"
              dy="14"
              stdDeviation="17"
              floodColor="#000"
              floodOpacity="0.4"
            />
          </filter>
        </defs>

        <rect width="680" height="480" rx="28" fill={C.night} />

        {/* Sky and the column rules between the stages. */}
        <g fill={C.cream} opacity="0.22">
          <circle cx="190" cy="70" r="1.2" />
          <circle cx="300" cy="120" r="1" />
          <circle cx="420" cy="60" r="1.4" />
          <circle cx="640" cy="64" r="1" />
          <circle cx="270" cy="430" r="1.3" />
          <circle cx="400" cy="400" r="1" />
          <circle cx="180" cy="300" r="1" />
        </g>
        {[226, 452].map((x) => (
          <g key={x}>
            <line
              x1={x}
              y1="56"
              x2={x}
              y2="456"
              stroke={C.cream}
              strokeOpacity="0.12"
              strokeDasharray="3 5"
            />
            <path
              d={`M${x - 4} 21 L${x + 4} 30 L${x - 4} 39`}
              fill="none"
              stroke={C.accent}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </g>
        ))}

        {STAGES.map((stage, index) => (
          <g key={stage.label}>
            <circle cx={stage.x + 10} cy="30" r="10" fill={C.accent} />
            <text
              x={stage.x + 10}
              y="34"
              textAnchor="middle"
              fontSize="11"
              fontWeight="700"
              fill={C.paper}
            >
              {index + 1}
            </text>
            <text
              x={stage.x + 27}
              y="34"
              fontSize="11.5"
              fontWeight="700"
              fill={C.accent300}
              style={{ letterSpacing: "0.08em" }}
            >
              {stage.label.toUpperCase()}
            </text>
          </g>
        ))}

        {/* 1 — the evidence. */}
        {EVIDENCE.map((fact) => (
          <g key={fact.title}>
            <circle
              cx={fact.x}
              cy={fact.y}
              r="5.5"
              fill={fact.dot}
              stroke={C.night}
              strokeWidth="2.5"
            />
            <text
              x={fact.x + 12}
              y={fact.y + 2}
              fontSize="11.5"
              fontWeight="600"
              fill={C.cream}
            >
              {fact.title}
            </text>
            <text
              x={fact.x + 12}
              y={fact.y + 14}
              fontSize="9.5"
              fill={C.neutral500}
            >
              {fact.source}
            </text>
          </g>
        ))}

        {/* 2 — the strengths. */}
        <g fontSize="9.5" fill={C.neutral300}>
          {RINGS.map((share) => (
            <polygon
              key={share}
              points={getPolygon(AXES.map(() => share))}
              fill="none"
              stroke={C.cream}
              strokeOpacity="0.18"
            />
          ))}
          {AXES.map((axis, index) => {
            const [x, y] = getRadarPoint(index, 1);
            return (
              <line
                key={axis.label}
                x1={RADAR.cx}
                y1={RADAR.cy}
                x2={x.toFixed(1)}
                y2={y.toFixed(1)}
                stroke={C.cream}
                strokeOpacity="0.14"
              />
            );
          })}
          <polygon
            points={getPolygon(AXES.map((axis) => axis.score))}
            fill="rgba(198,113,57,0.38)"
            stroke={C.accent500}
            strokeWidth="2"
          />
          {AXES.map((axis, index) => {
            const [x, y] = getRadarPoint(index, axis.score);
            return (
              <circle
                key={axis.label}
                cx={x.toFixed(1)}
                cy={y.toFixed(1)}
                r="3"
                fill={C.peach}
              />
            );
          })}
          {AXES.map((axis) => (
            <text
              key={axis.label}
              x={axis.x}
              y={axis.y}
              textAnchor={axis.anchor}
            >
              {axis.label}
            </text>
          ))}
        </g>
        <text
          x="338"
          y="371"
          textAnchor="middle"
          fontSize="11"
          fill={C.neutral300}
        >
          <tspan x="338">Scored from the evidence on the left,</tspan>
          <tspan x="338" dy="14.85">
            each skill with a confidence
          </tspan>
        </text>

        {/* 3 — the route to a target role. */}
        <circle cx="566" cy="92" r="40" fill={C.accent} opacity="0.18" />
        <circle cx="566" cy="92" r="22" fill={C.accent} opacity="0.3" />
        <path
          d="M376 204 Q 430 110 540 92"
          fill="none"
          stroke={C.accent300}
          strokeWidth="2"
          strokeDasharray="6 7"
          strokeLinecap="round"
        />
        <path
          d="M396 318 C 425 330, 440 330, 462 330"
          fill="none"
          stroke={C.accent300}
          strokeWidth="1.4"
          strokeDasharray="2 5"
        />
        <path
          d="M566 68 L572 86 L590 92 L572 98 L566 116 L560 98 L542 92 L560 86 Z"
          fill={C.peach}
        />
        <text
          x="399"
          y="129"
          textAnchor="middle"
          fontSize="10"
          fontWeight="700"
          fill={C.accent300}
          transform="rotate(-24 399 125)"
          style={{ letterSpacing: "0.1em" }}
        >
          GAP PLAN
        </text>
        <text
          x="566"
          y="130"
          textAnchor="middle"
          fontSize="10"
          fontWeight="700"
          fill={C.accent300}
          style={{ letterSpacing: "0.1em" }}
        >
          TARGET ROLE
        </text>
        <text
          x="566"
          y="148"
          textAnchor="middle"
          fontSize="15"
          fill={C.cream}
          style={HEADING}
        >
          Staff Engineer, Payments
        </text>

        {/* The résumé written for it. */}
        <rect
          x="464"
          y="182"
          width="202"
          height="280"
          rx="6"
          fill={C.paper}
          filter="url(#sign-in-card-shadow)"
        />
        <g fill={C.ink}>
          <text x="477" y="208" fontSize="15" style={HEADING}>
            Maya Chen
          </text>
          <text x="477" y="221" fontSize="9" fill={C.neutral700}>
            Staff Engineer, Payments · Berlin
          </text>
          <rect x="477" y="231" width="176" height="1" opacity="0.6" />
          <ResumeHeading y={248}>EXPERIENCE</ResumeHeading>
          <text x="477" y="264" fontSize="10" fontWeight="700">
            Senior Backend Engineer
          </text>
          <text x="477" y="276" fontSize="8.5" fill={C.neutral700}>
            Northwind Pay · 2022 – now
          </text>
          <BackedLine y={281.5}>Split ledger reads/writes (RFC-017)</BackedLine>
          <BackedLine y={301.5}>Led PAY-311 rollout across 3 teams</BackedLine>
          <PlaceholderLine y={328} width={141} />
          <text x="477" y="351" fontSize="10" fontWeight="700">
            Platform Engineer
          </text>
          <text x="477" y="363" fontSize="8.5" fill={C.neutral700}>
            Kestrel Cloud · 2019 – 2022
          </text>
          <PlaceholderLine y={375} width={151} />
          <ResumeHeading y={398}>SKILLS</ResumeHeading>
          {SKILLS.map((skill) => (
            <g key={skill.label}>
              <rect
                x={skill.x}
                y="404.5"
                width={skill.width}
                height="14"
                rx="7"
                fill={C.sage200}
              />
              <text
                x={skill.x + skill.width / 2}
                y="414.5"
                textAnchor="middle"
                fontSize="9"
                fontWeight="600"
                fill={C.sage800}
              >
                {skill.label}
              </text>
            </g>
          ))}
        </g>
        <text x="470" y="476" fontSize="9.5" fill={C.neutral500}>
          <tspan fill={C.accent300}>✦</tspan> line backed by your evidence
        </text>
      </svg>
    </figure>
  );
}

function ResumeHeading({ y, children }: { y: number; children: string }) {
  return (
    <text
      x="477"
      y={y}
      fontSize="8.5"
      fontWeight="700"
      fill={C.accent700}
      style={{ letterSpacing: "0.12em" }}
    >
      {children}
    </text>
  );
}

/** A résumé line that rests on evidence: ✦ on peach. `y` is its top. */
function BackedLine({ y, children }: { y: number; children: string }) {
  return (
    <g>
      <rect x="473" y={y} width="184" height="17" rx="6" fill={C.peach} />
      <text x="477" y={y + 12} fontSize="9.5" fill={C.accent600}>
        ✦
      </text>
      <text x="491" y={y + 12} fontSize="9.5">
        {children}
      </text>
    </g>
  );
}

/** A line not drawn out: a bullet and a grey bar. `y` is its middle. */
function PlaceholderLine({ y, width }: { y: number; width: number }) {
  return (
    <g>
      <text x="477" y={y + 3} fontSize="9.5" fill={C.neutral500}>
        •
      </text>
      <rect
        x="486"
        y={y - 3}
        width={width}
        height="6"
        rx="3"
        fill={C.neutral300}
      />
    </g>
  );
}
