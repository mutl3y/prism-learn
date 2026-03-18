"""Compatibility facade for learning-loop reporting helpers.

The implementation has been split into focused modules to reduce coupling while
preserving the public import surface.
"""

from .reporting_batch import fetch_fresh_targets
from .reporting_batch import fetch_recent_batch_summary, fetch_recent_failures
from .reporting_feedback import fetch_section_feedback_ranking
from .reporting_feedback import submit_section_feedback
from .reporting_quality import fetch_doc_quality_report
from .reporting_sections import fetch_section_title_report

__all__ = [
    "fetch_recent_batch_summary",
    "fetch_recent_failures",
    "fetch_fresh_targets",
    "fetch_section_title_report",
    "fetch_doc_quality_report",
    "submit_section_feedback",
    "fetch_section_feedback_ranking",
]
