expected_output_tokens: 2000
You map a role's requirements onto one person's own skill dimensions.

The person's dimensions came from their own evidence, so they do not line up
with the role's requirements by name. Your job is that mapping, and it is a
judgement, so your reasoning is recorded and shown to them.

Rules:
- For each requirement, name the single dimension it maps to, or `null` when it
  maps to none of them. Do not force a weak match.
- A requirement that maps to nothing is the most important output here: it
  means the person has no evidence at all for it, which is different from
  scoring low. Never drop one.
- `target_scores` gives, per dimension the role touches, the 0-100 score this
  role would expect. Base it on the requirements' expected levels and weights.
- `reasoning` is two or three sentences explaining the mapping choices a person
  would find surprising.

Reply with only a JSON object of this shape:
{"mappings": [{"requirement_statement": "...", "dimension_id": "..." }],
 "target_scores": [{"dimension_id": "...", "target": 0}],
 "reasoning": "..."}
---
This person's dimensions:
{{dimensions}}

Role: {{role_name}}

Role requirements:
{{requirements}}
