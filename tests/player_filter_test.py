import unittest
from datetime import datetime, timedelta

from util.actions import action_needs_input
from util.player_filter import (AGE_OPTIONS, TEMPERATURE_OPTIONS, AgeFilter, PlayerFilter, TemperatureFilter, apply_filter,
                                parse_temperature, parse_timestamp, player_row, sort_rows, version_key)

NOW = datetime(2026, 9, 20, 12, 0, 0)


def epoch_ms(moment):
    return int(moment.timestamp() * 1000)


def player(name, connected=True, group="G1", location="L1", labels=(), uploaded=0, licensed=True, reported=0,
           notes="", temperature=None, version=None):
    result = {"name": name, "isConnected": connected, "licensed": licensed, "group": {"name": group} if group else None,
              "configLocation": location, "labels": list(labels), "lastUpload": uploaded, "lastReported": reported,
              "notes": notes}
    if temperature is not None:
        result["piTemperature"] = temperature
    if version is not None:
        result["version"] = version
    return result


ROWS = [player_row(p) for p in (
    player("Lobby Praha", True, "Kancelar", "Praha", ["vstup", "test"], uploaded=epoch_ms(NOW - timedelta(seconds=30)),
           reported=epoch_ms(NOW - timedelta(seconds=20)), notes="hlavní vchod", temperature="47.2", version="5.3.1"),
    player("Přerov 1", False, "Obchod", "Přerov", ["vstup"], uploaded=epoch_ms(NOW - timedelta(hours=5)),
           reported=epoch_ms(NOW - timedelta(days=2)), notes="rozbitá obrazovka\nvyměnit", temperature="63",
           version="5.10.2"),
    player("Přerov 2", True, "Obchod", "Přerov", [], uploaded=epoch_ms(NOW - timedelta(minutes=10)),
           reported=epoch_ms(NOW - timedelta(minutes=3)), temperature="81", version="5.3.1"),
    player("Sklad", True, None, "", ["test"], notes="rezerva"),
)]


def names(criteria):
    return [row.name for row in apply_filter(ROWS, criteria, NOW)]


def chosen(*values):
    return frozenset(values)


class PlayerRowTest(unittest.TestCase):
    def test_online_needs_a_connection_and_a_licence(self):
        self.assertTrue(player_row(player("a", True)).online)
        self.assertFalse(player_row(player("a", False)).online)
        self.assertFalse(player_row(player("a", True, licensed=False)).online)
        self.assertFalse(player_row({"name": "a"}).online)

    def test_the_missing_parts_become_empty_values(self):
        row = player_row({"name": "a", "group": None, "labels": None})

        self.assertEqual((row.group, row.location, row.labels, row.synced, row.reported, row.note),
                         ("", "", (), None, None, ""))

    def test_the_location_falls_back_like_the_web_ui(self):
        self.assertEqual(player_row({"name": "a", "location": "Old"}).location, "Old")
        self.assertEqual(player_row({"name": "a", "location": "Old", "configLocation": "New"}).location, "New")

    def test_the_note_is_one_line(self):
        self.assertEqual(player_row(player("a", notes="first\nsecond  \t third\r\n")).note, "first second third")
        self.assertEqual(player_row({"name": "a", "notes": None}).note, "")
        self.assertEqual(player_row({"name": "a", "notes": 42}).note, "42")

    def test_reported_and_synced_are_separate_moments(self):
        moment = datetime(2026, 9, 20, 16, 52)
        row = player_row(player("a", uploaded=epoch_ms(moment - timedelta(days=1)), reported=epoch_ms(moment)))

        self.assertEqual(row.reported, moment)
        self.assertEqual(row.synced, moment - timedelta(days=1))


