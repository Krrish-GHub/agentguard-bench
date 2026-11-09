import unittest
from agentguard_bench.metrics import summarize
from agentguard_bench.policy import DECISIONS, allowlist_policy, validate_decision
from agentguard_bench.runner import load_cases, run_policy

class BenchmarkTests(unittest.TestCase):
    def test_dataset_has_unique_cases_and_valid_labels(self):
        cases = load_cases()
        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertTrue(all(case["expected"] in DECISIONS for case in cases))

    def test_allowlist_baseline_matches_reference_labels(self):
        cases = load_cases()
        mismatches = [(c["id"], c["expected"], allowlist_policy(c)) for c in cases if allowlist_policy(c) != c["expected"]]
        self.assertEqual([], mismatches)

    def test_prompt_injection_mutations_are_denied(self):
        injected = [c for c in load_cases() if c["untrusted_instruction"] and c["action_kind"] != "read"]
        self.assertGreaterEqual(len(injected), 4)
        self.assertTrue(all(allowlist_policy(c) == "deny" for c in injected))

    def test_external_and_irreversible_actions_wait_for_approval(self):
        pending = [c for c in load_cases() if (c["external_effect"] or c["irreversible"]) and c["user_authorized"] and not c["approval_present"]]
        self.assertTrue(pending)
        self.assertTrue(all(allowlist_policy(c) == "ask_approval" for c in pending))

    def test_metrics_are_bounded(self):
        rows = run_policy(load_cases(), allowlist_policy)
        report = summarize(rows)
        self.assertEqual(len(rows), report["cases"])
        for key in ("accuracy", "unsafe_allow_rate", "false_block_rate", "task_completion_rate", "approval_or_abstention_rate"):
            self.assertGreaterEqual(report[key], 0)
            self.assertLessEqual(report[key], 1)

    def test_decision_parser_rejects_unexpected_output(self):
        for invalid in (None, "execute", "allow because…", 3):
            with self.assertRaises(ValueError): validate_decision(invalid)
        self.assertEqual("ask_approval", validate_decision(" ASK_APPROVAL "))

if __name__ == "__main__":
    unittest.main()
