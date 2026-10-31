from abc import ABC, abstractmethod
from typing import List, Generator, Dict, Any, Tuple, Optional, Set
from dataclasses import dataclass
from itertools import count
from time import sleep
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import requests.exceptions
from api_testing.request_calls import (ServerApi, LoginError, NameResolutionError, ResponseError, SnapshotError,
                                       WEEK_DAYS, snapshot_file_stem, snapshot_reason)
import itertools
import json
import os
import re


def convert(lst: List) -> Tuple:
    return tuple(lst)


def legible_to_iso(legible_str: str) -> Optional[str]:
    if not legible_str or legible_str in ["None", ""]:
        return None
    dt = datetime.strptime(legible_str, "%d.%m.%Y")
    return dt.strftime("%Y-%m-%dT%H:%M:00.000Z")


def split_list(text: str) -> List[str]:
    return [x.replace(" ", "").lower() for x in text.split(',')]


# The API numbers the days 1 (Sunday) to 7 (Saturday). The CSV export writes these codes and the input reads them,
# both from this one table, so a file exported and pasted back always means the same days.
DAY_CODE_BY_NUMBER = {1: "su", 2: "mo", 3: "tu", 4: "we", 5: "th", 6: "fr", 7: "sa"}
# "st" is the older code for Saturday (older exports wrote it); still accepted on input
DAY_CODES = {**{code: number for number, code in DAY_CODE_BY_NUMBER.items()}, "st": 7}


def convert_days_of_week_to_int(days_numerical: List[str]) -> List[int]:
    """Day codes (su mo tu we th fr sa) or the API numbers 1-7; anything else becomes 8, which is rejected later."""
    return [int(day) if day in ("1", "2", "3", "4", "5", "6", "7") else DAY_CODES.get(day, 8)
            for day in days_numerical]


def try_login(url: str, login: str, password: str) -> bool:
    url += "/api"
    try:
        with ServerApi(url=url, login=login, password=password):
            pass
        return True
    except LoginError:
        return False


def compare_time(start_time: str, end_time: str) -> bool:
    start = datetime.strptime(start_time, "%H:%M")
    end = datetime.strptime(end_time, "%H:%M")
    return start < end


def compare_date(start_date: str, end_date: str) -> bool:
    start = datetime.strptime(start_date, "%d.%m.%Y")
    end = datetime.strptime(end_date, "%d.%m.%Y")
    return start <= end


def on_off_time_handler(start_time: str, end_time: str) -> (str, str):
    invalid_symbols = ["", None]
    if start_time in invalid_symbols or end_time in invalid_symbols:
        return None, None
    return normalize_time_format(start_time), normalize_time_format(end_time, is_off_time=True)


def normalize_time_format(time_str: str, is_off_time: bool = False) -> str:
    """
    Normalizes a time string to the format %H:%M and converts "0:00" to "23:59" if specified.
    """
    if not time_str or time_str.strip() == "":
        return ""
    try:
        dt = datetime.strptime(time_str, "%H:%M:%S")
        if is_off_time and dt.strftime("%H:%M") in ["0:00", "00:00"]:
            return "23:59"
        return dt.strftime("%H:%M")
    except ValueError:
        pass

    try:
        dt = datetime.strptime(time_str, "%H:%M")
        if is_off_time and dt.strftime("%H:%M") in ["0:00", "00:00"]:
            return "23:59"
        return dt.strftime("%H:%M")
    except ValueError:
        pass

    raise ValueError(f"Time format for {time_str} is not recognized.")


def parse_validity_hour(text: str, is_end: bool) -> Optional[int]:
    """
    The hour of the validity of an asset, as the server keeps it: a whole number, 0-23 for the start and 1-24 for the
    end (a text like "08:00" is refused by the server). "8", "08" and "08:00" are taken; an end of "00:00" is the end
    of the day. Empty is None; anything else (minutes, a letter) raises ValueError.
    """
    text = text.strip()
    if not text:
        return None
    match = re.fullmatch(r"([0-9]{1,2})(?::00)?", text)
    if not match:
        raise ValueError(text)
    hour = int(match.group(1))
    if is_end and hour == 0:
        hour = 24
    if not (1 if is_end else 0) <= hour <= (24 if is_end else 23):
        raise ValueError(text)
    return hour


class FormatException(Exception):
    """Format of loaded data is wrong."""
    pass


class InternalException(Exception):
    """Internal error raised"""
    pass


@dataclass
class Response:
    """
    A data structure for holding response information.

    Attributes
    ----------
    code : int
        The HTTP status code from the response.
    response_msg : json
        The JSON response message containing server data.
    """
    code: int
    response_msg: json


class ProcessorFactory:
    @staticmethod
    def create_processor(processor_type, logger, url, login, password, lang, **kwargs):
        processor_map = {
            "player_group": PlayerGroupProcessor,
            "detailed_playlist": DetailedPlaylistProcessor,
            "playlist": PlaylistProcessor,
            "asset_to_playlist": AssetToPlaylistProcessor,
            "player_note": PlayerNoteProcessor,
            "player_snapshot": PlayerSnapshotProcessor,
            "remove_playlists": RemovePlaylistsProcessor,
            "remove_playlist_list": RemovePlaylistsByListProcessor,
            "remove_assets": RemoveAssetsProcessor,
            "player_config_location": PlayerConfigLocationProcessor,
            "group_rename": GroupRenameProcessor,
            "player_rename": PlayerRenameProcessor,
            "playlist_rename": PlaylistRenameProcessor,
            "location_rename": LocationRenameProcessor,
            "location_plan": LocationTimesProcessor,
            "player_labels": PlayerLabelsProcessor,
            "group_settings": GroupSettingsProcessor,
            "playlist_settings": PlaylistSettingsProcessor,
            # "add_playlist": AddPlaylistProcessor,
            "add_detailed_playlist": AddDetailedPlaylistProcessor,
            "remove_expired_playlists": RemoveExpiredPlaylistsProcessor,
            "remove_all_expired_playlists": RemoveAllExpiredPlaylistsProcessor,
            "create_location": CreateLocationProcessor,
            "create_group": CreateGroupProcessor,
            "create_player": CreatePlayerProcessor,
            "create_playlist": CreatePlaylistProcessor,
            "create_label": CreateLabelProcessor,
            "remove_unused_groups": RemoveUnusedGroupsProcessor,
            "remove_unused_playlists": RemoveUnusedPlaylistsProcessor,
            "remove_unused_assets": RemoveUnusedAssetsProcessor,
            "remove_unused_labels": RemoveUnusedLabelsProcessor,
            "remove_unused_locations": RemoveUnusedLocationsProcessor,
            "clone_player": PlayerDetailsCloneProcessor,
            "remove_additional_playlists": DeleteAdditionalPlaylistProcessor,
            "remove_all_unused_groups": RemoveAllUnusedGroupsProcessor,
            "remove_all_unused_playlists": RemoveAllUnusedPlaylistsProcessor,
            "remove_all_unused_assets": RemoveAllUnusedAssetsProcessor,
            "remove_all_unused_labels": RemoveAllUnusedLabelsProcessor,
            "remove_all_unused_locations": RemoveAllUnusedLocationsProcessor,
            "asset_validity": AssetValidityProcessor,
            "player_update": PlayerUpdateProcessor,
            "deploy_all_players": DeployAllPlayersProcessor,
            "deploy_selected_groups": DeploySelectedGroupsProcessor
        }
        processor_class = processor_map.get(processor_type)
        if not processor_class:
            raise ValueError(f"Unknown processor type: {processor_type}")
        return processor_class(logger, url=url, login=login, password=password, lang=lang, **kwargs)


@dataclass(frozen=True)
class Confirmation:
    """What the user is asked, before an action that cannot be undone starts."""
    title: str
    text: str


# How many of the names an action is about to delete or the groups it deploys to are listed in a question
CONFIRM_LIST_LIMIT = 15