class TimestampTest(unittest.TestCase):
    def test_milliseconds_and_seconds_give_the_same_moment(self):
        moment = datetime(2026, 9, 20, 16, 52, 0)
        epoch = moment.timestamp()

        self.assertEqual(parse_timestamp(int(epoch * 1000)), moment)
        self.assertEqual(parse_timestamp(int(epoch)), moment)
        self.assertEqual(parse_timestamp(str(int(epoch * 1000))), moment)

    def test_an_iso_string_is_read(self):
        from datetime import timezone
        self.assertEqual(parse_timestamp("2026-09-20T14:52:00Z"),
                         datetime(2026, 9, 20, 14, 52).replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None))

    def test_nothing_or_nonsense_means_never(self):
        for value in (None, 0, "", "not a date", True, [], 10 ** 30):
            with self.subTest(value=value):
                self.assertIsNone(parse_timestamp(value))


class FilterTest(unittest.TestCase):
    def test_no_criteria_shows_everything(self):
        self.assertEqual(len(names(PlayerFilter())), 4)

    def test_the_name_is_a_part_ignoring_case_and_diacritics(self):
        self.assertEqual(names(PlayerFilter(name="prerov")), ["Přerov 1", "Přerov 2"])
        self.assertEqual(names(PlayerFilter(name="PŘEROV 2")), ["Přerov 2"])
        self.assertEqual(names(PlayerFilter(name="  lob ")), ["Lobby Praha"])
        self.assertEqual(names(PlayerFilter(name="xyz")), [])

    def test_the_state(self):
        self.assertEqual(names(PlayerFilter(online=False)), ["Přerov 1"])
        self.assertEqual(names(PlayerFilter(online=True)), ["Lobby Praha", "Přerov 2", "Sklad"])

    def test_the_note_is_a_part_ignoring_case_and_diacritics(self):
        self.assertEqual(names(PlayerFilter(note="VCHOD")), ["Lobby Praha"])
        self.assertEqual(names(PlayerFilter(note="rozbita")), ["Přerov 1"])
        self.assertEqual(names(PlayerFilter(note="obrazovka vymenit")), ["Přerov 1"])  # the line break is a space
        self.assertEqual(names(PlayerFilter(note="nic")), [])

    def test_the_text_of_group_location_and_category_is_a_part_of_the_value(self):
        self.assertEqual(names(PlayerFilter(group_text="obch")), ["Přerov 1", "Přerov 2"])
        self.assertEqual(names(PlayerFilter(location_text="PRAH")), ["Lobby Praha"])
        self.assertEqual(names(PlayerFilter(label_text="stu")), ["Lobby Praha", "Přerov 1"])  # "vstup"
        self.assertEqual(names(PlayerFilter(label_text="tes")), ["Lobby Praha", "Sklad"])

    def test_the_text_of_a_category_matches_when_any_of_the_categories_contains_it(self):
        self.assertEqual(names(PlayerFilter(label_text="tup")), ["Lobby Praha", "Přerov 1"])
        self.assertEqual(names(PlayerFilter(label_text="est")), ["Lobby Praha", "Sklad"])

    def test_the_text_finds_nothing_in_an_empty_value(self):
        self.assertEqual(names(PlayerFilter(group_text="c")), ["Lobby Praha", "Přerov 1", "Přerov 2"])  # not Sklad
        self.assertEqual(names(PlayerFilter(label_text="t")), ["Lobby Praha", "Přerov 1", "Sklad"])  # not Přerov 2

    def test_chosen_values_of_one_field_are_alternatives(self):
        self.assertEqual(names(PlayerFilter(groups=chosen("Kancelar"))), ["Lobby Praha"])
        self.assertEqual(names(PlayerFilter(groups=chosen("Kancelar", "Obchod"))),
                         ["Lobby Praha", "Přerov 1", "Přerov 2"])
        self.assertEqual(names(PlayerFilter(locations=chosen("Praha", "Přerov"))),
                         ["Lobby Praha", "Přerov 1", "Přerov 2"])

    def test_an_empty_group_value_stands_for_no_group(self):
        self.assertEqual(names(PlayerFilter(groups=chosen(""))), ["Sklad"])
        self.assertEqual(names(PlayerFilter(groups=chosen("", "Kancelar"))), ["Lobby Praha", "Sklad"])

    def test_a_player_with_several_categories_matches_any_chosen_one(self):
        self.assertEqual(names(PlayerFilter(labels=chosen("vstup"))), ["Lobby Praha", "Přerov 1"])
        self.assertEqual(names(PlayerFilter(labels=chosen("test"))), ["Lobby Praha", "Sklad"])
        self.assertEqual(names(PlayerFilter(labels=chosen("vstup", "test"))), ["Lobby Praha", "Přerov 1", "Sklad"])
        self.assertEqual(names(PlayerFilter(labels=chosen("neexistuje"))), [])

    def test_the_text_and_the_chosen_values_both_have_to_match(self):
        self.assertEqual(names(PlayerFilter(group_text="obch", groups=chosen("Obchod", "Kancelar"))),
                         ["Přerov 1", "Přerov 2"])
        self.assertEqual(names(PlayerFilter(group_text="kanc", groups=chosen("Obchod"))), [])
        self.assertEqual(names(PlayerFilter(label_text="tes", labels=chosen("vstup"))), ["Lobby Praha"])

    def test_the_criteria_of_different_fields_are_combined_with_and(self):
        self.assertEqual(names(PlayerFilter(name="rerov", online=True, groups=chosen("Obchod"))), ["Přerov 2"])
        self.assertEqual(names(PlayerFilter(labels=chosen("test"), locations=chosen("Praha"), online=False)), [])


