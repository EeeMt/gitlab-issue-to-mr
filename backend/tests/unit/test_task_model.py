import unittest

from sqlalchemy import Boolean

from app.models import Task


class TestTaskRequireChanges(unittest.TestCase):
    def test_require_changes_column_exists_not_nullable_default_true(self):
        col = Task.__table__.c.require_changes

        self.assertIsInstance(col.type, Boolean)
        self.assertFalse(col.nullable)