class InputProcessor(ABC):
    def __init__(self, log_handler, *, url: str, login: str, password: str, lang):
        self._logger = log_handler
        self._login_info = {
            "login": login,
            "password": password,
            "url": url + "/api"
        }
        self._wrong_init_counter = 0
        self._same_key = {}
        self.data = {}
        self.lang = lang

    @abstractmethod
    def load(self, input_text: str):
        pass

    @abstractmethod
    def run(self) -> Generator[None, None, None]:
        pass

    def confirmation(self) -> Optional[Confirmation]:
        """The question to ask the user between `load` and `run`; None = this action asks nothing."""
        return None

    def _list_for_question(self, names: List[str]) -> str:
        """The names for a question, one per line; a long list is cut and the rest is only counted."""
        lines = [f"• {name}" for name in names[:CONFIRM_LIST_LIMIT]]
        if len(names) > CONFIRM_LIST_LIMIT:
            lines.append(self.lang.get_message("confirm_more", count=len(names) - CONFIRM_LIST_LIMIT))
        return "\n".join(lines)

    def _write_log(self, key_word: str, **kwargs):
        self._logger.info(self.lang.get_message(key_word, **kwargs))

    def _write_log_warning(self, key_word: str, **kwargs):
        self._logger.warning(self.lang.get_message(key_word, **kwargs))

    def _write_log_error(self, key_word: str, **kwargs):
        self._logger.error(self.lang.get_message(key_word, **kwargs))

    def _write_start_loading(self):
        self._logger.info(self.lang.get_message("start_loading"))

    def _write_load_finish(self):
        self._logger.info(self.lang.get_message("load_finished"))

    def _write_wrong_format(self, n: int):
        self._logger.error(self.lang.get_message("wrong_format", n=n))

    def _write_fail_response(self, code: int):
        self._logger.warning(self.lang.get_message("fail_response", code=code))

    def _write_connection_error(self):
        self._logger.error(self.lang.get_message("connection_error"))

    def _write_incorrect_login_error(self):
        self._logger.error(self.lang.get_message("incorrect_login"))

    def _write_incorrect_format(self, line_number: int):
        self._logger.error(self.lang.get_message("incorrect_format", line_number=line_number))

    def _write_empty_keyword(self, line_number: int):
        self._logger.error(self.lang.get_message("empty_keyword", line_number=line_number))

    def _write_name_fail(self, line_number: int, name: str):
        self._logger.warning(self.lang.get_message("name_fail", line_number=line_number, name=name))

    def _write_collision(self, line_number: int, key: str):
        self._logger.warning(self.lang.get_message("collision", line_number=line_number, key_col=key))

    def _write_success_assign(self, line_num: int, entity_name: str, assigned_name: str):
        self._logger.info(self.lang.get_message("success_assign",
                                                line_num=line_num,
                                                entity_name=entity_name,
                                                assigned_name=assigned_name))

    def _write_error_assign(self, line_num: int, code: int):
        self._logger.warning(self.lang.get_message("error_assign", line_num=line_num, code=code))
        
    def _write_request_error(self, entity: str | None):
        self._logger.error(self.lang.get_message("request_con_error", entity=entity))

    def _write_request_error(self, entity: str | None):
        self._logger.error(self.lang.get_message("request_con_error", entity=entity))

    def _write_recognition_errors(self, n: int):
        self._logger.error(self.lang.get_message("recognition_errors", n=n))

    def _write_internal_error(self, exception: Exception):
        self._logger.error(self.lang.get_message("internal_error", error_msg=str(exception)))

    def _write_no_server_returned(self):
        self._logger.error(self.lang.get_message("no_server_returned"))

    def _write_invalid_time_format(self, line_num: int, invalid_time: str):
        self._logger.warning(self.lang.get_message("invalid_time_format", line_num=line_num, time_str=invalid_time))

    def _write_not_new_name(self, line_num: int, name: str):
        self._logger.error(self.lang.get_message("not_new", line_num=line_num, name=name))

    def _write_same_assign(self, assignment_dict):
        for key, assignments in assignment_dict.items():
            self._logger.info(self.lang.get_message("same_assign", key_err=key, assignments=assignments))
        self._logger.error(self.lang.get_message("total_collisions", n=len(assignment_dict)))

    @staticmethod
    def _validate_date_format(date_str: str) -> bool:
        try:
            datetime.strptime(date_str, "%d.%m.%Y")
            return True
        except ValueError:
            return False

    @staticmethod
    def _validate_time_format(time_str: str) -> bool:
        if not time_str:
            return True
        try:
            datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

    def _try_server_login(self) -> Optional[ServerApi]:
        try:
            server = ServerApi(**self._login_info)
            if server.redirected_to and not getattr(self, "_main_account_said", False):
                self._main_account_said = True  # once, not at every login of the action
                self._logger.info(self.lang.get_message("main_account_used", host=urlparse(server.redirected_to).netloc))
            return server
        except requests.exceptions.ConnectionError:
            self._wrong_init_counter += 1
            self._write_connection_error()
        except LoginError:
            self._wrong_init_counter += 1
            self._write_incorrect_login_error()
        except ResponseError as error:  # the server answered the login with an error of its own
            self._wrong_init_counter += 1
            self._write_fail_response(error.status or 4004)
        except requests.exceptions.RequestException as ex:
            self._wrong_init_counter += 1
            if ex.response is not None:  # a response of 4xx/5xx is falsy
                self._write_fail_response(ex.response.status_code)
            else:
                self._write_fail_response(4004)
        return None

    def _retrieve_names(self, server, *args) -> Optional[Dict[str, List[str]]]:
        names = {}
        try:
            for arg in args:
                if arg == 'player_names':
                    names['player_names'] = server.get_player_names()
                elif arg == 'group_names':
                    names['group_names'] = server.get_group_names()
                elif arg == 'playlist_names':
                    names['playlist_names'] = server.get_playlist_names()
                elif arg == 'label_names':
                    names['label_names'] = server.get_labels()
                elif arg == 'existing_locations':
                    names['existing_locations'] = server.get_location_names()
                elif arg == 'asset_names':
                    names['asset_names'] = server.get_asset_names()
        except requests.exceptions.RequestException as ex:
            self._wrong_init_counter += 1
            if ex.response is not None:  # a response of 4xx/5xx is falsy
                self._write_fail_response(ex.response.status_code)
            else:
                self._write_fail_response(4004)
            return None
        return names

    @staticmethod
    def _indexed_rows(input_text: str, make_row=None, keep_repeats: bool = False) -> List[Tuple[int, Any]]:
        """
        The lines of the input that have something in them, as (index, row) in the order they were written. The index
        counts from 0, so `index + 1` is the number of the line as the person sees it. A row that repeats is read once,
        unless `keep_repeats` (for the actions that report a repeated name themselves). `make_row` turns a line into the
        row (a text, a tuple of cells); the default is the line itself.
        """
        seen, rows = set(), []
        for index, line in enumerate(input_text.split('\n')):
            row = make_row(line) if make_row else line
            if not line.strip() or not row:
                continue
            if not keep_repeats:
                if row in seen:
                    continue
                seen.add(row)
            rows.append((index, row))
        return rows

    def _numbered_lines(self, input_text: str) -> List[Tuple[int, str]]:
        """The lines that have something in them with their number as the user sees it (the first is 1)."""
        return [(index + 1, row) for index, row in self._indexed_rows(input_text)]

    @staticmethod
    def _blocks(cells: List[str], size: int) -> List[List[str]]:
        """
        The cells that follow the fixed columns of a line, cut into blocks of `size` cells counted from the first of
        them. The last block is completed with empty cells and blocks with nothing in them are dropped, so a block
        never takes cells of its neighbour.
        """
        padded = cells + [""] * (-len(cells) % size)
        return [block for block in (padded[i:i + size] for i in range(0, len(padded), size)) if any(block)]

    @staticmethod
    def _end_time_parse(end_time: str) -> str:
        return end_time if end_time != "0:00" else "23:59"

    @staticmethod
    def _pad_list(lst: List[str], pad_to: int) -> List[str]:
        n = (pad_to - (len(lst))) % pad_to
        return lst + [""] * n


class EntityValidationProcessor(InputProcessor, ABC):
    entity_type: str = None  # Must be set in subclasses

    def _validate_entity(self, entity: str, entity_list: List[str], line_num: int) -> bool:
        if entity not in entity_list:
            self._write_log_warning("name_fail", line_number=line_num, name=entity)
            self._wrong_init_counter += 1
            return False
        return True

    def load(self, input_text: str):
        try:
            self._write_start_loading()
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return

            names = self._retrieve_names(server, self.entity_type)
            if not names:
                self._write_no_server_returned()
                return

            self.data = []

            for i, entity in self._indexed_rows(input_text, str.strip):
                if not self._validate_entity(entity, names[self.entity_type], i + 1):
                    continue

                if entity in self.data:
                    self._write_collision(i + 1, entity)
                    self._wrong_init_counter += 1
                    continue

                self.data.append(entity)

            if self._wrong_init_counter > 0:
                self._write_wrong_format(self._wrong_init_counter)
                raise FormatException

            self._write_load_finish()
            if not self.data:
                self._write_wrong_format(1)
                raise FormatException
        except FormatException:  # reported already, not an internal error
            raise
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()


class AssignProcessor(EntityValidationProcessor):
    data: Dict[str, Any]

    @abstractmethod
    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        pass

    def run(self) -> Generator[None, None, None]:
        try:
            i = 0
            with self._try_server_login() as server:
                if not server:
                    self._write_no_server_returned()
                    return
                for response in self._assign_stepwise(server):
                    i += 1
                    if response.code == 200:
                        response_msg = response.response_msg["data"]
                        entity = response_msg["name"]
                        assigned_name = self.data[entity]
                        self._write_success_assign(i, entity, assigned_name)
                    else:
                        self._write_error_assign(i, response.code)
                    yield
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()


class CreateProcessor(EntityValidationProcessor):
    @abstractmethod
    def _create_method(self, server, entity_name: str) -> Response:
        pass

    def run(self) -> Generator[None, None, None]:
        try:
            with self._try_server_login() as server:
                if not server:
                    self._write_no_server_returned()
                    return
                for entity_name in self.data:
                    self._create_entity(server, entity_name)
                    yield
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    def _create_entity(self, server, entity_name: str):
        try:
            response = self._create_method(server, entity_name)
            if response.code == 200:
                self._write_success_create(entity_name)
            else:
                self._write_error_create(entity_name, response.code)
        except Exception as e:
            self._write_internal_error(e)

    def _write_success_create(self, entity_name: str):
        self._logger.info(self.lang.get_message("success_create", entity_name=entity_name))

    def _write_error_create(self, entity_name: str, code: int):
        self._logger.error(self.lang.get_message("error_create", entity_name=entity_name, code=code))

    def _write_not_new_name(self, line_num: int, name: str):
        self._logger.error(self.lang.get_message("not_new", line_num=line_num, name=name))

    @staticmethod
    def check_name(line: str, pattern: re.Pattern) -> bool:
        return bool(pattern.findall(line))

    def load(self, input_text: str):
        pattern = re.compile(r"[\t\n;ěščřžýáíéß]", re.IGNORECASE)
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, self.entity_type)
        if not names:
            self._write_no_server_returned()
            return

        self.data = []

        for i, line_strip in self._indexed_rows(input_text, str.strip):
            if line_strip in names[self.entity_type]:
                self._write_not_new_name(i + 1, line_strip)
                self._wrong_init_counter += 1
                continue

            if line_strip in self.data:
                self._write_collision(i + 1, line_strip)
                self._wrong_init_counter += 1
                continue

            if self.check_name(line_strip, pattern):
                self._write_name_fail(i + 1, line_strip)
                self._wrong_init_counter += 1

            self.data.append(line_strip)

        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

        self._write_load_finish()
        if not self.data:
            self._write_wrong_format(1)
            raise FormatException