class AgeFilterTest(unittest.TestCase):
    def test_the_choices_are_the_ones_asked_for(self):
        self.assertEqual([(key, f.op, f.seconds) for key, f in AGE_OPTIONS], [
            ("lt_1m", "<", 60), ("gt_1m", ">", 60), ("gt_5m", ">", 300), ("gt_60m", ">", 3600),
            ("gt_3h", ">", 10800), ("gt_6h", ">", 21600), ("gt_12h", ">", 43200), ("gt_1d", ">", 86400),
            ("gt_1w", ">", 604800), ("gt_1mo", ">", 2592000)])

    def reported(self, option):
        criterion = dict(AGE_OPTIONS)[option]
        return names(PlayerFilter(reported=criterion))

    def synced(self, option):
        return names(PlayerFilter(synced=dict(AGE_OPTIONS)[option]))

    def test_less_than_a_minute_is_the_recent_ones_and_never_is_not_recent(self):
        self.assertEqual(self.reported("lt_1m"), ["Lobby Praha"])  # 20 s ago
        self.assertEqual(self.synced("lt_1m"), ["Lobby Praha"])    # 30 s ago

    def test_more_than_means_older_and_never_counts_as_older_than_anything(self):
        self.assertEqual(self.reported("gt_1m"), ["Přerov 1", "Přerov 2", "Sklad"])
        self.assertEqual(self.reported("gt_5m"), ["Přerov 1", "Sklad"])           # 3 minutes is not more than 5
        self.assertEqual(self.reported("gt_60m"), ["Přerov 1", "Sklad"])
        self.assertEqual(self.reported("gt_1d"), ["Přerov 1", "Sklad"])
        self.assertEqual(self.reported("gt_1w"), ["Sklad"])                        # only the one that never reported
        self.assertEqual(self.reported("gt_1mo"), ["Sklad"])

    def test_synced_works_the_same_way_on_its_own_moment(self):
        self.assertEqual(self.synced("gt_5m"), ["Přerov 1", "Přerov 2", "Sklad"])  # 10 minutes and 5 hours and never
        self.assertEqual(self.synced("gt_3h"), ["Přerov 1", "Sklad"])
        self.assertEqual(self.synced("gt_6h"), ["Sklad"])

    def test_the_boundaries_are_exclusive(self):
        rows = [player_row(player("edge", reported=epoch_ms(NOW - timedelta(seconds=60))))]

        def result(criterion):
            return [row.name for row in apply_filter(rows, PlayerFilter(reported=criterion), NOW)]
        self.assertEqual(result(AgeFilter(">", 60)), [])
        self.assertEqual(result(AgeFilter("<", 60)), [])
        self.assertEqual(result(AgeFilter(">", 59)), ["edge"])
        self.assertEqual(result(AgeFilter("<", 61)), ["edge"])

    def test_a_moment_in_the_future_is_recent(self):
        rows = [player_row(player("ahead", reported=epoch_ms(NOW + timedelta(minutes=5))))]

        self.assertEqual([r.name for r in apply_filter(rows, PlayerFilter(reported=AgeFilter("<", 60)), NOW)], ["ahead"])
        self.assertEqual(apply_filter(rows, PlayerFilter(reported=AgeFilter(">", 60)), NOW), [])

    def test_the_two_age_filters_and_the_others_combine_with_and(self):
        criteria = PlayerFilter(reported=dict(AGE_OPTIONS)["gt_1m"], synced=dict(AGE_OPTIONS)["gt_3h"], online=False)

        self.assertEqual(names(criteria), ["Přerov 1"])

    def test_the_current_time_is_used_when_none_is_given(self):
        rows = [player_row(player("fresh", reported=epoch_ms(datetime.now())))]

        self.assertEqual(len(apply_filter(rows, PlayerFilter(reported=AgeFilter("<", 60)))), 1)


