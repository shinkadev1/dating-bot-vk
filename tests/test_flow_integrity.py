"""flow.yaml цел: схема, ссылки, картинки, лимиты ВК, реестры кода, шаблоны и сообщения об ошибках."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DEV_MODE"] = "False"

import yaml  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

from app import events, flow, handlers  # noqa: E402

FLOW_YAML = flow.FLOW_DIR / "flow.yaml"

# Токены текста по действиям: то, что бот понимал до перехода на flow (tests/fixtures/ui_snapshot.json).
EXPECTED_TOKENS = {
    "start": {"начать", "/start", "start", "🔍 новый собеседник", "🔍 найти собеседника", "🔥 начать чат", "👋 давай"},
    "report": {"🚫 пожаловаться", "пожаловаться"},
    "stop": {"🛑 закончить диалог", "остановить диалог"},
    "next": {"➡️ следующий собеседник"},
}


def base_data() -> dict:
    return yaml.load(FLOW_YAML.read_text(encoding="utf-8"), Loader=flow._Loader)


class RealFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flow = flow.load()

    def test_schema_is_valid_draft_2020_12(self) -> None:
        schema = json.loads((flow.FLOW_DIR / "flow.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("/v1/", schema["$id"])
        self.assertEqual(self.flow.bot, "vk")
        self.assertEqual(self.flow.version, 1)

    def test_every_screen_has_title_and_unique_pos_on_grid(self) -> None:
        positions = []
        for screen in self.flow.screens.values():
            self.assertTrue(screen.title, screen.id)
            self.assertIsNotNone(screen.pos, screen.id)
            self.assertEqual((screen.pos[0] % 320, screen.pos[1] % 180), (0, 0), screen.id)
            positions.append(screen.pos)
        self.assertEqual(len(positions), len(set(positions)))

    def test_links_and_files(self) -> None:
        self.assertIn(self.flow.start, self.flow.screens)
        for screen in self.flow.screens.values():
            for target in (screen.next, screen.buttons_from):
                self.assertTrue(target is None or target in self.flow.screens, screen.id)
            for row in screen.buttons:
                for button in row:
                    for target in (button.goto, button.next):
                        self.assertTrue(target is None or target in self.flow.screens, button.text)
            if screen.image:
                self.assertTrue((flow.FLOW_DIR / screen.image).is_file(), screen.image)
        images = {p.name for p in (flow.FLOW_DIR / "images").iterdir()}
        used = {Path(s.image).name for s in self.flow.screens.values() if s.image}
        self.assertEqual(images, used, "лишние или недостающие файлы в flow/images")
        self.assertFalse((flow.FLOW_DIR.parent / "app" / "assets").exists(), "картинки живут в flow/images")

    def test_vk_limits(self) -> None:
        for screen in self.flow.screens.values():
            self.assertLessEqual(len(screen.text or ""), 4096, screen.id)
            inline = screen.kind == "inline"
            self.assertLessEqual(len(screen.buttons), 6 if inline else 10, screen.id)
            self.assertLessEqual(sum(len(r) for r in screen.buttons), 10 if inline else 40, screen.id)
            for row in screen.buttons:
                self.assertTrue(1 <= len(row) <= 5)
                for button in row:
                    self.assertTrue(1 <= len(button.text) <= 40, button.text)
                    if not button.url:
                        self.assertLessEqual(len(button.payload_json()), 255, button.text)
            if screen.options:
                mark = f" {screen.options.selected_mark}"
                self.assertLessEqual(len(screen.options.rows), 6)
                for key, label in screen.options.items.items():
                    self.assertLessEqual(len(label + mark), 40, key)
                    self.assertLessEqual(len(screen.options.data(key)), 255, key)
                    self.assertIsInstance(screen.options.payload_data(key).get("command"), str, key)
        self.assertLessEqual(len(self.flow.text("premium_active_until", date="31.12.2026")), 40)

    def test_every_button_has_explicit_style(self) -> None:
        for screen in self.flow.screens.values():
            for row in screen.buttons:
                for button in row:
                    self.assertIn(button.style, {"primary", "secondary", "success", "danger"}, f"{screen.id}: {button.text}")
            if screen.options:
                self.assertEqual(set(screen.options.styles), set(screen.options.items), screen.id)

    def test_registries_match_code_both_ways(self) -> None:
        self.assertEqual(self.flow.actions(), handlers.ACTIONS)
        self.assertEqual(self.flow.handlers(), handlers.HANDLERS)
        self.assertEqual(self.flow.events(), events.EVENTS)
        self.flow.check_registries(actions=handlers.ACTIONS, handlers=handlers.HANDLERS, events=events.EVENTS)

    def test_registry_mismatch_is_flow_error(self) -> None:
        cases = {
            "actions": dict(actions=handlers.ACTIONS | {"fly"}, handlers=handlers.HANDLERS, events=events.EVENTS),
            "actions_missing": dict(actions=handlers.ACTIONS - {"stop"}, handlers=handlers.HANDLERS, events=events.EVENTS),
            "handlers": dict(actions=handlers.ACTIONS, handlers=handlers.HANDLERS - {"rooms"}, events=events.EVENTS),
            "handlers_extra": dict(actions=handlers.ACTIONS, handlers=handlers.HANDLERS | {"x"}, events=events.EVENTS),
            "events": dict(actions=handlers.ACTIONS, handlers=handlers.HANDLERS, events=events.EVENTS - {"notice"}),
            "events_extra": dict(actions=handlers.ACTIONS, handlers=handlers.HANDLERS, events=events.EVENTS | {"zzz"}),
        }
        for name, kwargs in cases.items():
            with self.subTest(name), self.assertRaises(flow.FlowError):
                self.flow.check_registries(**kwargs)

    def test_handler_screens_have_runners(self) -> None:
        for screen in self.flow.screens.values():
            if screen.options:
                self.assertIsNotNone(screen.handler, screen.id)
            if screen.handler:
                self.assertIn(screen.handler, handlers._HANDLER_RUNNERS)
        for action in handlers.ACTIONS:
            self.assertIn(action, handlers._ACTION_RUNNERS)

    def test_text_tokens_are_exactly_the_old_ones(self) -> None:
        by_action: dict[str, set[str]] = {}
        for token, action in self.flow._action_tokens.items():
            by_action.setdefault(action, set()).add(token)
        for action, tokens in EXPECTED_TOKENS.items():
            self.assertEqual(by_action[action], tokens, action)
        self.assertEqual(self.flow._goto_tokens, {})

    def test_ids_and_text_keys(self) -> None:
        pattern = re.compile(r"^[a-z][a-z0-9_]*$")
        for key in [*self.flow.screens, *self.flow.texts]:
            self.assertRegex(key, pattern)

    def test_text_formatting(self) -> None:
        self.assertEqual(self.flow.text("toast_city", city="X"), "Город: X")
        self.assertEqual(self.flow.text("partner_message", text="{x}"), "👤 Собеседник:\n{x}")
        with self.assertRaises(flow.FlowError):
            self.flow.text("no_such_text")
        for key in flow.TEXT_FIELDS:
            self.assertIn(key, self.flow.texts)

    def test_start_button_marker_is_in_the_greeting(self) -> None:
        self.assertIn(self.flow.text("start_button_marker"), self.flow.screen("start_inline").text)

    def test_cli_summary_and_exit_code(self) -> None:
        with patch("builtins.print") as printed:
            self.assertEqual(flow.main(), 0)
        self.assertRegex(printed.call_args.args[0], r"^flow загружен: \d+ экранов, \d+ текстов$")
        with patch.object(flow, "load", side_effect=flow.FlowError("x")), patch("builtins.print"):
            self.assertEqual(flow.main(), 1)


class BrokenFlowTests(unittest.TestCase):
    """Любая правка CRM, ломающая связи, даёт FlowError с путём до поля."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(flow.FLOW_DIR / "images", self.tmp / "images")

    def write(self, data: dict | str) -> Path:
        path = self.tmp / "flow.yaml"
        text = data if isinstance(data, str) else yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        path.write_text(text, encoding="utf-8")
        return path

    def assert_error(self, data: dict | str, *needles: str) -> None:
        with self.assertRaises(flow.FlowError) as ctx:
            flow.load(self.write(data))
        for needle in needles:
            self.assertIn(needle, str(ctx.exception))

    def test_valid_copy_loads(self) -> None:
        flow.load(self.write(base_data()))

    def test_broken_yaml(self) -> None:
        self.assert_error("screens: [unclosed\n  - : :")

    def test_missing_file(self) -> None:
        with self.assertRaises(flow.FlowError):
            flow.load(self.tmp / "nope.yaml")

    def test_duplicate_yaml_key(self) -> None:
        self.assert_error("version: 1\nversion: 1\n", "version")

    def test_unknown_field(self) -> None:
        data = base_data()
        data["screens"]["main"]["colour"] = "red"
        self.assert_error(data, "colour")

    def test_goto_to_missing_screen(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0] = {"text": "Куда", "goto": "nowhere", "style": "primary"}
        self.assert_error(data, "screens.main.buttons[0][0].goto", "nowhere")

    def test_next_to_missing_screen(self) -> None:
        data = base_data()
        data["screens"]["settings"]["next"] = "nowhere"
        self.assert_error(data, "screens.settings.next", "nowhere")

    def test_button_next_to_missing_screen(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0]["next"] = "nowhere"
        self.assert_error(data, "buttons[0][0].next")

    def test_buttons_from_missing_screen(self) -> None:
        data = base_data()
        data["screens"]["undelivered"]["buttons_from"] = "nowhere"
        self.assert_error(data, "screens.undelivered.buttons_from")

    def test_start_missing(self) -> None:
        data = base_data()
        data["start"] = "nowhere"
        self.assert_error(data, "start")

    def test_missing_image(self) -> None:
        data = base_data()
        data["screens"]["start_inline"]["image"] = "images/absent.jpg"
        self.assert_error(data, "screens.start_inline.image")

    def test_bad_image_path(self) -> None:
        data = base_data()
        data["screens"]["start_inline"]["image"] = "../greeting.jpg"
        self.assert_error(data, "image")

    def test_text_too_long_for_vk(self) -> None:
        data = base_data()
        data["screens"]["main"]["text"] = "я" * 4097
        self.assert_error(data, "screens.main.text")

    def test_button_label_over_40(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0]["text"] = "я" * 41
        self.assert_error(data, "screens.main.buttons[0][0].text", "40")

    def test_option_label_over_40_with_mark(self) -> None:
        data = base_data()
        data["screens"]["rooms"]["options"]["items"]["msk"] = "я" * 39
        self.assert_error(data, "screens.rooms.options.rows", "40")

    def test_payload_over_255(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0]["payload"] = {"command": "start", "blob": "x" * 250}
        self.assert_error(data, "screens.main.buttons[0][0]", "255")

    def test_option_callback_over_schema_limit(self) -> None:
        data = base_data()
        data["screens"]["rooms"]["options"]["callback"] = '{"command": "room", "pad": "' + "x" * 60 + '", "room": "{key}"}'
        self.assert_error(data, "screens.rooms.options.callback")

    def test_option_callback_must_be_json_with_command(self) -> None:
        data = base_data()
        data["screens"]["rooms"]["options"]["callback"] = "room:{key}"
        self.assert_error(data, "screens.rooms.options.callback", "command")

    def test_too_many_buttons_in_row(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0] = [
            {"text": f"b{i}", "action": "start", "style": "primary"} for i in range(6)
        ]
        self.assert_error(data, "5 кнопок")

    def test_too_many_rows_in_inline_keyboard(self) -> None:
        data = base_data()
        data["screens"]["chat"]["buttons"] = [
            [{"text": f"b{i}", "action": "start", "style": "primary"}] for i in range(7)
        ]
        self.assert_error(data, "screens.chat", "6")

    def test_duplicate_token_with_different_action(self) -> None:
        data = base_data()
        data["screens"]["chat"]["buttons"][0][0] = {"text": "🔍 Найти собеседника", "action": "stop", "style": "primary"}
        self.assert_error(data, "уже занят")

    def test_inline_button_text_is_a_token_in_vk(self) -> None:
        data = base_data()
        data["screens"]["partner_left"]["buttons"][1][0]["text"] = "Остановить диалог"
        self.assert_error(data, "уже занят")

    def test_button_needs_exactly_one_of_action_goto_url(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0] = {"text": "Две цели", "action": "start", "goto": "chat"}
        self.assert_error(data, "buttons[0][0]")

    def test_url_must_be_https_or_premium_placeholder(self) -> None:
        data = base_data()
        data["screens"]["premium"]["buttons"][0][0]["url"] = "http://evil.example/"
        self.assert_error(data, "url")

    def test_reply_keyboard_has_no_url_buttons(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0] = {"text": "Ссылка", "url": "https://example.com/", "style": "primary"}
        self.assert_error(data, "url")

    def test_buttons_from_cycle(self) -> None:
        data = base_data()
        data["screens"]["undelivered"]["buttons_from"] = "age"
        data["screens"]["age"]["buttons_from"] = "undelivered"
        self.assert_error(data, "цикл")

    def test_options_default_must_exist(self) -> None:
        data = base_data()
        data["screens"]["rooms"]["options"]["default"] = "mars"
        self.assert_error(data, "default")

    def test_options_without_handler(self) -> None:
        data = base_data()
        del data["screens"]["rooms"]["handler"]
        self.assert_error(data, "screens.rooms.options", "handler")

    def test_bad_screen_id(self) -> None:
        data = base_data()
        data["screens"]["Bad-Id"] = copy.deepcopy(data["screens"]["notice"])
        self.assert_error(data, "Bad-Id")

    def test_row_limit_of_schema(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0] = [{"text": f"b{i}", "goto": "chat"} for i in range(9)]
        self.assert_error(data, "buttons[0]")

    def test_text_template_unknown_field(self) -> None:
        data = base_data()
        data["texts"]["toast_city"] = "Город: {city} ({region})"
        self.assert_error(data, "texts.toast_city", "region")

    def test_text_template_missing_field(self) -> None:
        data = base_data()
        data["texts"]["partner_message"] = "👤 Собеседник"
        self.assert_error(data, "texts.partner_message", "text")

    def test_text_template_broken_format(self) -> None:
        data = base_data()
        data["texts"]["premium_active_until"] = "до {date"
        self.assert_error(data, "texts.premium_active_until")
        data["texts"]["premium_active_until"] = "до {date.year}"
        self.assert_error(data, "texts.premium_active_until")
        data["texts"]["premium_active_until"] = "до {date} {0}"
        self.assert_error(data, "texts.premium_active_until")

    def test_plain_text_with_placeholder(self) -> None:
        data = base_data()
        data["texts"]["searching"] = "Ищем {who}"
        self.assert_error(data, "texts.searching", "who")

    def test_on_key_stays_a_string(self) -> None:
        """В YAML 1.1 on — булево значение; загрузчик flow его не превращает."""
        self.assertEqual(flow.load(self.write(FLOW_YAML.read_text(encoding="utf-8"))).screens["chat"].on, "partner_found")


class ButtonPayloadTests(unittest.TestCase):
    def test_default_payloads(self) -> None:
        self.assertEqual(flow.Button("x", action="start").payload_json(), '{"command": "start"}')
        self.assertEqual(flow.Button("x", goto="chat").payload_json(), '{"command": "go", "screen": "chat"}')
        self.assertEqual(flow.Button("x", action="start", payload={"command": "start", "a": 1}).payload_json(), '{"command": "start", "a": 1}')


if __name__ == "__main__":
    unittest.main()
