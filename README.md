# Grok TG Assistant

[![Version](https://img.shields.io/badge/version-1.2.0-22d3ee?style=for-the-badge)](https://github.com/Quadart21/Grok_Tg_Assistant/releases/tag/v1.2.0)
[![Python](https://img.shields.io/badge/python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-a78bfa?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-34d399?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/Quadart21/Grok_Tg_Assistant)

**Kot_Teamlead** — локальная панель для Telegram outreach и AI-диалогов.  
Работает только на вашем ПК: веб-интерфейс в браузере, без облака и без передачи сессий третьим лицам.

---

## Возможности

| Раздел | Что умеет |
|--------|-----------|
| **Рассылка** | Первые сообщения по username, запуск/стоп, журнал, продолжение диалогов |
| **Подключение** | Telegram API, ключи LLM, тайминги, 2FA |
| **Аккаунты** | tdata → session, фильтры, массовый профиль, привязка прокси |
| **Прокси** | Пул с проверкой, страна/пинг, массовый импорт и auto-bind |
| **Стиль** | Мастер-промпт, роли, назначение на аккаунты |
| **Переписки** | Память диалогов, лимиты, стоп-слова |
| **AI Агент** | Личный секретарь на отдельном аккаунте (вне рассылки) |
| **Групповой чат** | Свои аккаунты общаются в общем чате по теме/ролям, с расписанием и «живостью» |

**LLM:** Grok (xAI), OpenAI, Gemini, Claude, DeepSeek, OpenRouter, **Local** (llama.cpp / OpenAI-compatible).

---

## Быстрый старт

### Требования

- Windows 10/11
- **Python 3.10+** (панель)
- **Python 3.10–3.12** — только если нужна конвертация **tdata → .session**
- Ключи Telegram: [my.telegram.org/apps](https://my.telegram.org/apps)

### Установка Python (если нет 3.11)

**Способ 1 — winget (без браузера):**
```bat
winget install Python.Python.3.11
```
или запустите `install_python.bat` в папке проекта.

**Способ 2 — прямая ссылка на установщик:**
https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe

При установке отметьте **«Add python.exe to PATH»**.

**Если стоит только Python 3.13+** — панель всё равно запустится (`start.bat`), но конвертер tdata будет отключён.

### Запуск

```bat
start.bat
```

`start.bat` сам выберет Python 3.11 → 3.12 → 3.10, при отсутствии попробует winget, иначе возьмёт 3.13+ в режиме «только панель».

Откроется браузер: **http://127.0.0.1:8787/**

---

## Структура проекта

```
Grok_Tg_Assistant/
├── main.py              # Точка входа
├── start.bat            # Запуск под Windows
├── core/                # Backend: API, движки, прокси, LLM
├── web/panel/           # Веб-панель (HTML, CSS, JS)
├── config/              # Настройки (*.example.json — шаблоны)
├── sessions/            # .session и tdata (не в git)
├── data/                # state.json — история диалогов
├── docs/TZ.md           # Полное техническое задание
└── scripts/             # Сборка фронтенда
```

---

## Версии

| Версия | Дата | Описание |
|--------|------|----------|
| [**v1.2.0**](https://github.com/Quadart21/Grok_Tg_Assistant/releases/tag/v1.2.0) | 20.07.2026 | Вступление аккаунтов в Telegram-чат по публичной или invite-ссылке из вкладки группового чата |
| [**v1.1.0**](https://github.com/Quadart21/Grok_Tg_Assistant/releases/tag/v1.1.0) | 19.07.2026 | Групповой чат аккаунтов + Local LLM (llama.cpp) |
| [**v1.0.0**](https://github.com/Quadart21/Grok_Tg_Assistant/releases/tag/v1.0.0) | 02.07.2026 | Первый публичный релиз |

Подробности — в [CHANGELOG.md](CHANGELOG.md).

---

## Безопасность

- Не коммитьте `config/settings.json`, сессии и ключи API.
- Панель слушает только `127.0.0.1` — доступ с других машин по умолчанию закрыт.
- Используйте прокси для аккаунтов при массовой работе.

---

## Разработчик

**Kot_Teamlead**

---

## Лицензия

[MIT](LICENSE) — см. файл LICENSE.
