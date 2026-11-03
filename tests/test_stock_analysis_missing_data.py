import unittest
from datetime import date
from io import BytesIO, StringIO
from unittest.mock import patch
from zipfile import ZipFile

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from pages import stock_analysis


def sample_data(case="complete", periods=8):
    index = pd.bdate_range("2026-10-22", periods=periods, name="Date")
    changes = (-2.0, 3.0, 1.0, -4.0, 5.0, -1.0, 2.0, -3.0)
    opens = [100.0 + i for i in range(periods)]
    closes = [value + changes[i % len(changes)] for i, value in enumerate(opens)]
    df = pd.DataFrame(
        {
            "Open": opens,
            "High": [max(open_, close) + 3.0 for open_, close in zip(opens, closes)],
            "Low": [min(open_, close) - 2.0 for open_, close in zip(opens, closes)],
            "Close": closes,
            "Volume": [1000.0 + i * 100 for i in range(periods)],
        },
        index=index,
    )
    if case == "last_close_missing":
        df.loc[index[-1], "Close"] = float("nan")
    elif case == "middle_close_missing":
        df.loc[index[3], "Close"] = float("nan")
    elif case == "ohlc_row_missing":
        df.loc[index[-1], ["Open", "High", "Low", "Close"]] = float("nan")
    elif case == "all_ohlc_missing":
        df.loc[:, ["Open", "High", "Low", "Close"]] = float("nan")
    elif case == "volume_missing":
        df.loc[index[-1], "Volume"] = float("nan")
    elif case == "all_volume_missing":
        df.loc[:, "Volume"] = float("nan")
    elif case != "complete":
        raise ValueError(f"Unknown sample case: {case}")
    return df


CASES = (
    "complete",
    "last_close_missing",
    "middle_close_missing",
    "ohlc_row_missing",
    "all_ohlc_missing",
    "volume_missing",
    "all_volume_missing",
)

APP_SOURCE = """
from datetime import date
from pages import stock_analysis
stock_analysis.show(date(2026, 11, 3))
"""


class ChartTests(unittest.TestCase):
    def test_chart_cases_preserve_source(self):
        for case in CASES:
            with self.subTest(case=case):
                df = sample_data(case)
                before = df.copy(deep=True)
                expected = df.dropna(subset=["Open", "High", "Low", "Close"])
                with patch.object(stock_analysis.mpf, "plot", wraps=stock_analysis.mpf.plot) as plot:
                    image, kind = stock_analysis.create_candlestick_chart(df)
                self.assertEqual(kind, "candle")
                if expected.empty:
                    self.assertIsNone(image)
                    plot.assert_not_called()
                else:
                    self.assertTrue(image.getvalue().startswith(b"\x89PNG\r\n\x1a\n"))
                    pd.testing.assert_frame_equal(plot.call_args.args[0], expected)
                    self.assertEqual(plot.call_args.kwargs["volume"], case != "all_volume_missing")
                pd.testing.assert_frame_equal(df, before)
                self.assertEqual(plt.get_fignums(), [])

    def test_original_point_count_controls_chart_type(self):
        for periods, expected_type in ((250, "candle"), (251, "line")):
            with self.subTest(periods=periods):
                image, kind = stock_analysis.create_candlestick_chart(
                    sample_data("last_close_missing", periods)
                )
                self.assertEqual(kind, expected_type)
                self.assertIsNotNone(image)

    def test_multiindex_and_string_dates_are_not_mutated(self):
        df = sample_data("last_close_missing")
        df.columns = pd.MultiIndex.from_product([df.columns, ["TEST"]])
        df.index = df.index.strftime("%Y-%m-%d")
        before = df.copy(deep=True)
        chart = stock_analysis.prepare_chart_data(df)
        self.assertEqual(len(chart), len(df) - 1)
        self.assertIsInstance(chart.index, pd.DatetimeIndex)
        self.assertNotIsInstance(chart.columns, pd.MultiIndex)
        image, _ = stock_analysis.create_candlestick_chart(df)
        self.assertIsNotNone(image)
        pd.testing.assert_frame_equal(df, before)

    def test_column_width_with_arrow_missing_values(self):
        for values in ([102.0, float("nan")], [float("nan"), float("nan")]):
            with self.subTest(values=values):
                series = pd.Series(values, dtype="string[pyarrow]")
                width = max(series.astype("string").fillna("").str.len().max(), len("Close"))
                self.assertGreaterEqual(width, len("Close"))
                self.assertFalse(pd.isna(width))


