"""Feedback persistence — ORM and SQL repository."""

from marketior.persistence.feedback.model import FeedbackRow
from marketior.persistence.feedback.sql import FeedbackRepository

__all__ = ["FeedbackRepository", "FeedbackRow"]
