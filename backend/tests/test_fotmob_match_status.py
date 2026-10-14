import unittest

from backend.fotmob_client import (
    STATUS_CANCELLED,
    STATUS_FINISH,
    STATUS_IN_PLAY,
    STATUS_NOT_STARTED,
    derive_match_status,
)


class DeriveMatchStatusTest(unittest.TestCase):
    def test_cancelled_takes_precedence_over_finished(self):
        self.assertEqual(
            derive_match_status(
                {"started": True, "finished": True, "cancelled": True}
            ),
            STATUS_CANCELLED,
        )

    def test_finished_match(self):
        self.assertEqual(
            derive_match_status(
                {"started": True, "finished": True, "cancelled": False}
            ),
            STATUS_FINISH,
        )

    def test_in_play_match(self):
        self.assertEqual(
            derive_match_status(
                {"started": True, "finished": False, "cancelled": False}
            ),
            STATUS_IN_PLAY,
        )

    def test_not_started_match(self):
        self.assertEqual(derive_match_status({}), STATUS_NOT_STARTED)

    def test_invalid_status_shape_is_not_started(self):
        self.assertEqual(derive_match_status(None), STATUS_NOT_STARTED)


if __name__ == "__main__":
    unittest.main()