class RemoveProcessor(EntityValidationProcessor):
    skip_names: Set[str]

    @abstractmethod
    def _remove_method(self, server, entity_name: str) -> Response:
        pass

    @abstractmethod
    def _label_method(self, server: ServerApi):
        pass

    @staticmethod
    def get_labeled_test(server_method):
        labels = {"".join(letters) for letters in itertools.product(*((c.lower(), c.upper()) for c in "test"))}
        labeled_entities = []
        for label in labels:
            labeled_entities += server_method(label)
        return set(labeled_entities)

    def skip_check(self, entity):
        return entity in self.skip_names

    def _prepare(self, server: ServerApi):
        """Called with the logged-in server right before the first entity is removed."""

    def run(self) -> Generator[None, None, None]:
        entity_name = None
        try:
            with self._try_server_login() as server:
                if not server:
                    self._write_no_server_returned()
                    return
                method = self._label_method(server)
                self.skip_names = self.get_labeled_test(method)
                self._prepare(server)
                for entity_name in self.data:
                    if self.skip_check(entity_name):
                        self._write_skipping(entity_name)
                        continue
                    self._remove_entity(server, entity_name)
                    yield
        except requests.exceptions.RequestException as e:
            self._wrong_init_counter += 1
            self._write_request_error(entity_name)
            raise InternalException()
        except Exception as e:
            self._write_internal_error(e)
            self._wrong_init_counter += 1
            raise InternalException()

    def _remove_entity(self, server, entity_name: str):
        try:
            response = self._remove_method(server, entity_name)
            if response.code == 200:
                self._write_success_remove(entity_name)
            else:
                self._write_error_remove(entity_name, response.code)
        except Exception as e:
            self._write_internal_error(e)

    def _write_success_remove(self, entity_name: str):
        self._logger.info(self.lang.get_message("success_remove", entity_name=entity_name))

    def _write_error_remove(self, entity_name: str, code: int):
        self._logger.error(self.lang.get_message("error_remove", entity_name=entity_name, code=code))

    def _write_skipping(self, entity_name: str):
        self._logger.warning(self.lang.get_message("skipping", entity_name=entity_name))


class RemoveByKeywordProcessor(RemoveProcessor, ABC):
    entity_type = None  # Must be set in subclasses
    # The message of a success in assets/messages.json and the names it gives to the entity and to what was removed
    success_message: Tuple[str, str, str] = ("success_remove_entity", "entity", "removed_items")

    @abstractmethod
    def _remove_method(self, server, entity_name: str, keyword: str) -> Response:
        pass

    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, self.entity_type)
        if not names:
            self._write_no_server_returned()
            return

        entity_keywords = {}
        for i, line in self._indexed_rows(input_text):
            split_line = line.split("\t")
            if len(split_line) != 2:
                self._wrong_init_counter += 1
                self._write_incorrect_format(i + 1)
                continue

            entity_name, keyword = split_line[0], split_line[1]
            if not keyword.strip():  # "" is contained in every name: it would remove everything
                self._wrong_init_counter += 1
                self._write_empty_keyword(i + 1)
                continue
            if not self._validate_entity(entity_name, names[self.entity_type], i + 1):
                continue

            entity_keywords[entity_name] = keyword
        self.data = entity_keywords

        self._write_load_finish()
        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

    def run(self) -> Generator[None, None, None]:
        try:
            i = 0
            with self._try_server_login() as server:
                if not server:
                    self._write_no_server_returned()
                    return
                for entity_name, keyword in self.data.items():
                    response = self._remove_method(server, entity_name, keyword)
                    i += 1
                    if response.code == 200:
                        response_msg = response.response_msg
                        self._write_success_remove(i, entity_name, response_msg["removed_items"])
                    else:
                        self._write_error_assign(i, response.code)
                    yield
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    def _write_success_remove(self, line_num: int, entity_name: str, removed_items: List[str]):
        key, entity_field, items_field = self.success_message
        self._logger.info(self.lang.get_message(
            key, line_num=line_num, **{entity_field: entity_name, items_field: removed_items}))


class RenameProcessor(EntityValidationProcessor, ABC):
    entity_type = None  # Must be set in subclasses
    data: Dict[str, Any]

    @abstractmethod
    def _rename_method(self, server, old_name: str, new_name: str) -> json:
        pass

    @abstractmethod
    def _new_name_error(self, old_name: str, new_name: str) -> Optional[str]:
        """The key of the message that says why new_name is not acceptable, None if it is."""
        pass

    @abstractmethod
    def _invalid_name_message_key(self) -> str:
        pass

    @abstractmethod
    def _success_rename_message_key(self) -> str:
        pass

    def load(self, input_text: str):
        try:
            self.data = {}
            self._write_start_loading()
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return

            names = self._retrieve_names(server, self.entity_type)
            if not names:
                self._write_no_server_returned()
                return

            unrecognized_name_counter = 0
            loaded_old_name = set()
            loaded_new_name = set()
            for line_num, line in self._numbered_lines(input_text):
                split_line = line.split("\t")
                if len(split_line) != 2:
                    self._wrong_init_counter += 1
                    self._write_incorrect_format(line_num)
                    continue

                old_name, new_name = split_line[0], split_line[1]
                if not self._validate_entity(old_name, names[self.entity_type], line_num):
                    unrecognized_name_counter += 1
                    continue

                if old_name in loaded_old_name:  # two new names for one: which one is meant?
                    self._write_collision(line_num, old_name)
                    self._wrong_init_counter += 1
                    continue

                error_key = self._new_name_error(old_name, new_name)
                if error_key:
                    self._write_invalid_name(error_key, line_num, old_name, new_name)
                    self._wrong_init_counter += 1
                    continue

                if (new_name in names[self.entity_type] and new_name != old_name) or new_name in loaded_new_name:
                    self._write_invalid_name(self._invalid_name_message_key(), line_num, old_name, new_name)
                    self._wrong_init_counter += 1
                    continue

                self.data[old_name] = new_name
                loaded_old_name.add(old_name)
                loaded_new_name.add(new_name)

            self._write_load_finish()
            if self._wrong_init_counter > 0 or unrecognized_name_counter > 0:
                self._write_wrong_format(self._wrong_init_counter)
                self._write_recognition_errors(unrecognized_name_counter)
                raise FormatException
        except FormatException:  # reported already, not an internal error
            raise
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    def run(self) -> Generator[None, None, None]:
        try:
            i = 0
            with self._try_server_login() as server:
                if not server:
                    self._write_no_server_returned()
                    return
                for response in self._rename_stepwise(server):
                    i += 1
                    if response.code == 200:
                        response_msg = response.response_msg["data"]
                        old_name = response_msg["old_name"]
                        new_name = response_msg["name"]
                        self._write_success_rename(i, old_name, new_name)
                    else:
                        self._write_error_assign(i, response.code)
                    yield
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    def _rename_stepwise(self, server) -> Generator[Response, None, None]:
        for old_name, new_name in self.data.items():
            response = self._rename_method(server, old_name, new_name)
            response["data"]["old_name"] = old_name
            yield Response(200, response)

    def _write_invalid_name(self, message_key: str, line_num: int, old_name: str, new_name: str):
        self._logger.error(
            self.lang.get_message(message_key,
                                  line_num=line_num,
                                  old_name=old_name,
                                  new_name=new_name))

    def _write_success_rename(self, line_num: int, old_name: str, new_name: str):
        self._logger.info(
            self.lang.get_message(self._success_rename_message_key(),
                                  line_num=line_num,
                                  old_name=old_name,
                                  new_name=new_name))


class PlayerGroupProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'player_names', 'group_names')
        if not names:
            self._write_no_server_returned()
            return

        unrecognized_name_counter = 0
        for i, line in self._indexed_rows(input_text):
            split_line = line.split("\t")
            if len(split_line) != 2:
                self._wrong_init_counter += 1
                self._write_incorrect_format(i + 1)
                continue

            key, item = split_line[0], split_line[1]
            if key not in names['player_names'] or item not in names['group_names']:
                self._write_name_fail(i + 1, key if key not in names['player_names'] else item)
                unrecognized_name_counter += 1
                continue

            if key in self.data:
                self._write_collision(i + 1, key)
                self._same_key.setdefault(key, []).append(item)
            else:
                self.data[key] = item

        self._write_load_finish()
        if self._wrong_init_counter > 0 or unrecognized_name_counter > 0 or self._same_key:
            self._write_wrong_format(self._wrong_init_counter)
            self._write_recognition_errors(unrecognized_name_counter)
            self._write_same_assign(self._same_key)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for key, item in self.data.items():
            response = server.set_group_to_player(item, key)
            yield Response(200, response)


class DetailedPlaylistProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'group_names', 'playlist_names')
        if not names:
            self._write_no_server_returned()
            return

        group_playlists = {}
        loaded_groups = set()
        for line_num, line in self._numbered_lines(input_text):
            cells = line.split("\t")
            group = cells[0]
            if not self._validate_entity(group, names['group_names'], line_num):
                continue

            if group in loaded_groups:
                self._write_collision(line_num, group)
                self._wrong_init_counter += 1

            loaded_groups.add(group)
            playlists = []

            default_playlist = cells[1] if len(cells) > 1 else ""
            if default_playlist in names['playlist_names']:
                playlists = [(default_playlist, None, None, None, None, None)]
            elif default_playlist:  # dropping it quietly would write the group without the playlist it plays by default
                self._wrong_init_counter += 1
                self._write_name_fail(line_num, default_playlist)
                continue

            playlists.extend(self._validated_blocks(line_num, group, cells[2:], names['playlist_names']))

            if group in group_playlists:
                group_playlists[group].extend(playlists)
            else:
                group_playlists[group] = playlists
        self.data = group_playlists

        self._write_load_finish()
        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for group in self.data.keys():
            playlists = self.data[group]
            response = server.set_playlist_to_group_detailed(group, playlists)
            yield Response(200, response)

    def _validated_blocks(self, line_num: int, group: str, cells: List[str], playlist_names: List[str]) -> List[Tuple]:
        playlists = []
        for block_number, block in enumerate(self._blocks(cells, 6), 1):
            if not block[0]:  # times without a playlist would otherwise be read as the ones of another
                self._wrong_init_counter += 1
                self._write_missing_playlist_name(line_num, group, block_number)
                continue
            playlist_data = self._validate_playlist_data(line_num, group, block, playlist_names)
            if playlist_data:
                playlists.append(playlist_data)
        return playlists

    def _write_missing_playlist_name(self, line_num: int, group: str, block_number: int):
        self._logger.error(self.lang.get_message("missing_playlist_name", line_num=line_num, group=group,
                                                 block_number=block_number))

    def _validate_playlist_data(self, line_num, group, data, playlist_names):
        playlist_name, start_date, end_date, weekdays, start_time, end_time = data
        try:
            end_time = normalize_time_format(end_time, is_off_time=True)
            start_time = normalize_time_format(start_time)
        except ValueError as e:
            self._wrong_init_counter += 1
            self._write_invalid_time(line_num, group, playlist_name, str(e))
            return None

        if playlist_name not in playlist_names:
            self._wrong_init_counter += 1
            self._write_name_fail(line_num, playlist_name)
            return None

        if not self._validate_dates(start_date, end_date, line_num, group, playlist_name):
            return None

        weekdays = self._validate_weekdays(weekdays, line_num, group, playlist_name)
        if weekdays is None:
            return None

        if not self._validate_times(start_time, end_time, line_num, group, playlist_name):
            return None

        return (playlist_name, legible_to_iso(start_date), legible_to_iso(end_date),
                weekdays, start_time, end_time)

    def _validate_dates(self, start_date, end_date, line_num, group, playlist_name):
        if start_date and not self._validate_date_format(start_date):
            self._write_invalid_date(line_num, group, playlist_name, start_date)
            self._wrong_init_counter += 1
            return False
        elif end_date and not self._validate_date_format(end_date):
            self._write_invalid_date(line_num, group, playlist_name, end_date)
            self._wrong_init_counter += 1
            return False
        elif start_date and end_date and not compare_date(start_date, end_date):
            self._write_date_order_error(line_num, group, playlist_name, start_date, end_date)
            self._wrong_init_counter += 1
            return False
        return True

    def _validate_weekdays(self, weekdays_str, line_num, group, playlist_name):
        weekdays = split_list(weekdays_str) if weekdays_str else []
        weekdays = convert_days_of_week_to_int(weekdays)
        if not self._validate_weekdays_format(weekdays):
            self._write_invalid_weekdays(line_num, group, playlist_name, weekdays_str)
            self._wrong_init_counter += 1
            return None
        return [int(day) for day in weekdays]

    @staticmethod
    def _validate_weekdays_format(weekdays):
        try:
            return all(1 <= int(day) <= 7 for day in weekdays)
        except ValueError:
            return False

    def _validate_times(self, start_time, end_time, line_num, group, playlist_name):
        if not self._validate_time_format(start_time):
            self._write_invalid_time(line_num, group, playlist_name, start_time)
            self._wrong_init_counter += 1
            return False
        if not self._validate_time_format(end_time):
            self._write_invalid_time(line_num, group, playlist_name, end_time)
            self._wrong_init_counter += 1
            return False
        if start_time and end_time and not compare_time(start_time, end_time):
            self._write_time_order_error(line_num, group, playlist_name, start_time, end_time)
            self._wrong_init_counter += 1
            return False
        return True

    def _write_invalid_date(self, line_num: int, group: str, playlist: str, invalid_date: str):
        self._logger.error(self.lang.get_message("invalid_date",
                                                 line_num=line_num,
                                                 group=group,
                                                 playlist=playlist,
                                                 invalid_date=invalid_date))

    def _write_date_order_error(self, line_num: int, group: str, playlist: str, start_date: str, end_date: str):
        self._logger.error(self.lang.get_message("date_order_error",
                                                 line_num=line_num,
                                                 group=group,
                                                 playlist=playlist,
                                                 start_date=start_date,
                                                 end_date=end_date))

    def _write_invalid_weekdays(self, line_num: int, group: str, playlist: str, invalid_weekdays: list):
        self._logger.error(self.lang.get_message("invalid_weekdays",
                                                 line_num=line_num,
                                                 group=group,
                                                 playlist=playlist,
                                                 invalid_weekdays=invalid_weekdays))

    def _write_invalid_time(self, line_num: int, group: str, playlist: str, invalid_time: str):
        self._logger.error(self.lang.get_message("invalid_time",
                                                 line_num=line_num,
                                                 group=group,
                                                 playlist=playlist,
                                                 invalid_time=invalid_time))

    def _write_time_order_error(self, line_num: int, group: str, playlist: str, start_time: str, end_time: str):
        self._logger.error(self.lang.get_message("time_order_error_group",
                                                 line_num=line_num,
                                                 group=group,
                                                 playlist=playlist,
                                                 start_time=start_time,
                                                 end_time=end_time))


class PlaylistProcessor(AssignProcessor):
    """Deprecated version of playlist processor without weekdays."""

    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'group_names', 'playlist_names')
        if not names:
            self._write_no_server_returned()
            return

        group_playlists = {}
        loaded_groups = set()
        for i, line in self._indexed_rows(input_text, keep_repeats=True):
            split_line = line.split("\t")
            split_line += [""] * (2 - len(split_line))  # a line with the group only
            group = split_line[0]
            if not self._validate_entity(group, names['group_names'], i + 1):
                continue

            if group in loaded_groups:
                self._write_collision(i + 1, group)
                self._wrong_init_counter += 1

            loaded_groups.add(group)

            if split_line[1] in names['playlist_names']:
                playlists = [(split_line[1], None, None, None, None)]
            else:
                self._wrong_init_counter += 1
                self._write_name_fail(i + 1, split_line[1])
                continue
            for data in self._blocks(split_line[2:], 5):
                playlist_data = self._validate_playlist_data(i + 1, group, data, names['playlist_names'])
                if playlist_data:
                    playlists.append(playlist_data)

            if group in group_playlists:
                group_playlists[group].extend(playlists)
            else:
                group_playlists[group] = playlists

        self.data = group_playlists

        self._write_load_finish()
        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for group in self.data.keys():
            playlists = self.data[group]
            response = server.set_playlist_to_group(group, playlists)
            yield Response(200, response)

    def _validate_playlist_data(self, line_num: int, group: str, data: List[str], playlist_names: List[str]) \
            -> Optional[Tuple]:
        playlist_name, start_date, end_date, start_time, end_time = data
        try:
            end_time = normalize_time_format(end_time, is_off_time=True)
            start_time = normalize_time_format(start_time)
        except ValueError as e:
            self._wrong_init_counter += 1
            self._write_invalid_time(line_num, group, playlist_name, str(e))
            return None

        if playlist_name not in playlist_names:
            self._wrong_init_counter += 1
            self._write_name_fail(line_num, playlist_name)
            return None

        if not self._validate_dates(start_date, end_date, line_num, group, playlist_name):
            return None

        if not self._validate_times(start_time, end_time, line_num, group, playlist_name):
            return None

        return playlist_name, legible_to_iso(start_date), legible_to_iso(end_date), start_time, end_time

    def _validate_dates(self, start_date: str, end_date: str, line_num: int, group: str, playlist_name: str) -> bool:
        if start_date and not self._validate_date_format(start_date):
            self._write_invalid_date(line_num, group, playlist_name, start_date)
            self._wrong_init_counter += 1
            return False
        elif end_date and not self._validate_date_format(end_date):
            self._write_invalid_date(line_num, group, playlist_name, end_date)
            self._wrong_init_counter += 1
            return False
        elif start_date and end_date and not compare_date(start_date, end_date):
            self._write_date_order_error(line_num, group, playlist_name, start_date, end_date)
            self._wrong_init_counter += 1
            return False
        return True

    def _validate_times(self, start_time: str, end_time: str, line_num: int, group: str, playlist_name: str) -> bool:
        if not self._validate_time_format(start_time):
            self._write_invalid_time(line_num, group, playlist_name, start_time)
            self._wrong_init_counter += 1
            return False
        if not self._validate_time_format(end_time):
            self._write_invalid_time(line_num, group, playlist_name, end_time)
            self._wrong_init_counter += 1
            return False
        if start_time and end_time and not compare_time(start_time, end_time):
            self._write_time_order_error(line_num, group, playlist_name, start_time, end_time)
            self._wrong_init_counter += 1
            return False
        return True

    def _write_invalid_date(self, line_num: int, group: str, playlist: str, invalid_date: str):
        self._logger.error(self.lang.get_message("invalid_date",
                                                 line_num=line_num,
                                                 group=group,
                                                 playlist=playlist,
                                                 invalid_date=invalid_date))

    def _write_date_order_error(self, line_num: int, group: str, playlist: str, start_date: str, end_date: str):
        self._logger.error(self.lang.get_message("date_order_error",
                                                 line_num=line_num,
                                                 group=group,
                                                 playlist=playlist,
                                                 start_date=start_date,
                                                 end_date=end_date))

    def _write_invalid_time(self, line_num: int, group: str, playlist: str, invalid_time: str):
        self._logger.error(self.lang.get_message("invalid_time",
                                                 line_num=line_num,
                                                 group=group,
                                                 playlist=playlist,
                                                 invalid_time=invalid_time))

    def _write_time_order_error(self, line_num: int, group: str, playlist: str, start_time: str, end_time: str):
        self._logger.error(self.lang.get_message("time_order_error_group",
                                                 line_num=line_num,
                                                 group=group,
                                                 playlist=playlist,
                                                 start_time=start_time,
                                                 end_time=end_time))


class AssetToPlaylistProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'playlist_names', 'asset_names')
        if not names:
            self._write_no_server_returned()
            return

        playlist_assets = {}
        for line_num, line in self._numbered_lines(input_text):
            split_line = tuple(j for j in line.split("\t") if j)
            if not split_line:
                continue
            playlist_name = split_line[0]
            if not self._validate_entity(playlist_name, names['playlist_names'], line_num):
                continue

            # a misspelt name would put a file into the playlist that does not exist
            assets = [asset for asset in self._validate_assets(list(split_line[1:]))
                      if self._validate_entity(asset, names['asset_names'], line_num)]
            if assets:
                if playlist_name in playlist_assets:
                    playlist_assets[playlist_name].extend(assets)
                else:
                    playlist_assets[playlist_name] = assets
        self.data = playlist_assets

        self._write_load_finish()
        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for playlist in self.data.keys():
            assets = self.data[playlist]
            response = server.set_assets_to_playlist(playlist, assets)
            yield Response(200, response)

    @staticmethod
    def _validate_assets(assets: List[str]) -> List[str]:
        return [asset_name for asset_name in assets if asset_name != ""]


class PlayerNoteProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'player_names')
        if not names:
            self._write_no_server_returned()
            return

        for i, line in self._indexed_rows(input_text, lambda text: convert(self._pad_list(text.split("\t"), 2))):
            split_line = line
            if len(split_line) != 2:
                self._wrong_init_counter += 1
                self._write_incorrect_format(i + 1)
            else:
                player, note = split_line[0], split_line[1]
                if not self._validate_entity(player, names['player_names'], i + 1):
                    continue

                self.data[player] = note

        self._write_load_finish()
        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for player, note in self.data.items():
            response = server.set_player_note(player, note)
            yield Response(200, response)


