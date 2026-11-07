"""Rule-based NL -> SQL fallback (used when no LLM key is configured)."""
import pandas as pd
import pytest

from app.agents.sql_agent import _rule_based_sql, run_sql


@pytest.fixture
def df():
    return pd.DataFrame({
        "customer_id": ["C1", "C2", "C3", "C4", "C5", "C6"],
        "age": [20, 30, 40, 50, 60, 70],
        "contract_type": ["Monthly", "Monthly", "Yearly", "Yearly", "Yearly", "Monthly"],
        "monthly_charges": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
        "total_charges": [100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
        "churn": ["Yes", "No", "No", "No", "Yes", "Yes"],
    })


def ask(question, df):
    return run_sql(_rule_based_sql(question, df), df)["rows"]


def test_average_does_not_match_age_column(df):
    # Regression: 'age' is a substring of 'average', which used to return AVG(age).
    rows = ask("What is the average monthly charges?", df)
    assert rows == [{"avg_monthly_charges": 35.0}]


def test_column_names_with_spaces_match_underscores(df):
    assert ask("average total charges", df) == [{"avg_total_charges": 350.0}]


def test_average_by_category_groups(df):
    rows = ask("What is the average monthly charges by contract type?", df)
    assert {r["contract_type"]: r["avg_monthly_charges"] for r in rows} == {"Monthly": 30.0, "Yearly": 40.0}


def test_metric_by_category_without_aggregation_word_sums(df):
    rows = ask("total charges per contract type", df)
    assert {r["contract_type"]: r["sum_total_charges"] for r in rows} == {"Monthly": 900.0, "Yearly": 1200.0}


def test_count_per_category(df):
    rows = ask("how many customers by churn?", df)
    assert {r["churn"]: r["count"] for r in rows} == {"Yes": 3, "No": 3}


def test_max_and_min(df):
    assert ask("highest monthly charges", df) == [{"max_monthly_charges": 60.0}]
    assert ask("lowest age", df) == [{"min_age": 20}]


def test_average_age_still_works(df):
    assert ask("average age", df) == [{"avg_age": 45.0}]


def test_first_numeric_column_suggestion(df):
    assert ask("What is the average of the first numeric column?", df) == [{"avg_age": 45.0}]


def test_top_n_by_metric(df):
    rows = ask("top 2 customers by total charges", df)
    assert [r["customer_id"] for r in rows] == ["C6", "C5"]


def test_row_count_and_preview(df):
    assert ask("How many rows are in this dataset?", df) == [{"row_count": 6}]
    assert len(ask("Show me the top 3 rows", df)) == 3


def test_does_not_group_by_high_cardinality_numeric(df):
    sql = _rule_based_sql("average age by total charges", df)
    assert "GROUP BY" not in sql


def test_column_names_with_quotes_are_escaped():
    odd = pd.DataFrame({'pri"ce': [1.0, 3.0]})
    assert run_sql(_rule_based_sql('average pri"ce', odd), odd)["rows"] == [{'avg_pri"ce': 2.0}]
