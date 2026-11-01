import unittest
from unittest.mock import patch, MagicMock
from api_testing.request_calls import ServerApi, LoginError, ResponseError
from processor.input_processing import (
    PlayerGroupProcessor, DetailedPlaylistProcessor, PlaylistProcessor,
    AssetToPlaylistProcessor, PlayerNoteProcessor, PlayerConfigLocationProcessor,
    LocationTimesProcessor, PlayerLabelsProcessor, GroupSettingsProcessor,
    PlaylistSettingsProcessor, RemovePlaylistsProcessor,
    DeployAllPlayersProcessor, DeploySelectedGroupsProcessor,
    FormatException,
    legible_to_iso, split_list, convert_days_of_week_to_int,
    try_login, compare_time, compare_date, on_off_time_handler,
    normalize_time_format
)


class TestProcessors(unittest.TestCase):

    def setUp(self):
        self.valid_token_response = MagicMock()
        self.valid_token_response.json.return_value = {'token': 'valid_token'}

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_player_group_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_player_names.return_value = ["player1", "player2"]
        mock_server.get_group_names.return_value = ["group1", "group2"]

        logger = MagicMock()
        processor = PlayerGroupProcessor(logger, url='http://example.com', login='user', password='pass',
                                         lang=MagicMock())

        input_text = "player1\tgroup1\nplayer2\tgroup2"
        # set_group_to_player(group, player) echoes the player back as the server's "name", matching how
        # run() looks the assignment up in self.data (keyed by player name).
        mock_server.set_group_to_player.side_effect = lambda group, player: {"data": {"name": player}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {"player1": "group1", "player2": "group2"}
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_group_to_player.assert_any_call("group1", "player1")
        mock_server.set_group_to_player.assert_any_call("group2", "player2")
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_detailed_playlist_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_group_names.return_value = ["group1"]
        mock_server.get_playlist_names.return_value = ["playlist1", "playlist2"]

        logger = MagicMock()
        processor = DetailedPlaylistProcessor(logger, url='http://example.com', login='user', password='pass',
                                              lang=MagicMock())

        # group, blank default playlist, then a 6-field chunk (playlist, start date, end date, weekdays,
        # start time, end time) for the dated assignment.
        input_text = "group1\t\tplaylist1\t01.01.2022\t31.12.2022\tmo,tu\t08:00\t18:00"
        mock_server.set_playlist_to_group_detailed.return_value = {"data": {"name": "group1"}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "group1": [
                    ("playlist1", "2022-01-01T00:00:00.000Z", "2022-12-31T00:00:00.000Z", [2, 3], "08:00", "18:00")
                ]
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_playlist_to_group_detailed.assert_called_with("group1", [
            ("playlist1", "2022-01-01T00:00:00.000Z", "2022-12-31T00:00:00.000Z", [2, 3], "08:00", "18:00")
        ])
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_playlist_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_group_names.return_value = ["group1"]
        mock_server.get_playlist_names.return_value = ["playlist1"]

        logger = MagicMock()
        processor = PlaylistProcessor(logger, url='http://example.com', login='user', password='pass', lang=MagicMock())

        # 2 tab-separated fields (group, default playlist) plus a 5-field chunk (playlist, start date,
        # end date, start time, end time) for a dated assignment of the same playlist.
        input_text = "group1\tplaylist1\tplaylist1\t01.01.2022\t31.12.2022\t08:00\t18:00"
        mock_server.set_playlist_to_group.return_value = {"data": {"name": "group1"}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "group1": [
                    ("playlist1", None, None, None, None),
                    ("playlist1", "2022-01-01T00:00:00.000Z", "2022-12-31T00:00:00.000Z", "08:00", "18:00")
                ]
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_playlist_to_group.assert_called_with("group1", [
            ("playlist1", None, None, None, None),
            ("playlist1", "2022-01-01T00:00:00.000Z", "2022-12-31T00:00:00.000Z", "08:00", "18:00")
        ])
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_asset_to_playlist_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_playlist_names.return_value = ["playlist1"]
        mock_server.get_asset_names.return_value = ["asset1", "asset2"]

        logger = MagicMock()
        processor = AssetToPlaylistProcessor(logger, url='http://example.com', login='user', password='pass',
                                             lang=MagicMock())

        input_text = "playlist1\tasset1\tasset2"
        mock_server.set_assets_to_playlist.return_value = {"data": {"name": "playlist1"}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "playlist1": ["asset1", "asset2"]
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_assets_to_playlist.assert_called_with("playlist1", ["asset1", "asset2"])
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_player_note_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_player_names.return_value = ["player1"]

        logger = MagicMock()
        processor = PlayerNoteProcessor(logger, url='http://example.com', login='user', password='pass',
                                        lang=MagicMock())

        input_text = "player1\tnote1"
        mock_server.set_player_note.return_value = {"data": {"name": "player1"}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "player1": "note1"
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_player_note.assert_called_with("player1", "note1")
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_player_config_location_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_player_names.return_value = ["player1"]
        mock_server.get_location_names.return_value = ["location1"]

        logger = MagicMock()
        processor = PlayerConfigLocationProcessor(logger, url='http://example.com', login='user', password='pass',
                                                  lang=MagicMock())

        input_text = "player1\tlocation1"
        mock_server.set_player_config_location.return_value = {"data": {"name": "player1"}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "player1": "location1"
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_player_config_location.assert_called_with("player1", "location1")
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_location_times_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_location_names.return_value = ["location1"]

        logger = MagicMock()
        processor = LocationTimesProcessor(logger, url='http://example.com', login='user', password='pass',
                                           lang=MagicMock())

        input_text = "location1\t08:00\t18:00\t08:00\t18:00\t08:00\t18:00\t08:00\t18:00\t08:00\t18:00\t08:00\t18:00\t08:00\t18:00"
        mock_server.set_location.return_value = {"data": {"configLocation": "location1"}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "location1": {
                    "Monday": {"on": "08:00", "off": "18:00"},
                    "Tuesday": {"on": "08:00", "off": "18:00"},
                    "Wednesday": {"on": "08:00", "off": "18:00"},
                    "Thursday": {"on": "08:00", "off": "18:00"},
                    "Friday": {"on": "08:00", "off": "18:00"},
                    "Saturday": {"on": "08:00", "off": "18:00"},
                    "Sunday": {"on": "08:00", "off": "18:00"}
                }
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_location.assert_called_with("location1", expected_data["location1"])
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_player_labels_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_player_names.return_value = ["player1"]
        mock_server.get_labels.return_value = ["label1", "label2"]

        logger = MagicMock()
        processor = PlayerLabelsProcessor(logger, url='http://example.com', login='user', password='pass',
                                          lang=MagicMock())

        input_text = "player1\tlabel1\tlabel2"
        mock_server.set_player_labels.return_value = {"data": {"name": "player1"}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "player1": ["label1", "label2"]
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_player_labels.assert_called_with("player1", ["label1", "label2"])
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_group_settings_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_group_names.return_value = ["group1"]

        logger = MagicMock()
        processor = GroupSettingsProcessor(logger, url='http://example.com', login='user', password='pass',
                                           lang=MagicMock())

        input_text = "group1\t1080p\tlandscape\t03:00\t04:00\ttrue\ttrue\t06:00\t22:00"
        mock_server.set_group_settings.return_value = {"data": {"name": "group1"}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "group1": ["1080p", "landscape", "03:00", "04:00", True, True, "06:00", "22:00", ""]
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_group_settings.assert_called_with(
            "group1", "1080p", "landscape", "1970-01-01T02:00:00.000Z", "1970-01-01T03:00:00.000Z",
            True, True, "06:00", "22:00", ""
        )
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_playlist_settings_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_playlist_names.return_value = ["playlist1"]

        logger = MagicMock()
        processor = PlaylistSettingsProcessor(logger, url='http://example.com', login='user', password='pass',
                                              lang=MagicMock())

        input_text = "playlist1\t300"
        mock_server.set_playlist_settings.return_value = {"data": {"name": "playlist1"}}
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "playlist1": "300"
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.set_playlist_settings.assert_called_with("playlist1", "300")
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_remove_playlists_processor(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.get_group_names.return_value = ["group1"]

        logger = MagicMock()
        processor = RemovePlaylistsProcessor(logger, url='http://example.com', login='user', password='pass',
                                             lang=MagicMock())

        input_text = "group1\tkeyword"
        mock_server.remove_playlists_by_keyword_from_group.return_value = ["playlist1", "playlist2"]
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load(input_text)

            expected_data = {
                "group1": "keyword"
            }
            self.assertEqual(processor.data, expected_data)

            list(processor.run())

        mock_server.remove_playlists_by_keyword_from_group.assert_called_with("group1", "keyword")
        logger.info.assert_any_call(processor.lang.get_message.return_value)

    def test_legible_to_iso(self):
        self.assertEqual(legible_to_iso("01.01.2022"), "2022-01-01T00:00:00.000Z")
        self.assertIsNone(legible_to_iso(None))
        self.assertIsNone(legible_to_iso(""))

    def test_split_list(self):
        self.assertEqual(split_list("a, b, c"), ["a", "b", "c"])

    def test_convert_days_of_week_to_int(self):
        self.assertEqual(convert_days_of_week_to_int(["mo", "tu", "we"]), [2, 3, 4])

    @patch('api_testing.request_calls.requests.post')
    @patch('api_testing.request_calls.ServerApi._get_session_token', return_value='valid_token')
    def test_try_login(self, mock_get_token, mock_post):
        mock_post.return_value = self.valid_token_response
        mock_server = ServerApi(url='https://example.com', login='user', password='pass')

        with patch.object(ServerApi, '__enter__', return_value=mock_server), \
                patch.object(ServerApi, '__exit__', return_value=False):
            self.assertTrue(try_login("https://example.com", "user", "pass"))

        with patch.object(ServerApi, '__enter__', side_effect=LoginError):
            self.assertFalse(try_login("https://example.com", "user", "pass"))

    def test_compare_time(self):
        self.assertTrue(compare_time("08:00", "18:00"))
        self.assertFalse(compare_time("18:00", "08:00"))

    def test_compare_date(self):
        self.assertTrue(compare_date("01.01.2022", "31.12.2022"))
        self.assertFalse(compare_date("31.12.2022", "01.01.2022"))

    def test_on_off_time_handler(self):
        self.assertEqual(on_off_time_handler("08:00", "18:00"), ("08:00", "18:00"))
        self.assertEqual(on_off_time_handler(None, None), (None, None))

    def test_normalize_time_format(self):
        self.assertEqual(normalize_time_format("08:00:00"), "08:00")
        self.assertEqual(normalize_time_format("08:00"), "08:00")
        self.assertEqual(normalize_time_format("00:00", is_off_time=True), "23:59")


def _make_player(name, connected=True, group_name="g1"):
    return {"name": name, "_id": f"id_{name}", "group_id": "gid1", "group_name": group_name,
            "isConnected": connected}


class TestDeployProcessors(unittest.TestCase):
    @staticmethod
    def _make_all_players_processor(**kwargs):
        logger = MagicMock()
        return DeployAllPlayersProcessor(logger, url='http://example.com', login='user', password='pass',
                                         lang=MagicMock(), **kwargs)

    @staticmethod
    def _make_selected_groups_processor(**kwargs):
        logger = MagicMock()
        return DeploySelectedGroupsProcessor(logger, url='http://example.com', login='user', password='pass',
                                             lang=MagicMock(), **kwargs)

    @staticmethod
    def _mock_server_context():
        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.__exit__.return_value = False
        return mock_server

    def test_load_all_players_ignores_input(self):
        processor = self._make_all_players_processor()
        with patch.object(processor, '_try_server_login', return_value=MagicMock()):
            processor.load("")
        self.assertEqual(processor.data, {"groups": None})

    def test_load_selected_groups(self):
        processor = self._make_selected_groups_processor()
        mock_server = MagicMock()
        mock_server.get_group_names.return_value = ["group1", "group2", "group3"]
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            processor.load("group1\ngroup2")
        self.assertEqual(sorted(processor.data["groups"]), ["group1", "group2"])

    def test_load_selected_groups_unknown_raises(self):
        processor = self._make_selected_groups_processor()
        mock_server = MagicMock()
        mock_server.get_group_names.return_value = ["group1"]
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            with self.assertRaises(FormatException):
                processor.load("unknown_group")

    def test_load_selected_groups_empty_input_raises(self):
        processor = self._make_selected_groups_processor()
        mock_server = MagicMock()
        mock_server.get_group_names.return_value = ["group1"]
        with patch.object(processor, '_try_server_login', return_value=mock_server):
            with self.assertRaises(FormatException):
                processor.load("")

    def test_run_skips_offline_and_sorts_by_name(self):
        processor = self._make_all_players_processor(batch_size=2, batch_interval=0)
        processor.data = {"groups": None}
        players = [_make_player(n) for n in ["charlie", "alpha", "bravo"]] + [_make_player("offline1", connected=False)]

        mock_server = self._mock_server_context()
        mock_server.get_players_for_deploy.return_value = players
        mock_server.trigger_player_deploy.return_value = {"success": True}

        with patch.object(processor, '_write_deploy_batch_sent') as mock_batch_sent:
            with patch.object(processor, '_write_deploy_remaining') as mock_remaining:
                with patch.object(processor, '_try_server_login', return_value=mock_server):
                    list(processor.run())

        self.assertEqual(mock_server.trigger_player_deploy.call_count, 3)
        called_ids = {c.args[0] for c in mock_server.trigger_player_deploy.call_args_list}
        self.assertNotIn("id_offline1", called_ids)

        # 3 online players, batch_size=2: after batch 1 (alpha,bravo) one remains, after batch 2 none remain
        mock_remaining.assert_called_once_with(1)

        sent_batches = [call.args[0] for call in mock_batch_sent.call_args_list]
        self.assertEqual(sent_batches, [["alpha", "bravo"], ["charlie"]])

    def test_run_retries_and_eventually_succeeds(self):
        processor = self._make_all_players_processor(batch_size=5, batch_interval=0)
        processor.data = {"groups": None}
        player = _make_player("flaky")

        mock_server = self._mock_server_context()
        mock_server.get_players_for_deploy.return_value = [player]
        mock_server.trigger_player_deploy.side_effect = [ResponseError({}), ResponseError({}), {"success": True}]

        with patch.object(processor, '_write_deploy_final_summary') as mock_summary:
            with patch.object(processor, '_try_server_login', return_value=mock_server):
                list(processor.run())

        self.assertEqual(mock_server.trigger_player_deploy.call_count, 3)
        mock_summary.assert_called_once_with(1, 1, [])

    def test_run_fails_after_max_attempts(self):
        processor = self._make_all_players_processor(batch_size=5, batch_interval=0)
        processor.data = {"groups": None}
        player = _make_player("always_flaky")

        mock_server = self._mock_server_context()
        mock_server.get_players_for_deploy.return_value = [player]
        mock_server.trigger_player_deploy.side_effect = ResponseError({})

        with patch.object(processor, '_write_deploy_final_summary') as mock_summary:
            with patch.object(processor, '_try_server_login', return_value=mock_server):
                list(processor.run())

        self.assertEqual(mock_server.trigger_player_deploy.call_count, DeployAllPlayersProcessor.MAX_ATTEMPTS)
        mock_summary.assert_called_once_with(1, 0, [("always_flaky", "response_error")])

    def test_run_selected_groups_filters_by_group(self):
        processor = self._make_selected_groups_processor(batch_size=5, batch_interval=0)
        processor.data = {"groups": ["group1", "group2"]}

        mock_server = self._mock_server_context()
        mock_server.get_players_for_deploy.return_value = [_make_player("p1", group_name="group1")]
        mock_server.trigger_player_deploy.return_value = {"success": True}

        with patch.object(processor, '_try_server_login', return_value=mock_server):
            list(processor.run())

        mock_server.get_players_for_deploy.assert_called_once_with(["group1", "group2"])


if __name__ == '__main__':
    unittest.main()
