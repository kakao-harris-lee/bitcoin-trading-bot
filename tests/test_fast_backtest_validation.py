from scripts.fast_backtest_validation import (
    classify_result,
    parse_period,
    render_table,
    ValidationRow,
)


def test_parse_period_uses_next_day_for_backtest_end():
    start, display_end, backtest_end = parse_period("2026-02-17:2026-05-08")

    assert start == "2026-02-17"
    assert display_end == "2026-05-08"
    assert backtest_end == "2026-05-09"


def test_classify_result_fails_large_underperformance():
    status, reasons = classify_result(
        result={
            "total_return_pct": -1.0,
            "max_drawdown_pct": -6.0,
            "total_trades": 10,
            "profit_factor": 0.9,
            "sharpe_ratio": -0.1,
        },
        benchmark_return_pct=16.0,
        min_trades=3,
        max_underperform_pct=5.0,
        max_drawdown_pct=25.0,
    )

    assert status == "FAIL"
    assert any("alpha" in reason for reason in reasons)


def test_classify_result_warns_low_profit_factor():
    status, reasons = classify_result(
        result={
            "total_return_pct": 1.0,
            "max_drawdown_pct": -3.0,
            "total_trades": 10,
            "profit_factor": 0.9,
            "sharpe_ratio": 0.1,
        },
        benchmark_return_pct=0.0,
        min_trades=3,
        max_underperform_pct=5.0,
        max_drawdown_pct=25.0,
    )

    assert status == "WARN"
    assert reasons == ["PF 0.90 < 1.00"]


def test_classify_result_warns_low_trade_count_when_return_gates_pass():
    status, reasons = classify_result(
        result={
            "total_return_pct": 1.0,
            "max_drawdown_pct": -3.0,
            "total_trades": 1,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.1,
        },
        benchmark_return_pct=0.0,
        min_trades=3,
        max_underperform_pct=5.0,
        max_drawdown_pct=25.0,
    )

    assert status == "WARN"
    assert reasons == ["trades 1 < 3"]


def test_render_table_contains_strategy_and_status():
    table = render_table(
        [
            ValidationRow(
                strategy="llm_direction_btc",
                symbol="BTC",
                start_date="2026-01-01",
                end_date="2026-05-08",
                backtest_end_date="2026-05-09",
                latest_bar="2026-05-08 08:00:00",
                total_return_pct=1.0,
                benchmark_return_pct=2.0,
                alpha_pct=-1.0,
                max_drawdown_pct=-3.0,
                sharpe_ratio=0.2,
                profit_factor=1.1,
                win_rate=55.0,
                total_trades=5,
                final_capital=10100.0,
                status="PASS",
                status_reasons=["meets fast validation gates"],
            )
        ]
    )

    assert "llm_direction_btc" in table
    assert "PASS" in table