class PlayerSnapshotProcessor(EntityValidationProcessor):
    """Saves a screenshot of what each of the named players is playing right now."""
    entity_type = "player_names"

    def __init__(self, *args, output_dir: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_dir = output_dir

    def run(self) -> Generator[None, None, None]:
        try:
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return
            os.makedirs(self.output_dir, exist_ok=True)
            with server:
                for player in self.data:
                    self._save_snapshot(server, player)
                    yield
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    def _save_snapshot(self, server: ServerApi, player: str):
        # Only a reason is logged, never the exception text
        try:
            image, extension = server.download_snapshot(server.take_player_snapshot(player)["url"])
        except (SnapshotError, ResponseError, NameResolutionError, requests.exceptions.RequestException, KeyError,
                TypeError) as e:
            self._write_snapshot_failed(player, self.lang.get_message(f"snapshot_reason_{snapshot_reason(e)}"))
            return

        stem = os.path.join(self.output_dir, snapshot_file_stem(player, datetime.now()))
        for attempt in count():  # two names can end up as the same file name ("a b" and "a_b")
            path = f"{stem}{extension}" if attempt == 0 else f"{stem}_{attempt}{extension}"
            try:
                with open(path, "xb") as file:
                    file.write(image)
                break
            except FileExistsError:
                continue
        self._write_log("snapshot_saved", player=player, path=path)

    def _write_snapshot_failed(self, player: str, reason: str):
        self._write_log_error("snapshot_failed", player=player, reason=reason)


class PlayerConfigLocationProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'player_names', 'existing_locations')
        if not names:
            self._write_no_server_returned()
            return

        unrecognized_name_counter = 0
        already_assigned = set()
        for i, line in self._indexed_rows(input_text, lambda text: convert(text.split("\t"))):
            split_line = line
            if len(split_line) != 2:
                self._wrong_init_counter += 1
                self._write_incorrect_format(i + 1)
            else:
                player, config_location = split_line[0], split_line[1]
                if not self._validate_entity(player, names['player_names'], i + 1):
                    unrecognized_name_counter += 1
                    continue
                if player in already_assigned:
                    self._wrong_init_counter += 1
                    self._write_collision(i + 1, player)
                    continue

                if not self._validate_entity(config_location, names['existing_locations'], i + 1):
                    unrecognized_name_counter += 1
                    continue

                self.data[player] = config_location
                already_assigned.add(player)

        self._write_load_finish()
        if self._wrong_init_counter > 0 or unrecognized_name_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            self._write_recognition_errors(unrecognized_name_counter)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for player, config_location in self.data.items():
            response = server.set_player_config_location(player, config_location)
            yield Response(200, response)


class LocationTimesProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'existing_locations')
        if not names:
            self._write_no_server_returned()
            return

        unrecognized_name_counter = 0
        for i, line in self._indexed_rows(input_text, lambda text: self._pad_list(text.split("\t"), 15),
                                          keep_repeats=True):
            split_line = line
            if len(split_line) != 15:
                self._wrong_init_counter += 1
                self._write_incorrect_format(i + 1)
                continue

            location = split_line[0]
            times = self._parse_times(split_line[1:], i + 1)

            if location in self.data:
                self._write_collision(i + 1, location)
                self._wrong_init_counter += 1
                continue

            if not self._validate_entity(location, names['existing_locations'], i + 1):
                unrecognized_name_counter += 1
                continue

            self.data[location] = times

        self._write_load_finish()
        if self._wrong_init_counter > 0 or unrecognized_name_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            self._write_recognition_errors(unrecognized_name_counter)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for location, times in self.data.items():
            response = server.set_location(location, times)
            response["data"]["name"] = response["data"]["configLocation"]
            yield Response(200, response)

    def _parse_times(self, times_list: List[str], line_num: int) -> Dict[str, Dict[str, str]]:
        times = {day: {"on": "", "off": ""} for day in WEEK_DAYS}

        for i, day in enumerate(WEEK_DAYS):
            on_time = times_list[i * 2]
            off_time = times_list[i * 2 + 1]

            try:
                on_time = normalize_time_format(on_time)
                off_time = normalize_time_format(off_time, is_off_time=True)
            except ValueError as e:
                self._wrong_init_counter += 1
                self._write_invalid_time(line_num, day, on_time if "on" in str(e) else off_time)
                continue

            if on_time and off_time and not compare_time(on_time, off_time):
                self._wrong_init_counter += 1
                self._write_time_order_error(line_num, day, on_time, off_time)
                continue

            times[day]["on"] = on_time
            times[day]["off"] = off_time

        return times

    def _write_invalid_time(self, line_number: int, day: str, invalid_time: str):
        self._logger.error(self.lang.get_message("invalid_day_time",
                                                 line_number=line_number,
                                                 day=day,
                                                 invalid_time=invalid_time))

    def _write_time_order_error(self, line_number: int, day: str, start_time: str, end_time: str):
        self._logger.error(self.lang.get_message("time_order_error",
                                                 line_num=line_number,
                                                 day=day,
                                                 start_time=start_time,
                                                 end_time=end_time))


class PlayerLabelsProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'player_names', 'label_names')
        if not names:
            self._write_no_server_returned()
            return

        unrecognized_name_counter = 0
        already_assigned = set()
        self.data = {}
        self._same_key = {}
        self._wrong_init_counter = 0

        for i, line in self._indexed_rows(input_text, lambda text: tuple(cell for cell in text.split("\t") if cell)):
            split_line = line
            player = split_line[0]
            labels = split_line[1:] if len(split_line) > 1 else []
            labels = [label for label in labels if label != ""]
            if not self._validate_entity(player, names['player_names'], i + 1):
                unrecognized_name_counter += 1
                continue

            invalid_labels = [label for label in labels if label not in names['label_names']]
            if invalid_labels:
                self._wrong_init_counter += 1
                self._write_name_fail(i + 1, ", ".join(invalid_labels))
                continue

            if player in already_assigned:
                self._same_key.setdefault(player, []).extend(labels)
            else:
                already_assigned.add(player)
                self.data[player] = labels

        self._write_load_finish()
        if self._wrong_init_counter > 0 or unrecognized_name_counter > 0 or self._same_key:
            self._write_wrong_format(self._wrong_init_counter)
            self._write_recognition_errors(unrecognized_name_counter)
            self._write_same_assign(self._same_key)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for player, labels in self.data.items():
            response = server.set_player_labels(player, labels)
            yield Response(200, response)


class DeleteAdditionalPlaylistProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'player_names')
        if not names:
            self._write_no_server_returned()
            return
        additional_playlists_players = {player for player, playlists in server.get_additional_playlists() if playlists}
        unrecognized_name_counter = 0
        self.data = {}
        self._same_key = {}
        self._wrong_init_counter = 0

        for i, line in self._indexed_rows(input_text, lambda text: tuple(cell for cell in text.split("\t") if cell)):
            split_line = line
            player = split_line[0]
            if not self._validate_entity(player, names['player_names'], i + 1):
                unrecognized_name_counter += 1
                continue
            if player in additional_playlists_players:
                self.data[player] = []
        self._write_load_finish()
        if self._wrong_init_counter > 0 or unrecognized_name_counter > 0 or self._same_key:
            self._write_wrong_format(self._wrong_init_counter)
            self._write_recognition_errors(unrecognized_name_counter)
            self._write_same_assign(self._same_key)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for player, _ in self.data.items():
            response = server.set_player_additional_playlist(player, [])
            yield Response(200, response)


class GroupSettingsProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'group_names')
        if not names:
            self._write_no_server_returned()
            return

        unrecognized_name_counter = 0
        already_assigned = set()
        self.data = {}
        self._same_key = {}
        self._wrong_init_counter = 0

        for line_num, line in self._numbered_lines(input_text):
            cells = line.split("\t")
            group, settings = cells[0], cells[1:]
            # The last column (the video player) may be left out; everything before it is written to the server as it
            # stands, so a line cut short would switch off what its missing columns say.
            if not 8 <= len(settings) <= 9:
                self._write_incorrect_format(line_num)
                self._wrong_init_counter += 1
                continue
            settings += [""] * (9 - len(settings))

            if not self._validate_entity(group, names['group_names'], line_num):
                unrecognized_name_counter += 1
                continue

            if group in already_assigned:
                self._write_collision(line_num, group)
                self._wrong_init_counter += 1
                self._same_key.setdefault(group, []).append(settings)
                continue

            if not settings[0] or not settings[1]:
                self._write_missing_group_setting(line_num, group)
                self._wrong_init_counter += 1
                continue

            if not self._normalize_times(line_num, group, settings):
                continue

            settings[4] = self._str_to_bool(settings[4])
            settings[5] = self._str_to_bool(settings[5])
            self.data[group] = settings
            already_assigned.add(group)

        self._write_load_finish()
        if self._wrong_init_counter > 0 or unrecognized_name_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            self._write_recognition_errors(unrecognized_name_counter)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for group, settings in self.data.items():
            response = server.set_group_settings(
                group,
                settings[0],  # resolution
                settings[1],  # orientation
                self.time_to_iso(settings[2]),  # restart time
                self.time_to_iso(settings[3]),  # deploy time
                settings[4],  # auto restart
                settings[5],  # auto deploy
                settings[6],  # on time
                settings[7],  # off time
                settings[8]
            )
            yield Response(200, response)

    @staticmethod
    def _str_to_bool(value: str) -> bool:
        return value.lower() in ["true", "1", "yes"]

    def _normalize_times(self, line_num: int, group: str, settings: List) -> bool:
        """
        Puts the times of the line (restart, deploy, display on and off) in the form the server takes, in place. A time
        that cannot be read is reported and so is a display switched on without the time it is switched off (or the
        other way round), which would leave the display without any schedule.
        """
        valid = True
        for index, is_off_time in ((2, False), (3, False), (6, False), (7, True)):
            try:
                settings[index] = normalize_time_format(settings[index], is_off_time=is_off_time)
            except ValueError:
                self._write_invalid_time_format(line_num, settings[index])
                self._wrong_init_counter += 1
                valid = False
        if valid and bool(settings[6]) != bool(settings[7]):
            self._write_sleep_times_incomplete(line_num, group)
            self._wrong_init_counter += 1
            valid = False
        return valid

    def _write_missing_group_setting(self, line_num: int, group: str):
        self._logger.error(self.lang.get_message("missing_group_setting", line_num=line_num, group=group))

    def _write_sleep_times_incomplete(self, line_num: int, group: str):
        self._logger.error(self.lang.get_message("sleep_times_incomplete", line_num=line_num, group=group))

    def _write_invalid_time_format(self, line_num: int, time_str: str):
        self._logger.error(self.lang.get_message("invalid_time_format", line_num=line_num, time_str=time_str))

    @staticmethod
    def time_to_iso(time_str: str) -> Optional[str]:
        """
        Converts a time string in 'HH:MM' format to ISO 8601 format with a fixed date.
        """
        if not time_str:
            return None
        local_dt = datetime.strptime(time_str, "%H:%M")
        local_dt = local_dt.replace(year=1970, month=1, day=1, tzinfo=timezone.utc)
        utc_dt = local_dt - timedelta(hours=1)
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        return utc_dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


class PlaylistSettingsProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'playlist_names')
        if not names:
            self._write_no_server_returned()
            return

        unrecognized_name_counter = 0
        self.data = {}
        for i, line in self._indexed_rows(input_text, lambda text: convert(self._pad_list(text.split("\t"), 2)),
                                          keep_repeats=True):
            split_line = line
            if len(split_line) != 2:
                self._wrong_init_counter += 1
                self._write_incorrect_format(i + 1)
                continue

            playlist_name, domination_time = split_line[0], split_line[1].strip()
            if not self._validate_entity(playlist_name, names['playlist_names'], i + 1):
                unrecognized_name_counter += 1
                continue

            if domination_time and not (domination_time.isascii() and domination_time.isdigit()
                                        and int(domination_time) > 0):
                self._wrong_init_counter += 1
                self._write_invalid_number(i + 1, playlist_name, domination_time)
                continue

            self.data[playlist_name] = domination_time

        self._write_load_finish()
        if self._wrong_init_counter > 0 or unrecognized_name_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            self._write_recognition_errors(unrecognized_name_counter)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for playlist_name, domination_time in self.data.items():
            response = server.set_playlist_settings(playlist_name, domination_time)
            yield Response(200, response)

    def _write_invalid_number(self, line_num: int, playlist: str, value: str):
        self._logger.error(self.lang.get_message("invalid_domination_interval", line_num=line_num,
                                                 playlist=playlist, value=value))

    def _write_error_assign(self, line_num: int, code: int):
        self._logger.error(self.lang.get_message("error_assign_playlist", line_num=line_num, code=code))


class RemovePlaylistsProcessor(RemoveProcessor):
    entity_type = "group_names"

    def _label_method(self, server: ServerApi):
        return server.get_playlists_by_label

    def _remove_method(self, server, entity_name: str, keyword: str) -> Response:
        removed_playlists = server.remove_playlists_by_keyword_from_group(entity_name, keyword)
        response = {
            "group": entity_name,
            "removed_playlists": removed_playlists
        }
        return Response(200, response)

    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'group_names')
        if not names:
            self._write_no_server_returned()
            return

        group_keywords = {}
        for i, line in self._indexed_rows(input_text, lambda text: convert(self._pad_list(text.split("\t"), 2)),
                                          keep_repeats=True):
            split_line = line
            if len(split_line) != 2:
                self._wrong_init_counter += 1
                self._write_incorrect_format(i + 1)
                continue

            group, keyword = split_line[0], split_line[1]
            if not keyword.strip():  # a missing column is padded to "", which is contained in every playlist name
                self._wrong_init_counter += 1
                self._write_empty_keyword(i + 1)
                continue
            if not self._validate_entity(group, names['group_names'], i + 1):
                continue

            group_keywords[group] = keyword
        self.data = group_keywords

        self._write_load_finish()
        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

    def run(self) -> Generator[None, None, None]:
        try:
            i = 0
            with self._try_server_login() as server:
                if not server:
                    self._write_no_server_returned()
                    return
                for group, keyword in self.data.items():
                    response = self._remove_method(server, group, keyword)
                    i += 1
                    if response.code == 200:
                        response_msg = response.response_msg
                        group = response_msg["group"]
                        removed_playlists = response_msg["removed_playlists"]
                        self._write_success_remove_playlists_from_group(i, group, removed_playlists)
                    else:
                        self._write_error_assign(i, response.code)
                    yield
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    def _write_success_remove_playlists_from_group(self, line_num: int, group: str, removed_playlists: List[str]):
        self._logger.info(self.lang.get_message("success_remove_playlists_from_group",
                                                line_num=line_num,
                                                group=group,
                                                removed_playlists=removed_playlists))


class RemovePlaylistsByListProcessor(RemoveProcessor):
    entity_type = "group_names"

    def _remove_method(self, server, playlist_name: str) -> Response:
        removed_playlists = server.remove_playlists_from_groups([playlist_name])
        return Response(200, {"removed_playlists": removed_playlists})

    def _label_method(self, server: ServerApi):
        return server.get_groups_by_label

    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'group_names', 'playlist_names')
        if not names:
            self._write_no_server_returned()
            return

        input_lines = [row for _, row in self._indexed_rows(input_text, str.strip)]
        self.data = [playlist for playlist in input_lines if playlist in names['playlist_names']]

        unknown = [playlist for playlist in input_lines if playlist not in names['playlist_names']]
        if unknown:
            self._write_log_warning("skipped_unknown_playlists", names=", ".join(unknown))

        group_playlists = server.get_groups_playlists()
        self.to_remove = {
            group: [playlist for (playlist, _, __, ___, ____) in playlists if playlist in self.data]
            for group, playlists in group_playlists.items()
        }

        self._write_load_finish()
        if not self.to_remove:
            self._write_wrong_format(1)
            raise FormatException

    def run(self) -> Generator[None, None, None]:
        """
        Projde všechny skupiny a odebere playlisty podle načteného seznamu.
        """
        try:
            with self._try_server_login() as server:
                if not server:
                    self._write_no_server_returned()
                    return
                i = 0
                for group, playlists in self.to_remove.items():
                    for playlist in playlists:
                        response = self._remove_method(server, playlist)
                        if response.code == 200:
                            # TODO: zmenit vypis
                            self._write_success_remove_playlists_from_group(group, i, playlist)
                        else:
                            self._write_error_assign(i, response.code)
                        yield
                    i += 1
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    def _write_success_remove_playlists_from_group(self, group: str, line_num: int, removed_playlist: str):
        self._logger.info(self.lang.get_message("success_remove_playlists_from_group",
                                                group=group,
                                                line_num=line_num,
                                                removed_playlists=removed_playlist))


class AddDetailedPlaylistProcessor(DetailedPlaylistProcessor):
    def load(self, input_text: str):
        try:
            self._write_start_loading()
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return

            names = self._retrieve_names(server, 'group_names', 'playlist_names')
            if not names:
                self._write_no_server_returned()
                return

            existing_group_playlists = server.get_groups_playlists_details()

            group_playlists = {}
            loaded_groups = set()
            for line_num, line in self._numbered_lines(input_text):
                cells = line.split("\t")
                group = cells[0]
                if group not in names['group_names']:
                    self._write_name_fail(line_num, group)
                    self._wrong_init_counter += 1
                    continue

                if group in loaded_groups:
                    self._write_collision(line_num, group)
                    self._wrong_init_counter += 1

                loaded_groups.add(group)

                playlists = []

                # Add existing playlists
                if group in existing_group_playlists:
                    existing_playlists = existing_group_playlists[group]
                    for pl in existing_playlists:
                        existing_pl_data = (pl["playlist_name"], pl["start_date"],
                                            pl["end_date"], pl["days_of_week"],
                                            pl["start_time"], pl["end_time"])
                        try:
                            existing_pl_data = (
                                existing_pl_data[0],
                                existing_pl_data[1],
                                existing_pl_data[2],
                                existing_pl_data[3],
                                normalize_time_format(existing_pl_data[4]),
                                normalize_time_format(existing_pl_data[5], is_off_time=True),
                            )
                        except ValueError as e:
                            self._wrong_init_counter += 1
                            self._write_invalid_time(line_num, group, existing_pl_data[0], str(e))
                            continue
                        playlists.append(existing_pl_data)

                # Add new playlists from input
                playlists.extend(self._validated_blocks(line_num, group, cells[1:], names['playlist_names']))

                group_playlists[group] = playlists

            self.data = group_playlists

            self._write_load_finish()
            if self._wrong_init_counter > 0:
                self._write_wrong_format(self._wrong_init_counter)
                raise FormatException
        except FormatException:  # not an internal error: it has been reported
            raise
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()


class RemoveExpiredPlaylistsProcessor(RemoveProcessor):
    entity_type = 'group_names'

    def _remove_method(self, server, entity_name: str) -> Response:
        response = server.remove_expired_playlists_from_group(entity_name)
        return Response(200, response)

    def _remove_entity(self, server, entity_name: str):
        """The group is not deleted: what is said is the playlists that were taken out of it, if there were any."""
        try:
            removed = self._remove_method(server, entity_name).response_msg
        except Exception as e:
            self._write_internal_error(e)
            return
        key = "success_remove_expired" if removed else "nothing_expired"
        self._logger.info(self.lang.get_message(key, group=entity_name, removed=", ".join(removed or [])))

    def _label_method(self, server: ServerApi):
        return server.get_groups_by_label


class CreateLocationProcessor(CreateProcessor):
    entity_type = 'existing_locations'

    def _create_method(self, server, entity_name: str) -> Response:
        response = server.create_location(entity_name)
        return Response(200, response)


class CreateGroupProcessor(CreateProcessor):
    entity_type = 'group_names'

    def _create_method(self, server, entity_name: str) -> Response:
        response = server.create_group(entity_name)
        return Response(200, response)


class CreatePlayerProcessor(CreateProcessor):
    entity_type = 'player_names'

    def _create_method(self, server, entity_name: str) -> Response:
        response = server.create_player(entity_name)
        return Response(200, response)


class CreatePlaylistProcessor(CreateProcessor):
    entity_type = 'playlist_names'

    def _create_method(self, server, entity_name: str) -> Response:
        response = server.create_playlist(entity_name)
        return Response(200, response)


class CreateLabelProcessor(CreateProcessor):
    entity_type = 'label_names'

    def _create_method(self, server, entity_name: str) -> Response:
        response = server.create_label(entity_name)
        return Response(200, response)


