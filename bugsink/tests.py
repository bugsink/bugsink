import io
from datetime import datetime, timezone
import brotli

from unittest import TestCase as RegularTestCase
from django.test import TestCase as DjangoTestCase

from projects.models import Project
from issues.models import Issue, IssueStateManager
from issues.factories import denormalized_issue_fields
from events.models import Event
from events.factories import create_event

from .period_counter import PeriodCounter, _prev_tup
from .volume_based_condition import VolumeBasedCondition
from .registry import PeriodCounterRegistry
from .streams import (
    compress_with_zlib, GeneratorReader, WBITS_PARAM_FOR_GZIP, WBITS_PARAM_FOR_DEFLATE, MaxDataReader,
    MaxDataWriter, zlib_generator, brotli_generator)


def apply_n(f, n, v):
    for i in range(n):
        v = f(v)
    return v


class PeriodCounterTestCase(RegularTestCase):

    def test_prev_tup_near_rollover(self):
        self.assertEquals((2020,), _prev_tup((2021,)))

        self.assertEquals((2020,  1), _prev_tup((2020,  2)))
        self.assertEquals((2019, 12), _prev_tup((2020,  1)))

        self.assertEquals((2020,  1,  1), _prev_tup((2020,  1,  2)))
        self.assertEquals((2019, 12, 31), _prev_tup((2020,  1,  1)))
        self.assertEquals((2020,  2, 29), _prev_tup((2020,  3,  1)))
        self.assertEquals((2019,  2, 28), _prev_tup((2019,  3,  1)))

        self.assertEquals((2020,  1,  1, 10), _prev_tup((2020,  1,  1, 11)))
        self.assertEquals((2020,  1,  1,  0), _prev_tup((2020,  1,  1,  1)))
        self.assertEquals((2019, 12, 31, 23), _prev_tup((2020,  1,  1,  0)))
        self.assertEquals((2019, 12, 31, 22), _prev_tup((2019, 12, 31, 23)))

        self.assertEquals((2020,  1,  1,  0,  0), _prev_tup((2020,  1,  1,  0,  1)))
        self.assertEquals((2019, 12, 31, 23, 59), _prev_tup((2020,  1,  1,  0,  0)))

    def test_prev_tup_large_number_of_applications(self):
        self.assertEquals((1920,), apply_n(_prev_tup, 100, (2020,)))
        self.assertEquals((2010, 5), apply_n(_prev_tup, 120, (2020, 5)))
        self.assertEquals((2019, 5, 7,), apply_n(_prev_tup, 366, (2020, 5, 7)))
        self.assertEquals((2020, 5, 6, 20,), apply_n(_prev_tup, 24, (2020, 5, 7, 20,)))
        self.assertEquals((2020, 5, 6, 20, 12), apply_n(_prev_tup, 1440, (2020, 5, 7, 20, 12)))

    def test_prev_tup_with_explicit_n(self):
        self.assertEquals(_prev_tup((2020,), 100), apply_n(_prev_tup, 100, (2020,)))
        self.assertEquals(_prev_tup((2020, 5), 120), apply_n(_prev_tup, 120, (2020, 5)))
        self.assertEquals(_prev_tup((2020, 5, 7), 366), apply_n(_prev_tup, 366, (2020, 5, 7)))
        self.assertEquals(_prev_tup((2020, 5, 7, 20,), 24), apply_n(_prev_tup, 24, (2020, 5, 7, 20,)))
        self.assertEquals(_prev_tup((2020, 5, 7, 20, 12), 1440), apply_n(_prev_tup, 1440, (2020, 5, 7, 20, 12)))

    def test_prev_tup_works_for_empty_tup(self):
        # in general 'prev' is not defined for empty tuples; but it is convienient to define it as the empty tuple
        # because it makes the implementation of PeriodCounter simpler for the case of "all 1 'total' periods".

        self.assertEquals((), _prev_tup(()))
        # the meaninglessness of prev_tup is not extended to the case of n > 1, because "2 total periods" makes no sense
        # self.assertEquals((), _prev_tup((), 2))

    def test_foo(self):
        datetime_utc = datetime.now(timezone.utc)  # basically I just want to write this down somewhere
        pc = PeriodCounter()
        pc.inc(datetime_utc)

    def test_thresholds_for_total(self):
        timepoint = datetime(2020, 1, 1, 10, 15, tzinfo=timezone.utc)

        pc = PeriodCounter()
        thresholds = {"unmute": [("total", 1, 2, "meta")]}

        # first inc: should not yet be True
        states = pc.inc(timepoint, thresholds=thresholds)
        self.assertEquals({"unmute": [(False, "meta")]}, states)

        # second inc: should be True (threshold of 2)
        states = pc.inc(timepoint, thresholds=thresholds)
        self.assertEquals({"unmute": [(True, "meta")]}, states)

        # third inc: should still be True
        states = pc.inc(timepoint, thresholds=thresholds)
        self.assertEquals({"unmute": [(True, "meta")]}, states)

    def test_thresholds_for_year(self):
        tp_2020 = datetime(2020, 1, 1, 10, 15, tzinfo=timezone.utc)
        tp_2021 = datetime(2021, 1, 1, 10, 15, tzinfo=timezone.utc)
        tp_2022 = datetime(2022, 1, 1, 10, 15, tzinfo=timezone.utc)

        pc = PeriodCounter()
        thresholds = {"unmute": [("year", 2, 3, "meta")]}

        states = pc.inc(tp_2020, thresholds=thresholds)
        self.assertEquals({"unmute": [(False, "meta")]}, states)

        states = pc.inc(tp_2020, thresholds=thresholds)
        self.assertEquals({"unmute": [(False, "meta")]}, states)

        # 3rd in total: become True
        states = pc.inc(tp_2021, thresholds=thresholds)
        self.assertEquals({"unmute": [(True, "meta")]}, states)

        # into a new year, total == 2: become false
        states = pc.inc(tp_2022, thresholds=thresholds)
        self.assertEquals({"unmute": [(False, "meta")]}, states)

        # 3rd in (new) total: become True again
        states = pc.inc(tp_2022, thresholds=thresholds)
        self.assertEquals({"unmute": [(True, "meta")]}, states)


