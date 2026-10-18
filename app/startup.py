"""Проверка доступа к Long Poll и совместимость ответов VK с Pydantic."""

import requests

from app.config import API_VERSION


def rebuild_vkbottle_response_models() -> None:
    """Дособирает модели ответов VK, которые Pydantic 2.13 не собирает на Python 3.10.

    Иначе messages.send падает с ошибкой: MessagesSendPeerIdsResponse is not fully defined.
    """
    import vkbottle_types.objects as objects
    import vkbottle_types.responses as responses
    from vkbottle_types.base_model import BaseModel

    types_namespace = vars(objects)
    for model in vars(responses).values():
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            continue
        if model is BaseModel or model.__pydantic_complete__:
            continue
        if model.__module__.startswith("vkbottle_types.codegen"):
            continue
        model.model_rebuild(_types_namespace=types_namespace)


def preflight_check(token: str) -> tuple[int, str]:
    """Проверяет доступ к Long Poll до запуска бота. Возвращает id и название сообщества."""
    response = requests.get(
        "https://api.vk.com/method/groups.getById",
        params={"access_token": token, "v": API_VERSION},
        timeout=15,
    ).json()

    if "error" in response:
        err = response["error"]
        raise SystemExit(
            f"Токен невалиден или это не ключ сообщества.\n"
            f"VK Error [{err.get('error_code')}]: {err.get('error_msg')}\n"
            f"Возьмите ключ: Управление сообществом → Работа с API → Ключи доступа"
        )

    raw = response["response"]
    group = raw[0] if isinstance(raw, list) else raw["groups"][0]
    group_id = int(group["id"])

    lp = requests.get(
        "https://api.vk.com/method/groups.getLongPollServer",
        params={"access_token": token, "group_id": group_id, "v": API_VERSION},
        timeout=15,
    ).json()

    if "error" in lp:
        err = lp["error"]
        raise SystemExit(
            f"Нет доступа к Long Poll (это и есть Error 15 / 1133).\n"
            f"Сообщество: {group.get('name')} (id={group_id})\n"
            f"VK Error [{err.get('error_code')}] subcode={err.get('error_subcode')}: "
            f"{err.get('error_msg')}\n\n"
            f"Сделайте по шагам:\n"
            f"  1. Сообщения сообщества → включить\n"
            f"  2. Работа с API → Long Poll API → Включено\n"
            f"     + событие «Входящее сообщение» (message_new)\n"
            f"  3. Ключи доступа → НОВЫЙ ключ с правами:\n"
            f"       • Сообщения сообщества\n"
            f"       • Управление сообществом\n"
            f"  4. Вставьте новый ключ в .env без кавычек"
        )

    ensure_incoming_events(token, group_id)
    ensure_bot_capabilities(token, group_id)
    return group_id, str(group.get("name") or "")


def ensure_incoming_events(token: str, group_id: int) -> None:
    """Включает Long Poll и событие message_new, иначе бот молчит на любое сообщение."""
    current = requests.post(
        "https://api.vk.com/method/groups.getLongPollSettings",
        data={"access_token": token, "group_id": group_id, "v": API_VERSION},
        timeout=15,
    ).json()
    if "error" in current:
        err = current["error"]
        print(
            f"Не прочитал настройки Long Poll group_id={group_id}: "
            f"VK Error [{err.get('error_code')}] {err.get('error_msg')}"
        )
        return

    body = current.get("response") or {}
    events = dict(body.get("events") or {})
    was = 1 if events.get("message_new") else 0
    events["message_new"] = 1
    events["message_event"] = 1
    params: dict = {
        "access_token": token,
        "group_id": group_id,
        "v": API_VERSION,
        "enabled": 1,
        "api_version": API_VERSION,
    }
    for name, flag in events.items():
        params[name] = 1 if flag else 0
    saved = requests.post(
        "https://api.vk.com/method/groups.setLongPollSettings",
        data=params,
        timeout=15,
    ).json()
    if "error" in saved:
        err = saved["error"]
        print(
            f"Не включил message_new group_id={group_id}: "
            f"VK Error [{err.get('error_code')}] {err.get('error_msg')}. "
            f"Сейчас message_new={was}."
        )
        return
    print(f"Long Poll message_new включён (group_id={group_id}, было={was}).")


def ensure_bot_capabilities(token: str, group_id: int) -> None:
    """Включает клавиатуры сообщества. Иначе VK отвечает 912 и кнопка не уходит."""
    saved = requests.post(
        "https://api.vk.com/method/groups.setSettings",
        data={
            "access_token": token,
            "group_id": group_id,
            "v": API_VERSION,
            "bots_capabilities": 1,
            "bots_start_button": 1,
            "bots_add_to_chat": 1,
        },
        timeout=15,
    ).json()
    if "error" in saved:
        err = saved["error"]
        print(
            f"Не включил возможности ботов group_id={group_id}: "
            f"VK Error [{err.get('error_code')}] {err.get('error_msg')}"
        )
        return
    print(f"Возможности ботов включены (group_id={group_id}).")
