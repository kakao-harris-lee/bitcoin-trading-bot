from trading.risk.risk_controls import clamp_fraction, should_block_new_entries


def test_clamp_fraction_respects_cap():
    assert clamp_fraction(0.8, 0.5) == 0.5
    assert clamp_fraction(0.2, 0.5) == 0.2
    assert clamp_fraction(1.5, 0.5) == 0.5
    assert clamp_fraction(-1.0, 0.5) == 0.0


def test_daily_loss_guard_blocks_when_breached():
    blocked, ret = should_block_new_entries(daily_max_loss_pct=2.0, day_start_total=100.0, current_total=97.0)
    assert blocked is True
    assert ret == -3.0


def test_daily_loss_guard_disabled_when_zero():
    blocked, ret = should_block_new_entries(daily_max_loss_pct=0.0, day_start_total=100.0, current_total=1.0)
    assert blocked is False
    assert ret is None