class VolumeBasedConditionTestCase(RegularTestCase):

    def test_serialization(self):
        vbc = VolumeBasedCondition("day", 1, 100)
        self.assertEquals({"period": "day", "nr_of_periods": 1, "volume": 100}, vbc.to_dict())

        vbc2 = VolumeBasedCondition.from_dict(vbc.to_dict())
        self.assertEquals(vbc, vbc2)


class PCRegistryTestCase(DjangoTestCase):

    def test_empty(self):
        result = PeriodCounterRegistry().load_from_scratch(
            Project.objects.all(),
            Issue.objects.all(),
            Event.objects.all(),
            datetime.now(timezone.utc),
        )
        self.assertEquals(({}, {}), result)

    def test_with_muted_issue_and_event(self):
        project = Project.objects.create(name="project")
        issue = Issue.objects.create(
            project=project,
            is_muted=True,
            unmute_on_volume_based_conditions='[{"period": "day", "nr_of_periods": 1, "volume": 100}]',
            **denormalized_issue_fields(),
        )

        create_event(project, issue)

        by_project, by_issue = PeriodCounterRegistry().load_from_scratch(
            Project.objects.all(),
            Issue.objects.all(),
            Event.objects.all(),
            datetime.now(timezone.utc),
        )

        self.assertEquals({project.id}, by_project.keys())
        self.assertEquals({issue.id}, by_issue.keys())

        self.assertEquals("day", IssueStateManager.get_unmute_thresholds(issue)[0][0])
        self.assertEquals(1, IssueStateManager.get_unmute_thresholds(issue)[0][1])
        self.assertEquals(100, IssueStateManager.get_unmute_thresholds(issue)[0][2])


class StreamsTestCase(RegularTestCase):

    def test_compress_decompress_gzip(self):
        myself_times_ten = open(__file__, 'rb').read() * 10
        plain_stream = io.BytesIO(myself_times_ten)

        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_GZIP))

        result = b""
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_GZIP))

        while True:
            chunk = reader.read(3)
            result += chunk
            if chunk == b"":
                break

        self.assertEquals(myself_times_ten, result)

    def test_compress_decompress_deflate(self):
        myself_times_ten = open(__file__, 'rb').read() * 10
        plain_stream = io.BytesIO(myself_times_ten)

        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_DEFLATE))

        result = b""
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_DEFLATE))

        while True:
            chunk = reader.read(3)
            result += chunk
            if chunk == b"":
                break

        self.assertEquals(myself_times_ten, result)

    def test_compress_decompress_brotli(self):
        myself_times_ten = open(__file__, 'rb').read() * 10

        compressed_stream = io.BytesIO(brotli.compress(myself_times_ten))

        result = b""
        reader = GeneratorReader(brotli_generator(compressed_stream))

        while True:
            chunk = reader.read(3)
            result += chunk
            if chunk == b"":
                break

        self.assertEquals(myself_times_ten, result)

    def test_compress_decompress_read_none(self):
        myself_times_ten = open(__file__, 'rb').read() * 10
        plain_stream = io.BytesIO(myself_times_ten)

        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_DEFLATE))

        result = b""
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_DEFLATE))

        result = reader.read(None)
        self.assertEquals(myself_times_ten, result)

    def test_max_data_reader(self):
        stream = io.BytesIO(b"hello" * 100)
        reader = MaxDataReader(250, stream)

        for i in range(25):
            self.assertEquals(b"hellohello", reader.read(10))

        with self.assertRaises(ValueError) as e:
            reader.read(10)

        self.assertEquals("Max length (250) exceeded", str(e.exception))

    def test_max_data_reader_none_ok(self):
        stream = io.BytesIO(b"hello" * 10)
        reader = MaxDataReader(250, stream)

        self.assertEquals(b"hello" * 10, reader.read(None))

    def test_max_data_reader_none_fail(self):
        stream = io.BytesIO(b"hello" * 100)
        reader = MaxDataReader(250, stream)

        with self.assertRaises(ValueError) as e:
            reader.read(None)

        self.assertEquals("Max length (250) exceeded", str(e.exception))

    def test_max_data_writer(self):
        stream = io.BytesIO()
        writer = MaxDataWriter(250, stream)

        for i in range(25):
            writer.write(b"hellohello")

        with self.assertRaises(ValueError):
            writer.write(b"hellohello")
