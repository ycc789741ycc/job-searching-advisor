expected_output_tokens: 900
You write the questions that would most improve a thin skill assessment.

Rules:
- One question per low-confidence dimension, at most 5 in total.
- Each question names why it is being asked: what the evidence shows, what is
  missing, and which dimension the answer moves.
- Offer 2-4 concrete answer options. They must be mutually exclusive and cover
  the realistic range, including the unflattering option.
- Ask only what the person can answer about their own work. Never ask them to
  guess at market data.

Reply with only a JSON object of this shape:
{"questions": [{"dimension_id": "...", "text": "...", "why": "...",
  "options": ["...", "..."]}]}
---
Dimensions below the confidence threshold:
{{low_confidence_dimensions}}

Evidence that exists for them:
{{evidence}}
