import { useState } from "react";
import { api } from "../api/client";
import type { Assessment, Question } from "../api/types";
import {
  AutoGrid,
  Button,
  Done,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  PillToggle,
} from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { messageOf, useAsync } from "./useAsync";

/**
 * Follow-up questions.
 *
 * These appear when a dimension's confidence is below the threshold — the
 * domain's definition of "the context is not enough". Each says why it is being
 * asked and what it moves, and an answer becomes evidence like any other.
 */
export function Clarify() {
  const { status, navigate, refresh } = useShell();
  const questions = useAsync<Question[]>(() => api.get("/questions"), []);
  const assessment = useAsync<Assessment | null>(
    () => api.get("/assessments/latest"),
    [],
  );
  const [answering, setAnswering] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answered, setAnswered] = useState(0);

  async function answer(id: string, value: string) {
    setAnswering(id);
    setError(null);
    try {
      await api.post(`/questions/${id}/answer`, { answer: value });
      setAnswered((count) => count + 1);
      await Promise.all([questions.reload(), refresh()]);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setAnswering(null);
    }
  }

  const open = (questions.data ?? []).filter((q) => q.answer === null);
  const dimensions = new Map(
    (assessment.data?.dimensions ?? []).map((d) => [d.key, d]),
  );
  const moved = [...new Set(open.map((q) => q.dimension_key))]
    .map((key) => dimensions.get(key))
    .filter((d) => d !== undefined);

  return (
    <AutoGrid col={340}>
      <div>
        <span className="model-pill">
          Written by {modelName(status.credential)} after reading your profile
        </span>
        <p className="lead" style={{ marginTop: 14 }}>
          Things the data couldn&apos;t settle on its own. Answer what you can —
          each one sharpens the skill report and the salary band underneath it,
          and re-runs the analysis on your model.
        </p>
        <ErrorNote error={error} />
        {answered > 0 && (
          <Done>{answered} answered — your analysis is re-running.</Done>
        )}

        {questions.loading ? (
          <Loading what="questions" />
        ) : open.length === 0 ? (
          <EmptyState title="Nothing to clarify">
            Either the evidence was clear enough, or you haven&apos;t run an
            analysis yet.
          </EmptyState>
        ) : (
          open.map((question, index) => (
            <div
              key={question.id}
              className="panel panel-tight"
              style={{ marginTop: 14 }}
            >
              <div style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
                <span
                  style={{
                    fontFamily: "var(--font-heading)",
                    color: "var(--color-accent-700)",
                    fontSize: 14,
                  }}
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <div className="card-title">{question.text}</div>
                  <div className="subcopy" style={{ marginTop: 6 }}>
                    Asked because: {question.why}
                  </div>
                </div>
              </div>
              <div className="row" style={{ gap: 8, marginTop: 14 }}>
                {question.options.map((option) => (
                  <PillToggle
                    key={option}
                    pressed={false}
                    disabled={answering === question.id}
                    onClick={() => void answer(question.id, option)}
                  >
                    {option}
                  </PillToggle>
                ))}
              </div>
            </div>
          ))
        )}

        <div className="row" style={{ marginTop: 20 }}>
          <Button onClick={() => navigate("strengths")}>
            See my skill report
          </Button>
          {open.length > 0 && (
            <Button variant="ghost" onClick={() => navigate("strengths")}>
              Skip for now
            </Button>
          )}
        </div>
      </div>

      <div className="panel">
        <Eyebrow style={{ marginBottom: 4 }}>What your answers sharpen</Eyebrow>
        {moved.length === 0 ? (
          <p className="subcopy" style={{ marginTop: 10, marginBottom: 0 }}>
            No open questions, so every score stands on the evidence alone.
          </p>
        ) : (
          <div className="divided">
            {moved.map((dimension) => (
              <div key={dimension.key}>
                <div
                  className="row-between"
                  style={{ fontSize: 14, fontWeight: 600 }}
                >
                  <span>{dimension.name}</span>
                  <span style={{ color: "var(--color-accent-700)" }}>
                    {Math.round(dimension.confidence * 100)}% sure
                  </span>
                </div>
                <div
                  className="subcopy"
                  style={{ fontSize: 12.5, marginTop: 4 }}
                >
                  Scored {dimension.score}/100 on thin evidence — an answer
                  firms this up.
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AutoGrid>
  );
}
