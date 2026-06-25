from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MatchedSource:
    url: str
    similarity: float  # 0-100 percentage of match for this specific source
    matched_snippet: str = ""
    title: str = ""
    matched_words: int = 0

    def to_dict(self):
        return {
            "url": self.url,
            "similarity": self.similarity,
            "matched_snippet": self.matched_snippet,
            "title": self.title,
            "matched_words": self.matched_words,
        }


@dataclass
class CheckResult:
    score: float = 0.0  # 0-100 overall similarity/match percentage. Default to 0.0 for pending.
    matched_sources: List[MatchedSource] = field(default_factory=list)
    ai_generated_likelihood: Optional[float] = None  # 0-100, if the provider supports it
    grammar_score: Optional[float] = None # 0-100, if the provider supports it
    readability_text: str = "" # e.g. '5th Grader'
    raw_response: Optional[dict] = None
    is_pending: bool = False  # True if the provider submitted a webhook and returned instantly
    scan_id: Optional[str] = None  # Provider's scan ID, useful for matching incoming webhooks


class PlagiarismProvider:
    """Every concrete provider (Copyleaks, PlagiarismCheck.org, ...) implements this."""

    name = "base"

    def check_text(self, text: str) -> CheckResult:
        raise NotImplementedError
