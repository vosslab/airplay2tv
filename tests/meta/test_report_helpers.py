"""Unit tests for file_utils.report_name."""

# local repo modules
import file_utils


#============================================
class TestReportName:
	"""Behavioral tests for the report_name helper."""

	def test_report_name_strips_test_prefix_and_extension(self) -> None:
		"""report_name maps a test module path to its canonical report filename."""
		result = file_utils.report_name("/x/tests/test_foo.py")
		assert result == "report_foo.txt"

	def test_report_name_with_compound_stem(self) -> None:
		"""report_name handles multi-word test file stems correctly."""
		result = file_utils.report_name("/some/path/tests/test_ascii_compliance.py")
		assert result == "report_ascii_compliance.txt"
