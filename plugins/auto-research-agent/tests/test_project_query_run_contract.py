import unittest


class MalformedRunProofTests(unittest.TestCase):
    def test_untyped_saved_action_key_is_a_typed_refusal(self):
        from research_workspace_native.project_query_run import saved
        from research_workspace_native.session_api import SessionApiError

        for value in (None, [], {}):
            with self.subTest(value=value), self.assertRaises(SessionApiError):
                body = {
                    "confirmed": False,
                    "key": "not-authorized-work",
                    "run_authority": {"action_key": value},
                }
                saved(None, None, "alice", "project", body, "query-authorize")


if __name__ == "__main__":
    unittest.main()
