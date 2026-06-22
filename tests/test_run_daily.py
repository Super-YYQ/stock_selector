from src.run_daily import parse_args, resolve_report_date


def test_parse_args_supports_init_and_date() -> None:
    args = parse_args(["--init", "--date", "2026-06-22"])

    assert args.init is True
    assert args.date == "2026-06-22"


def test_resolve_report_date_uses_requested_date() -> None:
    assert resolve_report_date("2026-06-22", "2026-06-21") == "2026-06-22"
