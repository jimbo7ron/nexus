from __future__ import annotations

from tools.summarizer import Summarizer


def test_summarizer_parse_output():
    raw = """TL;DR: Video about race prep and training.
Takeaways:
- Preparation is key for success
- Mental strength matters
- Nerves are normal
Quotes:
- "It's hard to put into words"
- "Not even close"
Topics: cycling, racing, training"""
    
    s = Summarizer({"provider": "openai", "model": "gpt-4o-mini"})
    parsed = s._parse_llm_output(raw)
    
    assert "race prep" in parsed.tldr.lower()
    assert len(parsed.takeaways) == 3
    assert "Preparation is key for success" in parsed.takeaways
    assert len(parsed.key_quotes) == 2
    assert "cycling" in parsed.topics
    assert len(parsed.topics) == 3


def test_summarizer_parse_minimal():
    raw = """TL;DR: A simple summary.
Takeaways:
- One takeaway
Topics: test"""
    
    s = Summarizer({"provider": "openai", "model": "gpt-4o-mini"})
    parsed = s._parse_llm_output(raw)
    
    assert parsed.tldr == "A simple summary."
    assert len(parsed.takeaways) == 1
    assert len(parsed.topics) == 1


def test_summarizer_parse_empty():
    raw = ""
    
    s = Summarizer({"provider": "openai", "model": "gpt-4o-mini"})
    parsed = s._parse_llm_output(raw)
    
    assert parsed.tldr == "No summary generated"
    assert parsed.takeaways == ["No takeaways extracted"]


def test_chunk_text():
    s = Summarizer({"provider": "openai", "model": "gpt-4o-mini", "chunk_size": 10})
    text = " ".join(["word"] * 100)
    chunks = s._chunk_text(text)
    
    # Expect multiple chunks for 100 words with chunk_size=10 tokens (~7.5 words)
    assert len(chunks) > 1

