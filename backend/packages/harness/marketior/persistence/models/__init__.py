"""ORM model registration entry point.

Importing this module ensures all ORM models are registered with
``Base.metadata`` so Alembic autogenerate detects every table.

The actual ORM classes have moved to entity-specific subpackages:
- ``marketior.persistence.thread_meta``
- ``marketior.persistence.run``
- ``marketior.persistence.feedback``
- ``marketior.persistence.user``

``RunEventRow`` remains in ``marketior.persistence.models.run_event`` because
its storage implementation lives in ``marketior.runtime.events.store.db`` and
there is no matching entity directory.
"""

from marketior.persistence.feedback.model import FeedbackRow
from marketior.persistence.models.run_event import RunEventRow
from marketior.persistence.run.model import RunRow
from marketior.persistence.thread_meta.model import ThreadMetaRow
from marketior.persistence.user.model import UserRow
from marketior.persistence.project.model import ProjectRow, ProjectFileRow
from marketior.persistence.artifact.model import ArtifactRow, ArtifactVersionRow
from marketior.persistence.automation.model import AutomationRow

__all__ = ["FeedbackRow", "RunEventRow", "RunRow", "ThreadMetaRow", "UserRow", "ProjectRow", "ProjectFileRow", "ArtifactRow", "ArtifactVersionRow", "AutomationRow"]