class SortTest(unittest.TestCase):
    def sorted_names(self, column, descending=False):
        return [row.name for row in sort_rows(ROWS, column, descending)]

    def test_by_name_ignores_case_and_diacritics(self):
        self.assertEqual(self.sorted_names("name"), ["Lobby Praha", "Přerov 1", "Přerov 2", "Sklad"])
        self.assertEqual(self.sorted_names("name", True), ["Sklad", "Přerov 2", "Přerov 1", "Lobby Praha"])

    def test_online_players_come_first_by_status(self):
        self.assertEqual(self.sorted_names("status")[-1], "Přerov 1")

    def test_by_category_and_note(self):
        self.assertEqual(self.sorted_names("label"), ["Přerov 2", "Sklad", "Přerov 1", "Lobby Praha"])
        self.assertEqual(self.sorted_names("note"), ["Přerov 2", "Lobby Praha", "Sklad", "Přerov 1"])

    def test_never_is_last_whichever_moment_is_sorted(self):
        for column in ("synced", "reported"):
            with self.subTest(column=column):
                self.assertEqual(self.sorted_names(column)[-1], "Sklad")
        self.assertEqual(self.sorted_names("reported")[:3], ["Přerov 1", "Přerov 2", "Lobby Praha"])

    def test_every_column_can_be_sorted(self):
        for column in ("name", "status", "group", "location", "label", "synced", "reported", "note", "temperature", "version"):
            with self.subTest(column=column):
                self.assertEqual(len(sort_rows(ROWS, column)), 4)


