from __future__ import annotations

import os
from typing import Dict, List, Any

from pydantic import BaseModel


class SummaryOutput(BaseModel):
    tldr: str
    takeaways: List[str]
    key_quotes: List[str]
    topics: List[str]


class Summarizer:
    def __init__(self, config: Dict[str, Any]):
        self.provider = config.get("provider", "openai")
        self.model = config.get("model", "gpt-4o-mini")
        self.max_tokens = config.get("max_tokens", 1000)
        self.temperature = config.get("temperature", 0.3)
        self.chunk_size = config.get("chunk_size", 8000)
        self.api_key_env = config.get("api_key_env", "OPENAI_API_KEY")

        self.client = None
        if self.provider == "openai":
            api_key = os.getenv(self.api_key_env)
            if api_key:
                from openai import AsyncOpenAI
                self.client = AsyncOpenAI(api_key=api_key)

    async def close(self):
        """Close the OpenAI client and cleanup resources."""
        if self.client:
            await self.client.close()

    async def summarize_video(self, title: str, channel: str | None, transcript: str) -> SummaryOutput:
        chunks = self._chunk_text(transcript)
        if len(chunks) == 1:
            return await self._summarize_single(title, channel or "Unknown", transcript, "video")
        else:
            return await self._summarize_long(title, channel or "Unknown", chunks, "video")

    async def summarize_article(self, title: str, site: str | None, text: str) -> SummaryOutput:
        chunks = self._chunk_text(text)
        if len(chunks) == 1:
            return await self._summarize_single(title, site or "Unknown", text, "article")
        else:
            return await self._summarize_long(title, site or "Unknown", chunks, "article")

    def _chunk_text(self, text: str) -> List[str]:
        # Simple word-based chunking (rough approximation)
        words = text.split()
        words_per_chunk = int(self.chunk_size * 0.75)
        chunks = []
        for i in range(0, len(words), words_per_chunk):
            chunks.append(" ".join(words[i : i + words_per_chunk]))
        return chunks if chunks else [text]

    async def _summarize_single(self, title: str, source: str, text: str, content_type: str) -> SummaryOutput:
        if not self.client:
            raise Exception(f"LLM client not initialized; set {self.api_key_env} environment variable")

        prompt = self._build_prompt(title, source, text, content_type)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates concise, structured summaries."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            timeout=60.0,
        )
        raw = response.choices[0].message.content
        return self._parse_llm_output(raw)

    async def _summarize_long(self, title: str, source: str, chunks: List[str], content_type: str) -> SummaryOutput:
        if not self.client:
            raise Exception(f"LLM client not initialized; set {self.api_key_env} environment variable")

        # Map: summarize each chunk
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            prompt = f"Summarize this excerpt (part {i + 1}/{len(chunks)}) from '{title}':\n\n{chunk}"
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                timeout=60.0,
            )
            chunk_summaries.append(resp.choices[0].message.content)

        # Reduce: combine chunk summaries into final
        combined = "\n\n".join(chunk_summaries)
        final_prompt = f"""Synthesize these summaries of '{title}' from {source} into a final structured summary.

Summaries:
{combined}

Return in this exact format:
TL;DR: ...
Takeaways:
- ...
- ...
Quotes:
- ...
Topics: tag1, tag2, tag3
"""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": final_prompt}],
            max_tokens=self.max_tokens,
            timeout=60.0,
        )
        return self._parse_llm_output(response.choices[0].message.content)

    def _build_prompt(self, title: str, source: str, text: str, content_type: str) -> str:
        return f"""Title: {title}
Source: {source}

Summarize the following {content_type} into a structured format:
1. TL;DR (2-3 sentences)
2. Key Takeaways (5-8 bullet points)
3. Notable Quotes or Facts (2-3 items)
4. Topics (3-5 tags)

Content:
{text}

Return in this exact format:
TL;DR: ...
Takeaways:
- ...
- ...
Quotes:
- ...
Topics: tag1, tag2, tag3
"""

    def _parse_llm_output(self, raw: str) -> SummaryOutput:
        lines = raw.strip().split("\n")
        tldr = ""
        takeaways = []
        quotes = []
        topics = []

        current_section = None
        for line in lines:
            line = line.strip()
            # Remove markdown bold formatting (** prefix/suffix)
            line_clean = line.replace("**", "")

            if "TL;DR:" in line_clean.upper() or "TLDR:" in line_clean.upper():
                # Extract TL;DR text after the colon
                if ":" in line_clean:
                    tldr = line_clean.split(":", 1)[-1].strip()
                current_section = None
            elif "TAKEAWAYS:" in line_clean.upper() or "KEY TAKEAWAYS:" in line_clean.upper():
                current_section = "takeaways"
            elif "QUOTES:" in line_clean.upper() or "NOTABLE" in line_clean.upper():
                current_section = "quotes"
            elif "TOPICS:" in line_clean.upper():
                topics_str = line_clean.split(":", 1)[-1].strip()
                topics = [t.strip() for t in topics_str.split(",") if t.strip()]
                current_section = None
            elif line.startswith("-") or line.startswith("•") or line.startswith("*"):
                item = line.lstrip("-•*").strip()
                if current_section == "takeaways" and item:
                    takeaways.append(item)
                elif current_section == "quotes" and item:
                    quotes.append(item)

        return SummaryOutput(
            tldr=tldr or "No summary generated",
            takeaways=takeaways if takeaways else ["No takeaways extracted"],
            key_quotes=quotes if quotes else [],
            topics=topics if topics else [],
        )
