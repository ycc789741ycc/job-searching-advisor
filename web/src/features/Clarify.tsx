import { useState } from "react";
import { api } from "../api/client";
import type { Question } from "../api/types";
import { Button, EmptyState, ErrorNote, Loading } from "../components/ui";
import { messageOf, useAsync } from "./useAsync";

/**
 * Follow-up questions.
 *
 * These appear when a dimension's confidence is below the threshold — the
 * domain's definition of "the context is not enough". Each says why it is being
 * asked and what it moves, and an answer becomes evidence like any other.
 */
export function Clarify() {
  const questions = useAsync<Question[]>(() => api.get("/questions"), []);
  const [answering, setAnswering] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answered, setAnswered] = useState(0);

  async function answer(id: string, value: string) {
    setAnswering(id);
    setError(null);
    try {
      await api.post(`/questions/${id}/answer`, { answer: value });
      setAnswered((count) => count + 1);
      await questions.reload();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setAnswering(null);
    }
  }

  return (
    <section>
      <h1>A few things the evidence didn&apos;t settle</h1>
      <p className="secondary" style={{ maxWidth: 620 }}>
        Each of these moves a score we are currently unsure about. Answering
        re-runs the analysis on your model.
      </p>
      <ErrorNote error={error} />
      {answered > 0 && (
        <p style={{ color: "var(--status-good)", fontSize: 13.5 }}>
          <span aria-hidden="true">✓</span> {answered} answered — your analysis
          is re-running.
        </p>
      )}

      {questions.loading ? (
        <Loading what="questions" />
      ) : (questions.data ?? []).length === 0 ? (
        <EmptyState title="Nothing to clarify">
          Either the evidence was clear enough, or you haven&apos;t run an
          analysis yet.
        </EmptyState>
      ) : (
        <div style={{ display: "grid", gap: 12, marginTop: 16, maxWidth: 680 }}>
          {(questions.data ?? []).map((question, index) => (
            <div key={question.id} className="card">
              <div className="muted" style={{ fontSize: 12.5 }}>
                Q{index + 1}
              </div>
              <h3 style={{ margin: "2px 0 6px" }}>{question.text}</h3>
              <p className="muted" style={{ fontSize: 13, margin: "0 0 12px" }}>
                {question.why}
              </p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {question.options.map((option) => (
                  <Button
                    key={option}
                    variant="secondary"
                    busy={answering === question.id}
                    onClick={() => answer(question.id, option)}
                  >
                    {option}
                  </Button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