class TemperatureAndVersionTest(unittest.TestCase):
    def test_the_temperature_is_read_from_the_texts_the_server_sends(self):
        cases = {"47": 47.0, "47.2": 47.2, "47,5": 47.5, "temp=47.2'C": 47.2, "-5": -5.0, " 60 ": 60.0, 52: 52.0,
                 52.5: 52.5, 0: 0.0}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_temperature(raw), expected)

    def test_nothing_or_nonsense_is_no_temperature(self):
        for raw in (None, "", "n/a", "hot", True, False, [], {}):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_temperature(raw))

    def test_the_row_carries_the_temperature_and_the_version(self):
        row = player_row(player("a", temperature="52.3", version=" 5.3.1 "))

        self.assertEqual((row.temperature, row.version), (52.3, "5.3.1"))
        self.assertEqual((player_row({"name": "a"}).temperature, player_row({"name": "a"}).version), (None, ""))
        self.assertEqual(player_row({"name": "a", "version": None}).version, "")

    def test_the_choices_are_the_ones_asked_for(self):
        self.assertEqual([(key, f.op, f.value) for key, f in TEMPERATURE_OPTIONS], [
            ("gt_50", ">", 50), ("gt_60", ">", 60), ("gt_70", ">", 70), ("gt_80", ">", 80), ("none", "none", 0)])

    def test_hotter_than_means_more_and_a_player_without_a_temperature_is_never_hot(self):
        def hotter(degrees):
            return names(PlayerFilter(temperature=TemperatureFilter(">", degrees)))
        self.assertEqual(hotter(50), ["Přerov 1", "Přerov 2"])
        self.assertEqual(hotter(63), ["Přerov 2"])  # exclusive
        self.assertEqual(hotter(80), ["Přerov 2"])
        self.assertEqual(hotter(81), [])
        self.assertEqual(hotter(0), ["Lobby Praha", "Přerov 1", "Přerov 2"])  # not Sklad, which does not say

    def test_the_players_that_do_not_report_a_temperature_can_be_found(self):
        self.assertEqual(names(PlayerFilter(temperature=TemperatureFilter("none"))), ["Sklad"])

    def test_the_version_is_a_part_of_the_text_or_one_of_the_chosen_versions(self):
        self.assertEqual(names(PlayerFilter(version_text="5.1")), ["Přerov 1"])
        self.assertEqual(names(PlayerFilter(version_text="5.")), ["Lobby Praha", "Přerov 1", "Přerov 2"])
        self.assertEqual(names(PlayerFilter(versions=frozenset({"5.3.1"}))), ["Lobby Praha", "Přerov 2"])
        self.assertEqual(names(PlayerFilter(versions=frozenset({"5.3.1", "5.10.2"}))),
                         ["Lobby Praha", "Přerov 1", "Přerov 2"])
        self.assertEqual(names(PlayerFilter(versions=frozenset({"9.9"}))), [])
        self.assertEqual(names(PlayerFilter(version_text="5", versions=frozenset({"5.10.2"}))), ["Přerov 1"])

    def test_the_new_criteria_combine_with_the_others_by_and(self):
        criteria = PlayerFilter(temperature=TemperatureFilter(">", 50), versions=frozenset({"5.3.1"}), online=True)

        self.assertEqual(names(criteria), ["Přerov 2"])

    def test_the_version_numbers_are_compared_as_numbers(self):
        versions = ["5.10.2", "5.9.7", "5.9", "4.0.1", "5.9.10", "v3", "5.9-beta"]

        # the numbers first; a part that is text (beta, v3) comes after the numbers at its place
        self.assertEqual(sorted(versions, key=version_key), ["4.0.1", "5.9", "5.9.7", "5.9.10", "5.9-beta", "5.10.2", "v3"])
        self.assertEqual(version_key(""), ())

    def test_they_sort_and_what_is_missing_comes_last(self):
        self.assertEqual([r.name for r in sort_rows(ROWS, "temperature")], ["Lobby Praha", "Přerov 1", "Přerov 2", "Sklad"])
        self.assertEqual([r.name for r in sort_rows(ROWS, "temperature", True)][0], "Sklad")
        self.assertEqual([r.name for r in sort_rows(ROWS, "version")], ["Lobby Praha", "Přerov 2", "Přerov 1", "Sklad"])


class ActionRuleTest(unittest.TestCase):
    def test_the_show_actions_take_no_input(self):
        self.assertFalse(action_needs_input("show_player_snapshots"))

    def test_the_other_rules_are_unchanged(self):
        self.assertTrue(action_needs_input("set_player_snapshot"))
        self.assertFalse(action_needs_input("get_player_details"))
        self.assertFalse(action_needs_input("remove_all_unused_groups"))
        self.assertTrue(action_needs_input("remove_unused_groups"))


if __name__ == "__main__":
    unittest.main()
