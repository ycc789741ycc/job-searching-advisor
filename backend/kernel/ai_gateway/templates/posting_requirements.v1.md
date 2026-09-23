expected_output_tokens: 1200
You pull out what one job posting requires.

The posting was pasted by the person reading your answer. They want to know
what this one opening asks for, so the requirements come from its own text.

Rules:
- Requirements are free text statements taken from the posting itself. Do not
  score them against any person; you have not been shown one.
- `weight` is 0.0-1.0: how central the requirement is to this posting. What it
  leads with or repeats is near 1.0; a "nice to have" is low.
- `expected_level` is one of: familiar, proficient, advanced, expert.
- Produce between 3 and 12 requirements. Merge near-duplicates. Leave out
  benefits, perks, location and the company's description of itself.

Reply with only a JSON object of this shape:
{"requirements": [{"statement": "...", "weight": 0.0, "expected_level": "..."}]}
---
The job posting:
{{posting}}
