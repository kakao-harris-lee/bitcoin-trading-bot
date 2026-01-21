"""Tests for Optuna study management."""
import pytest
import tempfile
import os
from web.quant_lab.optimizer.study_manager import StudyManager


class TestStudyManager:
    """Test study lifecycle management."""

    def test_create_study(self):
        """StudyManager should create a new study."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            study = manager.create_study("test_experiment")

            assert study is not None
            assert study.study_name == "test_experiment"

    def test_resume_study(self):
        """StudyManager should resume existing study."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            # Create initial study
            study1 = manager.create_study("resume_test")

            # Resume it
            study2 = manager.get_study("resume_test")

            assert study2.study_name == "resume_test"

    def test_list_studies(self):
        """StudyManager should list all studies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            manager.create_study("study_a")
            manager.create_study("study_b")

            studies = manager.list_studies()

            assert len(studies) >= 2
            names = [s.study_name for s in studies]
            assert "study_a" in names
            assert "study_b" in names

    def test_get_pareto_front(self):
        """StudyManager should return Pareto-optimal trials."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            study = manager.create_study("pareto_test")

            # Note: pareto front requires completed trials
            # This tests the method exists and returns empty for new study
            pareto = manager.get_pareto_front("pareto_test")

            assert isinstance(pareto, list)
