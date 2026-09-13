import unittest

from shared.lab_cost_inputs import lab_resources, validate_lab_cost_inputs


class LabCostInputTests(unittest.TestCase):
    def inputs(self, **changes):
        return dict(cloud_provider="aws", cloud_region="ap-south-1",
                    hours_per_day=3, participant_count=20, fx_rate=84, **changes)

    def test_missing_values_are_not_defaulted(self):
        for key in self.inputs():
            values = self.inputs()
            del values[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_lab_cost_inputs(values)

    def test_supported_regions_roundtrip(self):
        for provider, region in (("aws", "ap-south-1"), ("azure", "centralindia"), ("gcp", "asia-south1")):
            values = self.inputs()
            values.update(cloud_provider=provider, cloud_region=region)
            checked = validate_lab_cost_inputs(values)
            self.assertEqual(validate_lab_cost_inputs(checked), checked)

    def test_mismatched_region_is_rejected(self):
        values = self.inputs()
        values["cloud_region"] = "central-india"
        with self.assertRaises(ValueError):
            validate_lab_cost_inputs(values)

    def test_invalid_numbers_are_rejected(self):
        for key, value in (("hours_per_day", 25), ("participant_count", 1.5), ("fx_rate", float("nan")), ("lab_support_per_participant", -1)):
            values = self.inputs()
            values[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_lab_cost_inputs(values)

    def test_zero_support_is_preserved(self):
        self.assertEqual(validate_lab_cost_inputs(self.inputs(lab_support_per_participant=0))["lab_support_per_participant"], 0)

    def test_mapping_cannot_inject_formulas_or_round_resource_counts(self):
        for value in ('=100', 1.5, True, -1, float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_lab_cost_inputs(self.inputs(lab_day_mapping=[{'vm_qty': value}]))

    def test_invalid_cost_adjustments_are_rejected(self):
        for key, value in [('tax_percent', 101), ('contingency_percent', float('nan')), ('egress_gb', -1), ('monitoring_gb', float('inf'))]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_lab_cost_inputs(self.inputs(**{key: value}))

    def test_local_topics_do_not_allocate_cloud_resources(self):
        for text in ("Git branches", "Docker Desktop on local machine", "Kubernetes minikube local lab", "Postgres on localhost"):
            resources = lab_resources(text)
            self.assertFalse(any(resources[key] for key in ("vm", "k8s", "database", "storage")), text)

    def test_explicit_cloud_resources_are_mapped(self):
        resources = lab_resources("AWS EC2 Jenkins pipeline EKS RDS S3")
        self.assertTrue(all(resources.values()))


if __name__ == "__main__":
    unittest.main()
