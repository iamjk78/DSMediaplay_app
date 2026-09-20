import unittest
from datetime import datetime

from util.actions import action_needs_input
from util.player_filter import PlayerFilter, apply_filter, parse_timestamp, player_row, sort_rows


def player(name, connected=True, group="G1", location="L1", labels=(), uploaded=0, licensed=True):
    return {"name": name, "isConnected": connected, "licensed": licensed, "group": {"name": group} if group else None,
            "configLocation": location, "labels": list(labels), "lastUpload": uploaded}


ROWS = [player_row(p) for p in (
    player("Lobby Praha", True, "Kancelar", "Praha", ["vstup", "test"]),
    player("Přerov 1", False, "Obchod", "Přerov", ["vstup"]),
    player("Přerov 2", True, "Obchod", "Přerov", []),
    player("Sklad", True, None, "", ["test"]),
)]


def names(criteria):
    return [row.name for row in apply_filter(ROWS, criteria)]


class PlayerRowTest(unittest.TestCase):
    def test_online_needs_a_connection_and_a_licence(self):
        self.assertTrue(player_row(player("a", True)).online)
        self.assertFalse(player_row(player("a", False)).online)
        self.assertFalse(player_row(player("a", True, licensed=False)).online)
        self.assertFalse(player_row({"name": "a"}).online)

    def test_the_missing_parts_become_empty_values(self):
        row = player_row({"name": "a", "group": None, "labels": None})

        self.assertEqual((row.group, row.location, row.labels, row.synced), ("", "", (), None))

    def test_the_location_falls_back_like_the_web_ui(self):
        self.assertEqual(player_row({"name": "a", "location": "Old"}).location, "Old")
        self.assertEqual(player_row({"name": "a", "location": "Old", "configLocation": "New"}).location, "New")


class TimestampTest(unittest.TestCase):
    def test_milliseconds_and_seconds_give_the_same_moment(self):
        moment = datetime(2026, 9, 20, 16, 52, 0)
        epoch = moment.timestamp()

        self.assertEqual(parse_timestamp(int(epoch * 1000)), moment)
        self.assertEqual(parse_timestamp(int(epoch)), moment)
        self.assertEqual(parse_timestamp(str(int(epoch * 1000))), moment)

    def test_an_iso_string_is_read(self):
        self.assertEqual(parse_timestamp("2026-09-20T14:52:00Z"),
                         datetime(2026, 9, 20, 14, 52).replace(tzinfo=__import__("datetime").timezone.utc)
                         .astimezone().replace(tzinfo=None))

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

    def test_group_label_location_and_state(self):
        self.assertEqual(names(PlayerFilter(group="Obchod")), ["Přerov 1", "Přerov 2"])
        self.assertEqual(names(PlayerFilter(label="test")), ["Lobby Praha", "Sklad"])
        self.assertEqual(names(PlayerFilter(location="Přerov")), ["Přerov 1", "Přerov 2"])
        self.assertEqual(names(PlayerFilter(online=False)), ["Přerov 1"])
        self.assertEqual(names(PlayerFilter(online=True)), ["Lobby Praha", "Přerov 2", "Sklad"])

    def test_an_empty_group_selects_the_players_without_a_group(self):
        self.assertEqual(names(PlayerFilter(group="")), ["Sklad"])

    def test_a_player_with_several_labels_matches_any_of_them(self):
        self.assertEqual(names(PlayerFilter(label="vstup")), ["Lobby Praha", "Přerov 1"])

    def test_the_criteria_are_combined_with_and(self):
        self.assertEqual(names(PlayerFilter(name="rerov", online=True, group="Obchod", label=None)), ["Přerov 2"])
        self.assertEqual(names(PlayerFilter(label="test", location="Praha", online=False)), [])


class SortTest(unittest.TestCase):
    def sorted_names(self, column, descending=False):
        return [row.name for row in sort_rows(ROWS, column, descending)]

    def test_by_name_ignores_case_and_diacritics(self):
        self.assertEqual(self.sorted_names("name"), ["Lobby Praha", "Přerov 1", "Přerov 2", "Sklad"])
        self.assertEqual(self.sorted_names("name", True), ["Sklad", "Přerov 2", "Přerov 1", "Lobby Praha"])

    def test_online_players_come_first_by_status(self):
        self.assertEqual(self.sorted_names("status")[-1], "Přerov 1")

    def test_never_synced_is_last_whichever_way_it_is_sorted_by_date(self):
        rows = [player_row(player("old", uploaded=1_600_000_000_000)), player_row(player("never")),
                player_row(player("new", uploaded=1_700_000_000_000))]

        self.assertEqual([row.name for row in sort_rows(rows, "synced")], ["old", "new", "never"])

    def test_every_column_can_be_sorted(self):
        for column in ("name", "status", "group", "location", "synced"):
            with self.subTest(column=column):
                self.assertEqual(len(sort_rows(ROWS, column)), 4)


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
