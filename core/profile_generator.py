"""Генерация имён, фамилий и ников для массовой смены профиля Telegram."""

from __future__ import annotations

import random
import re
import secrets
from dataclasses import dataclass

_CYRILLIC = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)

FIRST_NAMES_RU_M = (
    "Алексей", "Андрей", "Артём", "Виктор", "Дмитрий", "Егор", "Иван", "Кирилл",
    "Максим", "Михаил", "Никита", "Павел", "Роман", "Сергей", "Тимофей", "Фёдор",
    "Борис", "Владимир", "Глеб", "Денис", "Константин", "Олег", "Станислав", "Юрий",
)

FIRST_NAMES_RU_F = (
    "Алина", "Анастасия", "Вера", "Дарья", "Екатерина", "Ирина", "Ксения", "Мария",
    "Наталья", "Ольга", "Полина", "София", "Татьяна", "Юлия", "Яна", "Елена",
    "Виктория", "Анна", "Евгения", "Людмила", "Светлана", "Кристина", "Диана",
)

LAST_NAMES_RU = (
    "Иванов", "Петров", "Сидоров", "Смирнов", "Кузнецов", "Попов", "Васильев",
    "Соколов", "Михайлов", "Новиков", "Фёдоров", "Морозов", "Волков", "Алексеев",
    "Лебедев", "Семёнов", "Егоров", "Павлов", "Козлов", "Степанов", "Никитин",
    "Орлов", "Андреев", "Макаров", "Николаев", "Захаров", "Зайцев", "Соловьёв",
    "Борисов", "Яковлев", "Григорьев", "Романов", "Воробьёв", "Сергеев", "Куликов",
)

FIRST_NAMES_EN_M = (
    "James", "John", "Michael", "David", "Daniel", "Matthew", "Andrew", "Ryan",
    "Lucas", "Ethan", "Noah", "Liam", "Oliver", "Benjamin", "Henry", "Alexander",
)

FIRST_NAMES_EN_F = (
    "Emily", "Emma", "Olivia", "Sophia", "Ava", "Isabella", "Mia", "Charlotte",
    "Amelia", "Harper", "Evelyn", "Abigail", "Elizabeth", "Victoria", "Grace", "Chloe",
)

LAST_NAMES_EN = (
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Wilson",
    "Moore", "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin",
    "Thompson", "Garcia", "Martinez", "Robinson", "Clark", "Lewis", "Lee", "Walker",
)

NICK_ADJ_RU = (
    "Тихий", "Быстрый", "Смелый", "Лунный", "Горный", "Северный", "Ясный", "Серый",
    "Дикий", "Скрытый", "Острый", "Свободный", "Хитрый", "Редкий", "Глубокий",
)

NICK_NOUN_RU = (
    "Волк", "Сокол", "Беркут", "Рысь", "Орёл", "Лис", "Медведь", "Ястреб",
    "Страж", "Странник", "Охотник", "Пилот", "Искатель", "Стрелок", "Мастер",
)

NICK_ADJ_EN = (
    "Silent", "Swift", "Brave", "Lunar", "Arctic", "Clever", "Hidden", "Wild",
    "Lucky", "Golden", "Silver", "Shadow", "Cosmic", "Neon", "Royal",
)

NICK_NOUN_EN = (
    "Fox", "Hawk", "Wolf", "Eagle", "Tiger", "Panther", "Falcon", "Raven",
    "Pilot", "Scout", "Hunter", "Walker", "Knight", "Nomad", "Spirit",
)


@dataclass
class GeneratedProfile:
    first_name: str
    last_name: str
    username: str


def transliterate(text: str) -> str:
    lower = text.lower().translate(_CYRILLIC)
    return re.sub(r"[^a-z0-9]", "", lower)


def make_username(base: str, used: set[str], rng: random.Random) -> str:
    slug = transliterate(base) or "user"
    slug = re.sub(r"[^a-z0-9_]", "", slug.lower())[:24]
    if len(slug) < 3:
        slug = f"user{rng.randint(100, 9999)}"
    for _ in range(40):
        suffix = rng.randint(10, 9999)
        candidate = f"{slug}_{suffix}"
        if len(candidate) < 5:
            candidate = f"{slug}{suffix}"
        candidate = candidate[:32]
        if candidate not in used and re.fullmatch(r"[a-z][a-z0-9_]{4,31}", candidate):
            used.add(candidate)
            return candidate
    fallback = f"user_{secrets.token_hex(3)}"
    used.add(fallback)
    return fallback


def feminize_russian_surname(surname: str) -> str:
    """Мужская фамилия → женская (Иванов → Иванова, Сергеев → Сергеева)."""
    if surname.endswith("ский"):
        return surname[:-2] + "ая"
    if surname.endswith("ой"):
        return surname[:-2] + "ая"
    if surname.endswith("ёв"):
        return surname + "а"
    if surname.endswith(("ов", "ев", "ин", "ын")):
        return surname + "а"
    if surname.endswith("ий"):
        return surname[:-2] + "ая"
    return surname + "а"


def generate_name_pair(lang: str, rng: random.Random) -> tuple[str, str]:
    female = rng.random() < 0.5
    if lang == "en":
        first = rng.choice(FIRST_NAMES_EN_F if female else FIRST_NAMES_EN_M)
        return first, rng.choice(LAST_NAMES_EN)
    last_masc = rng.choice(LAST_NAMES_RU)
    if female:
        return rng.choice(FIRST_NAMES_RU_F), feminize_russian_surname(last_masc)
    return rng.choice(FIRST_NAMES_RU_M), last_masc


def generate_nick(lang: str, rng: random.Random) -> str:
    if lang == "en":
        adj, noun = rng.choice(NICK_ADJ_EN), rng.choice(NICK_NOUN_EN)
        if rng.random() < 0.35:
            return f"{adj}{noun}{rng.randint(1, 99)}"
        return f"{adj} {noun}"
    adj, noun = rng.choice(NICK_ADJ_RU), rng.choice(NICK_NOUN_RU)
    if rng.random() < 0.35:
        return f"{adj}{noun}{rng.randint(1, 99)}"
    return f"{adj} {noun}"


def generate_profile(
    mode: str,
    lang: str,
    *,
    with_username: bool,
    used_usernames: set[str],
    rng: random.Random | None = None,
) -> GeneratedProfile:
    """mode: names | nicks"""
    rnd = rng or random.Random()
    lang = "en" if lang == "en" else "ru"

    if mode == "nicks":
        nick = generate_nick(lang, rnd)
        username = make_username(nick, used_usernames, rnd) if with_username else ""
        return GeneratedProfile(first_name=nick, last_name="", username=username)

    first, last = generate_name_pair(lang, rnd)
    username = ""
    if with_username:
        base = f"{first}{last}"
        username = make_username(base, used_usernames, rnd)
    return GeneratedProfile(first_name=first, last_name=last, username=username)


def preview_profiles(
    mode: str,
    lang: str,
    count: int,
    with_username: bool,
) -> list[dict[str, str]]:
    count = max(1, min(int(count), 20))
    used: set[str] = set()
    rng = random.Random()
    samples = []
    for _ in range(count):
        profile = generate_profile(mode, lang, with_username=with_username, used_usernames=used, rng=rng)
        samples.append(
            {
                "first_name": profile.first_name,
                "last_name": profile.last_name,
                "username": profile.username,
            }
        )
    return samples
