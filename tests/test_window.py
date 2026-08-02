from datetime import date

from report_pipeline.window import Window


class TestWindow:
    def test_day(self):
        window = Window.day(date(2031, 4, 15))
        assert window.start == window.end == date(2031, 4, 15)

    def test_week_starts_monday(self):
        window = Window.week(date(2031, 4, 16))  # a Wednesday
        assert window.start.weekday() == 0
        assert (window.end - window.start).days == 6

    def test_month_covers_full_month(self):
        window = Window.month(date(2031, 4, 16))
        assert window.start == date(2031, 4, 1)
        assert window.end == date(2031, 4, 30)

    def test_february_leap_year(self):
        window = Window.month(date(2032, 2, 10))  # 2032 is a leap year
        assert window.end == date(2032, 2, 29)

    def test_prior_period_same_length(self):
        window = Window(start=date(2031, 4, 8), end=date(2031, 4, 14))  # 7 days
        prior = window.prior_period
        assert (prior.end - prior.start).days == 6
        assert prior.end == date(2031, 4, 7)
        assert prior.start == date(2031, 4, 1)

    def test_days_list(self):
        window = Window(start=date(2031, 4, 1), end=date(2031, 4, 3))
        assert window.days() == [date(2031, 4, 1), date(2031, 4, 2), date(2031, 4, 3)]

    def test_label_single_day_vs_range(self):
        assert Window.day(date(2031, 4, 1)).label() == "2031-04-01"
        assert Window(date(2031, 4, 1), date(2031, 4, 3)).label() == "2031-04-01..2031-04-03"
