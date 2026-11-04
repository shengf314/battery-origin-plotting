"""Offline public-package checks; no Origin process is created."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plotting_core.config import SKILL_ROOT
from plotting_core.models import PlotSpec
from plotting_core.pipeline import prepare
from plotting_core.export import runtime
from plotting_core.doctor import collect_diagnostics
from plotting_core.ingest.report import InputContractError
from plotting_core.ingest.normalize import NormalizedData, NormalizedSeries
from plotting_core.domains.electrochemistry.gcd.na_workflow import preflight_gcd_na
from scripts.prepare_example import prepare_example


class PublicPackageTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="battery-origin-example-"))

    def tearDown(self):
        shutil.rmtree(str(self.directory))

    def spec(self):
        return PlotSpec.from_file(str(prepare_example(self.directory, "rate_capability")))

    def test_synthetic_example_builds_six_stages_per_sample(self):
        spec = self.spec()
        before = Path(spec.data.file).read_bytes()
        config, data, validation, plan = prepare(spec)
        self.assertEqual(Path(spec.data.file).read_bytes(), before)
        self.assertEqual(len(plan.series), 2)
        self.assertTrue(all(len(series.points) == 30 for series in plan.series))
        # Recovery to 0.1 C is a sixth stage, independent of the first stage.
        rate_labels = [item for item in plan.labels if item.role == "rate_stage"]
        self.assertEqual(len(rate_labels), 6)

    def test_nonexistent_sample_is_rejected(self):
        spec = self.spec()
        document = spec.to_dict()
        document["samples"] = [{"name": "unknown-synthetic-sample"}]
        with self.assertRaises((ValueError, InputContractError)):
            prepare(PlotSpec.from_dict(document))

    def test_example_refuses_to_overwrite(self):
        prepare_example(self.directory)
        with self.assertRaises(FileExistsError):
            prepare_example(self.directory)

    def test_example_refuses_outputs_in_skill(self):
        with self.assertRaises(ValueError):
            prepare_example(SKILL_ROOT / "example-output")

    def test_default_gcd_example_preserves_both_branches_and_all_points(self):
        spec = PlotSpec.from_file(str(prepare_example(self.directory)))
        _, data, _, plan = prepare(spec)
        self.assertEqual(spec.plot_type, "gcd")
        self.assertEqual({series.branch for series in data.series}, {"charge", "discharge"})
        self.assertEqual(sum(len(series.points) for series in data.series), 6)
        self.assertEqual(len(plan.data_series), 2)

    def test_cycle_example_has_capacity_and_ce_on_native_dual_y_plan(self):
        spec = PlotSpec.from_file(str(prepare_example(self.directory, "cycle_performance")))
        _, data, _, plan = prepare(spec)
        self.assertEqual({series.metric for series in data.series},
                         {"discharge_capacity", "coulombic_efficiency"})
        self.assertEqual(sum(len(series.points) for series in data.series), 10)
        self.assertEqual({series.metric for series in plan.data_series},
                         {"discharge_capacity", "coulombic_efficiency"})

    def test_local_node_packages_are_discovered(self):
        modules = self.directory / "node_modules"
        (modules / "sharp").mkdir(parents=True)
        (modules / "sharp" / "package.json").write_text('{"version":"0.0.0"}', encoding="utf-8")
        self.assertEqual(runtime.find_node_modules({}, skill_root=self.directory), str(modules))

    def test_explicit_node_packages_must_contain_sharp(self):
        with self.assertRaises(RuntimeError):
            runtime.require(env={"CODEX_NODE_MODULES": str(self.directory)}, skill_root=self.directory)

    def test_doctor_honors_explicit_package_path(self):
        modules = self.directory / "modules"
        (modules / "sharp").mkdir(parents=True)
        (modules / "sharp" / "package.json").write_text('{"version":"0.0.0"}', encoding="utf-8")
        report = collect_diagnostics(node_modules=str(modules), probe_runtime=False)
        self.assertTrue(report["image_runtime"]["sharp"]["package_present"])
        self.assertEqual(report["image_runtime"]["load_probe"]["status"], "not_run")

    def test_na_mass_basis_requires_current_input_declaration(self):
        data = NormalizedData(
            plot_type="gcd", sample_order=["A"],
            source={"file": "synthetic.xlsx", "sheet": "Sheet1",
                    "x_representation": "specific_capacity",
                    "axis_binding": "capacity_voltage"},
            series=[NormalizedSeries(sample="A", cycle=1, branch="charge",
                                     points=[(0., 2.5), (10., 3.)],
                                     first_row=2, last_row=3)])
        settings = {
            "output": "delta_x",
            "samples": {"A": {
                "formula": "Na0.67Mn0.8Ni0.1Ti0.1O2",
                "formula_source": "synthetic declared formula",
                "assumptions": {
                    "reaction": "stoichiometric_na_intercalation",
                    "electrons_per_na": 1, "source": "synthetic example",
                    "parasitic_charge": "unknown"}}},
            "per_series": {"A_C1_charge": {
                "direction_sign": -1, "source": "synthetic sign",
                "reference_capacity_mAh_g": 0.,
                "reference_source": "synthetic initial state",
                "reference_delta_x": 0.,
                "reference_delta_x_source": "synthetic common origin"}}}
        missing = preflight_gcd_na(data, settings)
        self.assertFalse(missing["ready"])
        self.assertTrue(any("mass_normalization" in question
                            for question in missing["report"]["questions"]))
        explicit = copy.deepcopy(settings)
        explicit["mass_normalization"] = {
            "basis": "active_material", "source": "current synthetic input declaration"}
        supplied = preflight_gcd_na(data, explicit)
        self.assertTrue(supplied["ready"], supplied["report"])


if __name__ == "__main__":
    unittest.main()
