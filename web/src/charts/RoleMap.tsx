import { useId, useMemo, useState } from "react";
import { bubbleRadius, linearScale, paddedDomain, ticks } from "./geometry";

export interface RoleBubble {
  id: string;
  name: string;
  hiringBar: number;
  barBasis: string;
  salaryMid: number | null;
  salaryLabel: string | null;
  openings: number;
  fit: number | null;
  reasoning: string | null;
}

interface Props {
  roles: RoleBubble[];
  selectedId?: string | undefined;
  onSelect?: ((id: string) => void) | undefined;
}

const WIDTH = 720;
const HEIGHT = 440;
const MARGIN = { top: 24, right: 40, bottom: 52, left: 72 };

/**
 * The role map.
 *
 * X is the hiring bar, Y is salary, bubble size is fit — and fit belongs to the
 * User x Role pair, not to the role, which is why it arrives separately.
 *
 * Every bubble is the same kind of thing, so they share one hue and identity is
 * carried by direct labels. A bar that is only an AI estimate gets a dashed
 * outline: a second, non-colour channel, since "we guessed this" must survive a
 * greyscale print and a colour-blind reader.
 */
export function RoleMap({ roles, selectedId, onSelect }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);
  const titleId = useId();

  const plotted = useMemo(
    () => roles.filter((role) => role.salaryMid !== null),
    [roles],
  );

  const { xScale, yScale, xDomain, yDomain } = useMemo(() => {
    const xd = paddedDomain(plotted.map((r) => r.hiringBar));
    const yd = paddedDomain(plotted.map((r) => r.salaryMid ?? 0));
    return {
      xDomain: xd,
      yDomain: yd,
      xScale: linearScale(xd, [MARGIN.left, WIDTH - MARGIN.right]),
      yScale: linearScale(yd, [HEIGHT - MARGIN.bottom, MARGIN.top]),
    };
  }, [plotted]);

  if (roles.length === 0) {
    return (
      <p className="muted">
        No roles yet. Watch a company or choose a market, then build your role
        map.
      </p>
    );
  }

  const withoutSalary = roles.length - plotted.length;
  const active = plotted.find((role) => role.id === hovered) ?? null;
  // Label only the largest bubbles; a name on every mark collides and goes unread.
  const labelled = new Set(
    [...plotted]
      .sort((a, b) => (b.fit ?? 0) - (a.fit ?? 0))
      .slice(0, 5)
      .map((role) => role.id),
  );

  return (
    <div>
      <div style={{ position: "relative" }}>
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          width="100%"
          role="img"
          aria-labelledby={titleId}
          style={{ display: "block" }}
        >
          <title id={titleId}>
            {plotted.length} roles plotted by interview difficulty and salary,
            sized by how well they fit you
          </title>

          {ticks(yDomain, 5).map((value) => (
            <g key={`y-${value}`}>
              <line
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={yScale(value)}
                y2={yScale(value)}
                stroke="var(--gridline)"
                strokeWidth="1"
              />
              <text
                x={MARGIN.left - 10}
                y={yScale(value)}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize="11"
                fill="var(--text-muted)"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {compactMoney(value)}
              </text>
            </g>
          ))}

          {ticks(xDomain, 5).map((value) => (
            <text
              key={`x-${value}`}
              x={xScale(value)}
              y={HEIGHT - MARGIN.bottom + 18}
              textAnchor="middle"
              fontSize="11"
              fill="var(--text-muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {value.toFixed(0)}
            </text>
          ))}

          <line
            x1={MARGIN.left}
            x2={WIDTH - MARGIN.right}
            y1={HEIGHT - MARGIN.bottom}
            y2={HEIGHT - MARGIN.bottom}
            stroke="var(--axis)"
            strokeWidth="1"
          />
          <text
            x={(MARGIN.left + WIDTH - MARGIN.right) / 2}
            y={HEIGHT - 12}
            textAnchor="middle"
            fontSize="12"
            fill="var(--text-secondary)"
          >
            Hiring bar — how hard the interview is
          </text>
          <text
            transform={`translate(16 ${HEIGHT / 2}) rotate(-90)`}
            textAnchor="middle"
            fontSize="12"
            fill="var(--text-secondary)"
          >
            Salary, midpoint of the band
          </text>

          {plotted
            .slice()
            .sort((a, b) => (b.fit ?? 0) - (a.fit ?? 0))
            .map((role) => {
              const cx = xScale(role.hiringBar);
              const cy = yScale(role.salaryMid ?? 0);
              const r = bubbleRadius(role.fit ?? 0);
              const isEstimate = role.barBasis === "estimated";
              const isSelected = role.id === selectedId;
              return (
                <g key={role.id}>
                  <circle
                    cx={cx}
                    cy={cy}
                    r={r}
                    fill="var(--series-1)"
                    fillOpacity={isSelected ? 0.4 : 0.22}
                    stroke="var(--series-1)"
                    strokeWidth={isSelected ? 3 : 2}
                    strokeDasharray={isEstimate ? "5 4" : undefined}
                  />
                  {/* 2px surface ring keeps overlapping bubbles separable. */}
                  <circle
                    cx={cx}
                    cy={cy}
                    r={r + 1}
                    fill="none"
                    stroke="var(--surface-1)"
                    strokeWidth="2"
                    strokeOpacity="0.5"
                  />
                  <circle
                    cx={cx}
                    cy={cy}
                    r={Math.max(r, 18)}
                    fill="transparent"
                    style={{ cursor: "pointer" }}
                    onMouseEnter={() => setHovered(role.id)}
                    onMouseLeave={() => setHovered(null)}
                    onClick={() => onSelect?.(role.id)}
                    tabIndex={0}
                    role="button"
                    aria-label={ariaFor(role)}
                    onFocus={() => setHovered(role.id)}
                    onBlur={() => setHovered(null)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelect?.(role.id);
                      }
                    }}
                  />
                  {labelled.has(role.id) && (
                    <text
                      x={cx}
                      y={cy - r - 7}
                      textAnchor="middle"
                      fontSize="12"
                      fill="var(--text-secondary)"
                    >
                      {role.name}
                    </text>
                  )}
                </g>
              );
            })}
        </svg>

        {active && (
          <div className="tooltip" style={{ right: 12, top: 12 }}>
            <strong>{active.name}</strong>
            <div className="secondary">
              Fit {active.fit ?? "—"} · hiring bar {active.hiringBar}
              {active.barBasis === "estimated" ? " (estimated)" : ""}
            </div>
            <div className="secondary">
              {active.salaryLabel ?? "no published pay"} · {active.openings}{" "}
              openings
            </div>
            {active.reasoning && (
              <div className="muted" style={{ marginTop: 4 }}>
                {active.reasoning}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="legend" style={{ marginTop: 8 }}>
        <span className="legend-item">
          <svg width="26" height="14" aria-hidden="true">
            <circle
              cx="13"
              cy="7"
              r="6"
              fill="var(--series-1)"
              fillOpacity="0.22"
              stroke="var(--series-1)"
              strokeWidth="2"
            />
          </svg>
          Difficulty from real reports
        </span>
        <span className="legend-item">
          <svg width="26" height="14" aria-hidden="true">
            <circle
              cx="13"
              cy="7"
              r="6"
              fill="var(--series-1)"
              fillOpacity="0.22"
              stroke="var(--series-1)"
              strokeWidth="2"
              strokeDasharray="4 3"
            />
          </svg>
          Difficulty estimated from the postings
        </span>
        <span className="legend-item">
          Bubble size is how well the role fits you
        </span>
      </div>

      {withoutSalary > 0 && (
        <p className="muted" style={{ fontSize: 13 }}>
          {withoutSalary} role{withoutSalary === 1 ? "" : "s"} had no published
          pay in your markets, so {withoutSalary === 1 ? "it is" : "they are"}{" "}
          listed in the table below rather than plotted.
        </p>
      )}

      <details style={{ marginTop: 12 }}>
        <summary className="secondary" style={{ cursor: "pointer" }}>
          View as a table
        </summary>
        <table className="data-table" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Role</th>
              <th>Fit</th>
              <th>Hiring bar</th>
              <th>Basis</th>
              <th>Salary</th>
              <th>Openings</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role.id}>
                <td>{role.name}</td>
                <td>{role.fit ?? "—"}</td>
                <td>{role.hiringBar}</td>
                <td>{role.barBasis}</td>
                <td>{role.salaryLabel ?? "—"}</td>
                <td>{role.openings}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

function ariaFor(role: RoleBubble): string {
  return (
    `${role.name}: fit ${role.fit ?? "not scored"}, hiring bar ${role.hiringBar}` +
    `${role.barBasis === "estimated" ? " estimated" : ""}` +
    `${role.salaryLabel ? `, ${role.salaryLabel}` : ""}`
  );
}

function compactMoney(value: number): string {
  if (Math.abs(value) >= 1000) return `${Math.round(value / 1000)}k`;
  return Math.round(value).toString();
}
