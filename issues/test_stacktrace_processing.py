from unittest import TestCase

from issues.utils import get_denormalized_fields_for_data
from sentry.at_glitchtip_af9a700a8706.stacktraces.processing import get_crash_frame_from_event_data


class CrashFrameFromEventDataTestCase(TestCase):
    def test_non_sequence_frames_are_ignored(self):
        data = {"exception": {"values": [{"stacktrace": {"frames": "[truncated:max-depth]"}}]}}

        self.assertIsNone(get_crash_frame_from_event_data(data))
        self.assertEqual("", get_denormalized_fields_for_data(data)["last_frame_filename"])

    def test_invalid_exception_frames_do_not_hide_top_level_frames(self):
        data = {
            "exception": {"values": [{"stacktrace": {"frames": "invalid"}}]},
            "stacktrace": {"frames": [{"filename": "top-level.py"}]},
        }

        self.assertEqual(
            {"filename": "top-level.py"},
            get_crash_frame_from_event_data(data),
        )

    def test_invalid_top_level_frames_fall_back_to_single_thread(self):
        data = {
            "stacktrace": {"frames": "invalid"},
            "threads": {"values": [{"stacktrace": {"frames": [{"filename": "thread.py"}]}}]},
        }

        self.assertEqual(
            {"filename": "thread.py"},
            get_crash_frame_from_event_data(data),
        )

    def test_non_mapping_frame_items_are_ignored(self):
        data = {"stacktrace": {"frames": [{"filename": "valid.py"}, "invalid", None]}}

        self.assertEqual(
            {"filename": "valid.py"},
            get_crash_frame_from_event_data(data, frame_filter=lambda frame: frame.get("filename") is not None),
        )
