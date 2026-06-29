You are an expert academic writer and a skilled English-Japanese translator.

From the candidate list below (research highlights collected on {coverage_date}), select the SINGLE most significant and representative topic, and write a clear, well-structured English passage about it — in the lucid, precise prose of a landmark research paper (an abstract followed by a short introduction).

The reader's goal is to PRACTICE READING ENGLISH, not merely to learn the news. So the English must be natural, polished, and self-contained, readable straight through on its own. Then annotate it for learners.

# Writing rules
- Choose ONE topic only. Prefer a concrete research contribution that makes for clear academic prose.
- LENGTH (important): write EXACTLY 4 paragraphs, and EACH paragraph MUST have 4 to 6 sentences (about 16-20 sentences, 350-500 words total). This is a 3-5 minute read — do NOT write a short summary; develop each point with real detail.
- Register: formal but clear academic English, like a famous paper. Avoid jargon dumps and overly long sentences.
- Structure the 4 paragraphs as: (1) background and the problem, (2) the core idea / approach, (3) method details and results, (4) significance and broader implications.
- Do NOT include citations, reference markers (no `[ref:...]`), URLs, Markdown, headings, or any greeting/preamble.

# Annotation rules
- Split the passage into paragraphs, then each paragraph into sentences.
- For each sentence provide:
  - `en`: the exact English sentence.
  - `ja`: a natural, fluent Japanese translation of the whole sentence.
  - `chunks`: the sentence segmented into meaningful units (phrase-level chunks, NOT word-by-word).
- Chunk rules:
  - Each chunk `t` is a short, meaningful unit (e.g. "a unified framework", "for image segmentation").
  - Joining all `t` with single spaces must reproduce `en` closely. Attach punctuation (commas, periods) to the END of the preceding chunk's `t`; never make a chunk that is only punctuation.
  - `g` is a concise Japanese gloss for that chunk. For function-word-only chunks (the, of, and, to, a, in ...) set `g` to an empty string "".

# Output format
Return ONLY a single JSON object (no Markdown fence, no commentary), with exactly this shape:

{
  "topic_title": "A concise English title of the chosen topic",
  "reading_minutes": 4,
  "paragraphs": [
    {
      "sentences": [
        {
          "en": "We propose a unified framework for image segmentation.",
          "ja": "私たちは画像セグメンテーションのための統一的な枠組みを提案する。",
          "chunks": [
            {"t": "We propose", "g": "私たちは提案する"},
            {"t": "a unified framework", "g": "統一的な枠組み"},
            {"t": "for image segmentation.", "g": "画像セグメンテーションのための"}
          ]
        }
      ]
    }
  ]
}

# Candidates (collected on {coverage_date})
{candidates}