class PageTests(unittest.TestCase):
    def test_fetch_render_download_and_rerun(self):
        for case in CASES:
            with self.subTest(case=case):
                source = sample_data(case)
                source.columns = pd.MultiIndex.from_product([source.columns, ["TEST"]])
                before = source.copy(deep=True)
                expected = sample_data(case)
                chart_expected = stock_analysis.prepare_chart_data(expected)
                with (
                    patch.object(stock_analysis, "get_stock_data", return_value=source),
                    patch.object(stock_analysis, "get_stock_name", return_value="Test Stock"),
                    patch.object(stock_analysis.st, "download_button", wraps=stock_analysis.st.download_button) as downloads,
                    patch.object(stock_analysis.st, "line_chart", wraps=stock_analysis.st.line_chart) as line_chart,
                ):
                    app = AppTest.from_string(APP_SOURCE, default_timeout=30).run()
                    app.radio[0].set_value("銘柄コードをカンマ区切りで入力").run()
                    app.text_area[0].input("TEST")
                    next(button for button in app.button if button.label == "データ取得").click().run()
                    self.assertEqual(len(app.exception), 0)
                    self.assertEqual(len(app.error), 0)
                    self.assertEqual(len(app.dataframe), 1)
                    pd.testing.assert_frame_equal(app.dataframe[0].value, expected, check_freq=False)
                    pd.testing.assert_frame_equal(app.session_state["stock_data"]["TEST"], expected)
                    pd.testing.assert_frame_equal(source, before)
                    self.assertEqual(len(app.warning), int(len(chart_expected) < len(expected)))
                    if chart_expected.empty:
                        self.assertEqual(len(app.info), 1)
                        self.assertNotIn("TEST", app.session_state["charts"])
                        line_chart.assert_not_called()
                    else:
                        self.assertIn("TEST", app.session_state["charts"])
                        pd.testing.assert_frame_equal(
                            line_chart.call_args.args[0],
                            chart_expected[["Open", "Close", "High", "Low"]],
                        )
                    payloads = {call.kwargs["key"]: call.kwargs["data"] for call in downloads.call_args_list}
                    worksheet = load_workbook(BytesIO(payloads["download_excel"])).active
                    for row_index, row in enumerate(expected.itertuples(index=False), start=2):
                        for column_index, value in enumerate(row, start=2):
                            actual = worksheet.cell(row_index, column_index).value
                            if pd.isna(value):
                                self.assertIsNone(actual)
                            else:
                                self.assertEqual(actual, value)
                    for column in worksheet.column_dimensions.values():
                        self.assertGreater(column.width, 0)
                    with ZipFile(BytesIO(payloads["download_csv_zip"])) as archive:
                        csv = archive.read(archive.namelist()[0]).decode("utf-8-sig")
                    pd.testing.assert_frame_equal(
                        pd.read_csv(StringIO(csv), index_col=0, parse_dates=True),
                        expected,
                        check_freq=False,
                    )
                    self.assertEqual(payloads["download_TEST"].decode("utf-8-sig"), csv)
                    app.run()
                    self.assertEqual(len(app.exception), 0)
                    self.assertEqual(len(app.warning), int(len(chart_expected) < len(expected)))


if __name__ == "__main__":
    unittest.main()
