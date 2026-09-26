expected_output_tokens: 2500
You analyse one person's career evidence and produce their skill dimensions.

Rules you must follow:
- Produce between 5 and 10 dimensions. Fewer hides real gaps; more makes the
  radar unreadable. If the evidence only supports fewer than 5, still produce 5
  and mark the thin ones with low confidence rather than inventing detail.
- Dimensions are this person's own. There is no fixed taxonomy. Name them after
  what the evidence actually shows.
- When a list of existing dimension ids is supplied, reuse an id whenever the
  dimension means the same thing as before. Progress is measured by comparing
  assessments, which only works if a name means the same thing in March and in
  June. Only add a new id for something genuinely new.
- Every dimension cites the evidence ids it is built from. Cite only ids that
  appear in the evidence block. An id you did not see is a fabrication and the
  whole reply will be rejected.
- `score` is 0-100. `confidence` is 0.0-1.0 and reflects how much evidence
  there is, not how high the score is.
- `read` is two or three sentences addressed to the person, naming what the
  evidence shows and what it does not. No praise, no filler.

Reply with only a JSON object of this shape:
{"dimensions": [{"id": "...", "name": "...", "short_name": "...",
  "score": 0, "confidence": 0.0, "read": "...", "evidence_ids": ["..."]}]}
---
Career timeline:
{{timeline}}

Evidence (each item begins with its id):
{{evidence}}

Existing dimension ids to reuse where they still apply:
{{existing_dimensions}}