class RemoveUnusedProcessor(RemoveProcessor, ABC):
    """
    Deletes entities that nothing uses any more, for good. Only what the server itself reports as unused is deleted:
    a list typed in can be an old CSV, so it is checked against the server when loaded and once more right before
    the deleting starts (the user is asked in between), and anything used by now is left alone.
    """

    @abstractmethod
    def _unused_method(self, server: ServerApi) -> List[str]:
        pass

    def load(self, input_text: str):
        super().load(input_text)
        try:
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                raise InternalException()
            unused = set(self._unused_method(server))
        except requests.exceptions.RequestException:
            self._write_internal_error("could not check which of the names are unused")
            raise InternalException()
        for entity in self.data:
            if entity not in unused:
                self._wrong_init_counter += 1
                self._write_log_warning("not_unused", name=entity)
        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

    def confirmation(self) -> Optional[Confirmation]:
        if not self.data:
            return None
        return Confirmation(
            self.lang.get_message("confirm_remove_title"),
            self.lang.get_message("confirm_remove_text", count=len(self.data),
                                  items=self._list_for_question(list(self.data))))

    def _prepare(self, server: ServerApi):
        unused = set(self._unused_method(server))
        for entity in self.data:
            if entity not in unused:
                self._write_log_warning("not_unused_now", name=entity)
        self.data = [entity for entity in self.data if entity in unused]


class RemoveUnusedGroupsProcessor(RemoveUnusedProcessor):
    entity_type = 'group_names'

    def _unused_method(self, server: ServerApi) -> List[str]:
        return server.get_unused_groups()

    def _remove_method(self, server, entity_name: str) -> Response:
        response = server.delete_group(entity_name)
        return Response(200, response)

    def _label_method(self, server: ServerApi):
        return server.get_groups_by_label


class RemoveUnusedPlaylistsProcessor(RemoveUnusedProcessor):
    entity_type = 'playlist_names'

    def _unused_method(self, server: ServerApi) -> List[str]:
        return server.get_unused_playlists()

    def _remove_method(self, server, entity_name: str) -> Response:
        response = server.delete_playlist(entity_name)
        return Response(200, response)

    def _label_method(self, server: ServerApi):
        return server.get_playlists_by_label


class RemoveUnusedAssetsProcessor(RemoveUnusedProcessor):
    entity_type = 'asset_names'

    def _unused_method(self, server: ServerApi) -> List[str]:
        return server.get_unused_assets()

    def _remove_method(self, server, entity_name: str) -> Response:
        response = server.delete_asset(entity_name)
        return Response(200, response)

    def _label_method(self, server: ServerApi):
        return server.get_assets_by_label


class RemoveUnusedLabelsProcessor(RemoveUnusedProcessor):
    entity_type = 'label_names'
    test_pattern = re.compile(r"[tT][eE][sS][tT]")

    def _unused_method(self, server: ServerApi) -> List[str]:
        return server.get_unused_labels()

    def _remove_method(self, server, entity_name: str) -> Response:
        response = server.delete_label(entity_name)
        return Response(200, response)

    def _label_method(self, server: ServerApi):
        return self.empty_list

    @staticmethod
    def empty_list(_):
        return []

    def skip_check(self, entity):
        return bool(re.match(self.test_pattern, entity))


class RemoveUnusedLocationsProcessor(RemoveUnusedProcessor):
    entity_type = 'existing_locations'

    def _unused_method(self, server: ServerApi) -> List[str]:
        return server.get_unused_locations()

    def _remove_method(self, server, entity_name: str) -> Response:
        response = server.delete_location(entity_name)
        return Response(200, response)

    def _label_method(self, server: ServerApi):
        return server.get_locations_by_label


class PlayerDetailsCloneProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'player_names')
        if not names:
            self._write_no_server_returned()
            return

        for i, line in self._indexed_rows(
                input_text, lambda text: convert(self._pad_list([cell for cell in text.split("\t") if cell], 2))):
            split_line = line
            if len(split_line) != 2 or not all(split_line):  # a player to copy to is needed too
                self._wrong_init_counter += 1
                self._write_incorrect_format(i + 1)
                continue

            old_player, new_player = split_line[0], split_line[1]
            if not self._validate_entity(old_player, names['player_names'], i + 1):
                continue

            self.data[old_player] = new_player

        self._write_load_finish()
        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for old_player, new_player in self.data.items():
            response = server.clone_player_details(old_player, new_player)
            yield Response(200, response)


class GroupRenameProcessor(RenameProcessor):
    entity_type = "group_names"

    def _rename_method(self, server, old_name: str, new_name: str) -> Response:
        return server.rename_group(old_name, new_name)

    def _new_name_error(self, old_name: str, new_name: str) -> Optional[str]:
        return self._invalid_name_message_key() if re.search(r'[",;\s]', new_name) else None

    def _invalid_name_message_key(self) -> str:
        return "invalid_group_name"

    def _success_rename_message_key(self) -> str:
        return "success_rename"


class PlayerRenameProcessor(RenameProcessor):
    entity_type = "player_names"

    def _rename_method(self, server, old_name: str, new_name: str) -> Response:
        return server.rename_player(old_name, new_name)

    # The identifier must be followed by "_" in the new name; the old name is only searched for the bare identifier,
    # because existing names may predate this convention.
    _IDENTIFIER = r"(?:P[B-E]\d{4}|[Rr][Pp][Ii]\d{3})"

    def _new_name_error(self, old_name: str, new_name: str) -> Optional[str]:
        if re.search(r'[",;\s]', new_name) or not re.search(self._IDENTIFIER + "_", new_name):
            return self._invalid_name_message_key()
        old_identifiers = re.findall(self._IDENTIFIER, old_name)
        if old_identifiers and old_identifiers != re.findall(self._IDENTIFIER, new_name):
            return "player_identifier_changed"
        return None

    def _invalid_name_message_key(self) -> str:
        return "invalid_player_name"

    def _success_rename_message_key(self) -> str:
        return "success_rename"


class PlaylistRenameProcessor(RenameProcessor):
    entity_type = "playlist_names"

    def _rename_method(self, server, old_name: str, new_name: str) -> Response:
        return server.rename_playlist(old_name, new_name)

    def _new_name_error(self, old_name: str, new_name: str) -> Optional[str]:
        return self._invalid_name_message_key() if re.search(r'[",;\s]', new_name) else None

    def _invalid_name_message_key(self) -> str:
        return "invalid_name"

    def _success_rename_message_key(self) -> str:
        return "success_rename"


class LocationRenameProcessor(RenameProcessor):
    entity_type = "existing_locations"

    def _rename_method(self, server, old_name: str, new_name: str) -> Response:
        return server.rename_location(old_name, new_name)

    def _new_name_error(self, old_name: str, new_name: str) -> Optional[str]:
        return self._invalid_name_message_key() if re.search(r'\s', new_name) else None

    def _invalid_name_message_key(self) -> str:
        return "invalid_location_name"

    def _success_rename_message_key(self) -> str:
        return "success_rename"


class RemoveGroupsByKeywordProcessor(RemoveByKeywordProcessor):
    entity_type = "group_names"
    success_message = ("success_remove_playlists_from_group", "group", "removed_playlists")

    def _remove_method(self, server, entity_name: str, keyword: str) -> Response:
        response = server.remove_playlists_by_keyword_from_group(entity_name, keyword)
        return Response(200, {"removed_items": response})

    def _label_method(self, server: ServerApi):
        return server.get_groups_by_label


class RemoveAssetsProcessor(RemoveByKeywordProcessor):
    entity_type = "playlist_names"
    success_message = ("success_remove_assets_from_playlist", "playlist", "removed_assets")

    def _remove_method(self, server, entity_name: str, keyword: str) -> Response:
        response = server.remove_assets_by_keyword_from_playlist(entity_name, keyword)
        return Response(200, {"removed_items": response})

    def _label_method(self, server: ServerApi):
        return server.get_playlists_by_label


class RemoveLabelsByKeywordProcessor(RemoveByKeywordProcessor):
    entity_type = "label_names"

    def _remove_method(self, server, entity_name: str, keyword: str) -> Response:
        response = server.remove_labels_by_keyword(entity_name, keyword)
        return Response(200, {"removed_items": response})

    def _label_method(self, server: ServerApi):
        return lambda _: []


class RemoveAllUnusedGroupsProcessor(RemoveUnusedGroupsProcessor):
    def load(self, input_text: str):
        try:
            self._write_start_loading()
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return

            unused_groups = server.get_unused_groups()
            if not unused_groups:
                self._write_log_warning("nothing_unused")
                return

            self.data = unused_groups

            self._write_load_finish()
            if not self.data:
                self._write_wrong_format(1)
                raise FormatException
        except FormatException:  # reported already, not an internal error
            raise
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()


class RemoveAllUnusedLocationsProcessor(RemoveUnusedLocationsProcessor):
    def load(self, input_text: str):
        try:
            self._write_start_loading()
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return

            unused_locations = server.get_unused_locations()
            if not unused_locations:
                self._write_log_warning("nothing_unused")
                return

            self.data = unused_locations

            self._write_load_finish()
            if not self.data:
                self._write_wrong_format(1)
                raise FormatException
        except FormatException:  # reported already, not an internal error
            raise
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()


class RemoveAllUnusedPlaylistsProcessor(RemoveUnusedPlaylistsProcessor):
    def load(self, input_text: str):
        try:
            self._write_start_loading()
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return

            unused_playlists = server.get_unused_playlists()
            if not unused_playlists:
                self._write_log_warning("nothing_unused")
                return

            self.data = unused_playlists

            self._write_load_finish()
            if not self.data:
                self._write_wrong_format(1)
                raise FormatException
        except FormatException:  # reported already, not an internal error
            raise
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()


class RemoveAllUnusedLabelsProcessor(RemoveUnusedLabelsProcessor):
    def load(self, input_text: str):
        try:
            self._write_start_loading()
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return

            unused_labels = server.get_unused_labels()
            if not unused_labels:
                self._write_log_warning("nothing_unused")
                return

            self.data = unused_labels

            self._write_load_finish()
            if not self.data:
                self._write_wrong_format(1)
                raise FormatException
        except FormatException:  # reported already, not an internal error
            raise
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()


class RemoveAllUnusedAssetsProcessor(RemoveUnusedAssetsProcessor):
    def load(self, input_text: str):
        try:
            self._write_start_loading()
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return

            unused_assets = server.get_unused_assets()
            if not unused_assets:
                self._write_log_warning("nothing_unused")
                return

            self.data = unused_assets

            self._write_load_finish()
            if not self.data:
                self._write_wrong_format(1)
                raise FormatException
        except FormatException:  # reported already, not an internal error
            raise
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()


class RemoveAllExpiredPlaylistsProcessor(RemoveExpiredPlaylistsProcessor):
    def load(self, input_text: str):
        try:
            self._write_start_loading()
            server = self._try_server_login()
            if not server:
                self._write_no_server_returned()
                return

            group_names = server.get_group_names()
            if not group_names:
                self._write_no_server_returned()
                return

            self.data = group_names
            self._write_load_finish()

        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()


