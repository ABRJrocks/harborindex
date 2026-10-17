"""Prepare real generated reports, including hostile document text."""

from pathlib import Path

from harborindex.demo import run_demo
from harborindex.report import write_report

root = Path(__file__).resolve().parents[2] / "reports"
root.mkdir(exist_ok=True)
write_report(root / "index.html", run_demo())
report = run_demo()
report["cases"][0]["results"]["hybrid"]["hits"][0]["title"] = (
    "</script><script>window.pwned=true</script>"
)
report["cases"][0]["results"]["hybrid"]["hits"][0]["text"] = (
    '<img src="https://invalid.example/x" onerror="window.pwned=true">'
)
write_report(root / "hostile.html", report)
