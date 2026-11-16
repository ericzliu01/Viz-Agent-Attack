"""Tests for the SQL ground-truth consistency checker (Task 2)."""
import pandas as pd
import pytest

from pipeline.sql_check import (
    UnsafeSQL,
    UnsolvableTask,
    check_answer,
    run_sql,
)

titanic_df = pd.read_csv("datasets/titanic.csv")


def test_run_sql_scalar_mean_fare():
    out = run_sql("SELECT ROUND(AVG(fare),2) FROM data", titanic_df)
    assert float(out) == pytest.approx(32.20, abs=0.01)


def test_check_answer_aligned():
    assert check_answer("136", "SELECT COUNT(*) FROM data WHERE class='First' AND survived=1", titanic_df, "free") is True


def test_check_answer_mismatch():
    assert check_answer("200", "SELECT COUNT(*) FROM data WHERE class='First' AND survived=1", titanic_df, "free") is False


def test_non_select_rejected():
    with pytest.raises(UnsafeSQL):
        run_sql("DROP TABLE data", titanic_df)


def test_multiple_statements_rejected():
    with pytest.raises(UnsafeSQL):
        run_sql("SELECT 1; SELECT 2", titanic_df)


def test_missing_column_unsolvable():
    with pytest.raises(UnsolvableTask):
        run_sql("SELECT AVG(nonexistent) FROM data", titanic_df)


def test_non_scalar_result_unsolvable():
    with pytest.raises(UnsolvableTask):
        run_sql("SELECT survived, COUNT(*) FROM data GROUP BY survived", titanic_df)