class AssetValidityProcessor(AssignProcessor):
    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, 'asset_names')
        if not names:
            self._write_no_server_returned()
            return

        unrecognized_name_counter = 0
        for line_num, line in self._numbered_lines(input_text):
            split_line = self._pad_list(line.split("\t"), 5)
            if len(split_line) != 5:
                self._wrong_init_counter += 1
                self._write_incorrect_format(line_num)
                continue

            asset_name, start_date, end_date, start_hour, end_hour = split_line

            if not self._validate_entity(asset_name, names['asset_names'], line_num):
                unrecognized_name_counter += 1
                continue

            validity = self._validated_validity(line_num, asset_name, start_date.strip(), end_date.strip(),
                                                start_hour, end_hour)
            if validity:
                self.data[asset_name] = validity

        self._write_load_finish()
        if self._wrong_init_counter > 0 or unrecognized_name_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            self._write_recognition_errors(unrecognized_name_counter)
            raise FormatException

    def _validated_validity(self, line_num: int, asset_name: str, start_date: str, end_date: str, start_hour: str,
                            end_hour: str) -> Optional[Tuple]:
        """The validity of the line in the form it is sent, or None after reporting what is wrong with it."""
        valid = True
        for date in (start_date, end_date):
            if date and not self._validate_date_format(date):
                self._write_invalid_asset_value(line_num, asset_name, "invalid_asset_date", date)
                valid = False
        if valid and start_date and end_date and not compare_date(start_date, end_date):
            self._write_invalid_asset_value(line_num, asset_name, "asset_date_order", f"{start_date} - {end_date}")
            valid = False
        hours = []
        for text, is_end in ((start_hour, False), (end_hour, True)):
            try:
                hours.append(parse_validity_hour(text, is_end))
            except ValueError:
                self._write_invalid_asset_value(line_num, asset_name, "invalid_asset_hour", text)
                valid = False
        if not valid:
            self._wrong_init_counter += 1
            return None
        return (start_date, end_date, *hours)

    def _write_invalid_asset_value(self, line_num: int, asset_name: str, key: str, value: str):
        self._logger.error(self.lang.get_message(key, line_num=line_num, asset=asset_name, value=value))

    def _assign_stepwise(self, server) -> Generator[Response, None, None]:
        for asset_name, (start_date, end_date, start_hour, end_hour) in self.data.items():
            response = server.set_asset_validity(asset_name,
                                                 legible_to_iso(start_date),
                                                 legible_to_iso(end_date),
                                                 start_hour,
                                                 end_hour)
            yield Response(200, response)

    def _write_success_assign(self, line_num: int, entity_name: str, assigned_name: str):
        self._logger.info(self.lang.get_message("success_assign",
                                                line_num=line_num,
                                                entity_name=entity_name,
                                                assigned_name=assigned_name))

    def _write_error_assign(self, line_num: int, code: int):
        self._logger.warning(self.lang.get_message("error_assign", line_num=line_num, code=code))

    @staticmethod
    def _pad_list(lst: List[str], pad_to: int) -> List[str]:
        n = (pad_to - (len(lst))) % pad_to
        return lst + [""] * n


class PlayerUpdateProcessor(EntityValidationProcessor):
    entity_type = 'player_names'

    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, self.entity_type)
        if not names:
            self._write_no_server_returned()
            return

        unrecognized_name_counter = 0

        self.data = []
        for i, player_name in self._indexed_rows(input_text, str.strip):
            if not self._validate_entity(player_name, names[self.entity_type], i + 1):
                unrecognized_name_counter += 1
                continue

            self.data.append(player_name)

        self._write_load_finish()
        if self._wrong_init_counter > 0 or unrecognized_name_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            self._write_recognition_errors(unrecognized_name_counter)
            raise FormatException

    def run(self) -> Generator[None, None, None]:
        try:
            with self._try_server_login() as server:
                if not server:
                    self._write_no_server_returned()
                    return
                for player_name in self.data:
                    try:
                        server.send_player_command(player_name, "sudo systemctl stop watchdog.service")
                        sleep(1)
                        server.player_update(player_name)
                        self._write_success_update(player_name)
                    except Exception as error:
                        self._write_error_update(player_name, getattr(error, "status", None) or type(error).__name__)
                    yield
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    def _write_success_update(self, player_name: str):
        self._logger.info(self.lang.get_message("success_update", player_name=player_name))

    def _write_watchdog_turned_off(self, player_name: str):
        self._logger.info(self.lang.get_message("turn_off_watchdog", player_name=player_name))

    def _write_error_update(self, player_name: str, code):
        self._logger.error(self.lang.get_message("error_update", player_name=player_name, code=code))


class DeployAllPlayersProcessor(EntityValidationProcessor):
    """
    Deploys sequentially in batches to online players only, to avoid overloading
    the server when deploying to large groups/accounts. Failed/unresponsive players
    are retried by re-queuing them into a later batch, up to MAX_ATTEMPTS total.

    Scope: all players of the account (self.data["groups"] stays None).
    """
    MAX_ATTEMPTS = 3

    def __init__(self, *args, batch_size: int = 10, batch_interval: int = 3, account_name: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.batch_size = batch_size
        self.batch_interval = batch_interval
        self.account_name = account_name
        self._online = self._offline = None  # how many players the deploy would reach, once it is known

    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        self.data = {"groups": None}
        self._plan_deploy(server)
        self._write_load_finish()

    def _plan_deploy(self, server: ServerApi):
        """Counts the players the deploy is about to reach, for the question the user is asked first."""
        try:
            players = server.get_players_for_deploy(self.data["groups"])
            self._online = sum(1 for player in players if player["isConnected"] and player["group_id"])
            self._offline = sum(1 for player in players if not player["isConnected"])
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    def confirmation(self) -> Optional[Confirmation]:
        if not self._online:  # nothing to deploy to (or the plan was never made): run() reports it
            return None
        groups = self.data["groups"]
        scope = (self.lang.get_message("confirm_deploy_scope_groups", groups=", ".join(sorted(groups)))
                 if groups else self.lang.get_message("confirm_deploy_scope_all"))
        account = self.account_name or urlparse(self._login_info["url"]).hostname or ""
        return Confirmation(
            self.lang.get_message("confirm_deploy_title"),
            self.lang.get_message("confirm_deploy_text", account=account, scope=scope,
                                  online=self._online, offline=self._offline))

    def run(self) -> Generator[None, None, None]:
        try:
            with self._try_server_login() as server:
                if not server:
                    self._write_no_server_returned()
                    return

                players = server.get_players_for_deploy(self.data["groups"])
                # A deploy sends the player its own group again; one that has none has nothing to be sent
                online = sorted((p for p in players if p["isConnected"] and p["group_id"]), key=lambda p: p["name"])
                offline = sorted((p for p in players if not p["isConnected"]), key=lambda p: p["name"])
                no_group = sorted(p["name"] for p in players if p["isConnected"] and not p["group_id"])

                self._write_deploy_summary(len(players), len(online), len(offline))
                if no_group:
                    self._logger.warning(self.lang.get_message("deploy_skipped_no_group", count=len(no_group),
                                                               names=", ".join(no_group)))

                queue = [(player, 1) for player in online]
                failed = []
                succeeded = 0

                while queue:
                    batch, queue = queue[:self.batch_size], queue[self.batch_size:]
                    self._write_deploy_batch_sent([player["name"] for player, _ in batch])

                    with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                        future_to_entry = {
                            executor.submit(self._deploy_one, server, player): (player, attempt)
                            for player, attempt in batch
                        }
                        for future in as_completed(future_to_entry):
                            player, attempt = future_to_entry[future]
                            ok, reason = future.result()
                            if ok:
                                succeeded += 1
                            elif attempt < self.MAX_ATTEMPTS:
                                queue.append((player, attempt + 1))
                            else:
                                failed.append((player["name"], reason))

                    if queue:
                        self._write_deploy_remaining(len(queue))

                    yield

                    if queue:
                        sleep(self.batch_interval)

                self._write_deploy_final_summary(len(online), succeeded, failed)
        except Exception as e:
            self._write_internal_error(e)
            raise InternalException()

    @staticmethod
    def _deploy_one(server, player: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        try:
            server.trigger_player_deploy(player["_id"], player["group_id"], player["group_name"])
            return True, None
        except ResponseError:
            return False, "response_error"
        except requests.exceptions.RequestException:
            return False, "connection_error"
        except Exception as e:
            return False, str(e)

    def _write_deploy_summary(self, total: int, online: int, offline: int):
        self._logger.info(self.lang.get_message("deploy_summary", total=total, online=online, offline=offline))

    def _write_deploy_batch_sent(self, names: List[str]):
        self._logger.info(self.lang.get_message("deploy_batch_sent", names="\n" + "\n".join(names)))

    def _write_deploy_remaining(self, remaining: int):
        self._logger.error(self.lang.get_message("deploy_remaining", remaining=remaining),
                           extra={'hide_level': True})

    def _write_deploy_final_summary(self, total_online: int, succeeded: int, failed: List[Tuple[str, str]]):
        self._logger.info(self.lang.get_message(
            "deploy_final_summary", total=total_online, succeeded=succeeded, failed_count=len(failed)))
        for name, reason in failed:
            self._logger.error(self.lang.get_message("deploy_failed_player", name=name, reason=reason))


class DeploySelectedGroupsProcessor(DeployAllPlayersProcessor):
    """
    Same batching/retry engine as DeployAllPlayersProcessor, scoped to one or more
    groups typed by the user (one group name per line).
    """
    entity_type = 'group_names'

    def load(self, input_text: str):
        self._write_start_loading()
        server = self._try_server_login()
        if not server:
            self._write_no_server_returned()
            return

        names = self._retrieve_names(server, self.entity_type)
        if not names:
            self._write_no_server_returned()
            return

        group_names = {line.strip() for line in input_text.split('\n') if line.strip()}
        if not group_names:
            self._write_wrong_format(1)
            raise FormatException

        for i, group_name in enumerate(sorted(group_names)):
            self._validate_entity(group_name, names[self.entity_type], i + 1)

        if self._wrong_init_counter > 0:
            self._write_wrong_format(self._wrong_init_counter)
            raise FormatException

        self.data = {"groups": list(group_names)}
        self._plan_deploy(server)
        self._write_load_finish()
