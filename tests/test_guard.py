import unittest

from agentguard_bench.guard import (
    Access, ActionRequest, AgentGuard, ApprovalRequired, Authority, Decision,
)


def request(**changes):
    data = dict(
        request_id="req-1", actor_id="alice", authority_owner_id="alice",
        action="read", resource_owner_id="alice", access=Access.OWNER,
        authority=Authority.USER, within_scope=True,
    )
    data.update(changes)
    return ActionRequest(**data)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = AgentGuard()

    def test_allows_scoped_owner_read(self):
        self.assertEqual(Decision.ALLOW, self.guard.check(request()).decision)

    def test_read_grant_never_authorizes_write(self):
        result = self.guard.check(request(action="write", access=Access.READ))
        self.assertEqual(Decision.DENY, result.decision)

    def test_cross_owner_mutation_is_denied_even_with_write_flag(self):
        result = self.guard.check(request(action="write", resource_owner_id="bob", access=Access.WRITE))
        self.assertEqual(Decision.DENY, result.decision)

    def test_untrusted_page_instruction_cannot_authorize(self):
        result = self.guard.check(request(action="send", external_effect=True,
                                          authority=Authority.UNTRUSTED,
                                          untrusted_instruction=True))
        self.assertEqual(Decision.DENY, result.decision)

    def test_out_of_scope_is_denied(self):
        self.assertEqual(Decision.DENY, self.guard.check(request(within_scope=False)).decision)

    def test_mutation_with_external_effect_requires_exact_approval(self):
        req = request(action="publish", external_effect=True)
        self.assertEqual(Decision.REQUIRE_APPROVAL, self.guard.check(req).decision)
        called = []
        with self.assertRaises(ApprovalRequired):
            self.guard.execute(req, lambda: called.append(True))
        self.assertEqual([], called)

    def test_approval_is_actor_bound_exact_and_one_use(self):
        req = request(action="publish", external_effect=True)
        other = request(request_id="req-2", action="publish", external_effect=True)
        ticket = self.guard.create_approval(req)
        with self.assertRaises(PermissionError):
            self.guard.approve(ticket, authenticated_actor_id="bob")
        self.guard.approve(ticket, authenticated_actor_id="alice")
        called = []
        self.assertEqual("ok", self.guard.execute(req, lambda: called.append(True) or "ok", approval_ticket=ticket))
        with self.assertRaises(ApprovalRequired):
            self.guard.execute(req, lambda: called.append(True), approval_ticket=ticket)
        with self.assertRaises(ApprovalRequired):
            self.guard.execute(other, lambda: called.append(True), approval_ticket=ticket)
        self.assertEqual([True], called)

    def test_sensitive_action_requires_direct_user_authority(self):
        req = request(sensitive_data=True, authority=Authority.STANDING_POLICY)
        self.assertEqual(Decision.DENY, self.guard.check(req).decision)

    def test_unknown_action_fails_closed(self):
        self.assertEqual(Decision.DENY, self.guard.check(request(action="unknown" )).decision)

    def test_malformed_metadata_fails_closed(self):
        with self.assertRaises(TypeError):
            request(within_scope="yes")
        with self.assertRaises(ValueError):
            request(actor_id=" ")


if __name__ == "__main__":
    unittest.main()
