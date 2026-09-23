import { useId, useState } from "react";
import { radarPoint, radarPolygon } from "./geometry";

export interface RadarDimension {
  key: string;
  name: string;
  shortName: string;
  score: number;
  confidence: number;
  read: string;
}

interface Props {
  dimensions: RadarDimension[];
  /** A role's expected score per dimension, overlaid when a role is selected. */
  target?: { label: string; scores: Record<string, number> } | undefined;
  onSelect?: ((key: string) => void) | undefined;
  selectedKey?: string | undefined;
}

const SIZE = 420;
const CENTRE = { x: SIZE / 2, y: SIZE / 2 };
const RADIUS = 150;
const RINGS = [25, 50, 75, 100];

/**
 * The strength report.
 *
 * Axes are this user's own dimensions, so there is no fixed set and the chart
 * has to lay out whatever it is given. One series needs no legend — the title
 * names it; a target overlay makes two, and then the legend appears.
 */
export function SkillRadar({
  dimensions,
  target,
  onSelect,
  selectedKey,
}: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  const titleId = useId();

  if (dimensions.length === 0) {
    return (
      <p className="muted">
        No dimensions yet. Connect a source and run an analysis to see your
        radar.
      </p>
    );
  }

  const scores = dimensions.map((d) => d.score);
  const targetScores = target
    ? dimensions.map((d) => target.scores[d.key] ?? 0)
    : null;
  const active = hovered !== null ? dimensions[hovered] : null;

  return (
    <div>
      <div style={{ position: "relative" }}>
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          width="100%"
          role="img"
          aria-labelledby={titleId}
          style={{ maxWidth: SIZE, display: "block", margin: "0 auto" }}
        >
          <title id={titleId}>
            Skill strength across {dimensions.length} dimensions
            {target ? `, compared with ${target.label}` : ""}
          </title>

          {/* Recessive chrome: solid hairlines, never dashed. */}
          {RINGS.map((ring) => (
            <circle
              key={ring}
              cx={CENTRE.x}
              cy={CENTRE.y}
              r={(RADIUS * ring) / 100}
              fill="none"
              stroke="var(--gridline)"
              strokeWidth="1"
            />
          ))}
          {dimensions.map((dimension, index) => {
            const edge = radarPoint(
              100,
              index,
              dimensions.length,
              RADIUS,
              CENTRE,
            );
            return (
              <line
                key={dimension.key}
                x1={CENTRE.x}
                y1={CENTRE.y}
                x2={edge.x}
                y2={edge.y}
                stroke="var(--gridline)"
                strokeWidth="1"
              />
            );
          })}

          {targetScores && (
            <polygon
              points={radarPolygon(targetScores, RADIUS, CENTRE)}
              fill="none"
              stroke="var(--series-2)"
              strokeWidth="2.5"
              strokeDasharray="7 5"
              strokeLinejoin="round"
            />
          )}

          <polygon
            points={radarPolygon(scores, RADIUS, CENTRE)}
            fill="var(--series-1-fill)"
            stroke="var(--series-1)"
            strokeWidth="3"
            strokeLinejoin="round"
          />

          {dimensions.map((dimension, index) => {
            const point = radarPoint(
              dimension.score,
              index,
              dimensions.length,
              RADIUS,
              CENTRE,
            );
            const label = radarPoint(
              118,
              index,
              dimensions.length,
              RADIUS,
              CENTRE,
            );
            const isSelected = dimension.key === selectedKey;
            return (
              <g key={dimension.key}>
                {/* 2px surface ring so a marker over the fill stays legible. */}
                <circle
                  cx={point.x}
                  cy={point.y}
                  r={isSelected ? 7 : 5}
                  fill="var(--series-1)"
                  stroke="var(--surface-1)"
                  strokeWidth="2"
                />
                {/* Hit target larger than the mark. */}
                <circle
                  cx={point.x}
                  cy={point.y}
                  r="16"
                  fill="transparent"
                  style={{ cursor: onSelect ? "pointer" : "default" }}
                  onMouseEnter={() => setHovered(index)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => onSelect?.(dimension.key)}
                  tabIndex={0}
                  role="button"
                  aria-label={`${dimension.name}, scored ${dimension.score} out of 100`}
                  onFocus={() => setHovered(index)}
                  onBlur={() => setHovered(null)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect?.(dimension.key);
                    }
                  }}
                />
                <text
                  x={label.x}
                  y={label.y}
                  textAnchor={anchorFor(label.x)}
                  dominantBaseline="middle"
                  fontSize="12"
                  fill="var(--text-secondary)"
                  fontWeight={isSelected ? 700 : 400}
                >
                  {dimension.shortName || dimension.name}
                </text>
              </g>
            );
          })}
        </svg>

        {active && (
          <div className="tooltip" style={{ left: 12, top: 12 }}>
            <strong>{active.name}</strong>
            <div className="secondary">
              {active.score}/100 · confidence{" "}
              {(active.confidence * 100).toFixed(0)}%
            </div>
            <div className="muted" style={{ marginTop: 4 }}>
              {active.read}
            </div>
          </div>
        )}
      </div>

      {target && (
        <div
          className="legend"
          style={{ justifyContent: "center", marginTop: 8 }}
        >
          <span className="legend-item">
            <span
              className="legend-swatch"
              style={{ background: "var(--series-1)" }}
              aria-hidden="true"
            />
            You
          </span>
          <span className="legend-item">
            {/* Dashed like its line, so the pair never relies on colour. */}
            <svg width="16" height="4" aria-hidden="true">
              <line
                x1="0"
                y1="2"
                x2="16"
                y2="2"
                stroke="var(--series-2)"
                strokeWidth="2.5"
                strokeDasharray="5 3"
              />
            </svg>
            {target.label} expects
          </span>
        </div>
      )}

      {/* A table view, so nothing is readable only by colour or hover. */}
      <details style={{ marginTop: 16 }}>
        <summary className="secondary" style={{ cursor: "pointer" }}>
          View as a table
        </summary>
        <table className="data-table" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Dimension</th>
              <th>Score</th>
              <th>Confidence</th>
              {target && <th>{target.label} expects</th>}
            </tr>
          </thead>
          <tbody>
            {dimensions.map((dimension) => (
              <tr key={dimension.key}>
                <td>{dimension.name}</td>
                <td>{dimension.score}</td>
                <td>{(dimension.confidence * 100).toFixed(0)}%</td>
                {target && <td>{target.scores[dimension.key] ?? "—"}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

function anchorFor(x: number): "start" | "middle" | "end" {
  if (x > CENTRE.x + 8) return "start";
  if (x < CENTRE.x - 8) return "end";
  return "middle";
}
