# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from ruler.interfaces.cbr_benchmark import build_cbr_benchmark, write_cbr_benchmark


def test_cbr_benchmark_reports_all_release_gate_metrics(tmp_path) -> None:
    report = build_cbr_benchmark()
    assert report["domain_count"] == 5
    assert set(report["metrics"].values()) == {1.0}
    paths = write_cbr_benchmark(tmp_path)
    assert all(path.is_file() for path in paths.values())
