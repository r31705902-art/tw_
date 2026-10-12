# opencode on Railway

Веб-консоль с полноценным OpenCode CLI, задеплоенная на Railway. Открываете ссылку
Railway, вводите логин/пароль — и попадаете в TUI прямо в браузере.

Схема: браузер (через Tor Browser) → Railway → `ttyd` (веб-терминал) → `opencode` CLI.

Никакого самописного веб-интерфейса — терминал настоящий, с полноценным TUI.

---

## Что внутри

| Слой | Решение | Почему |
|---|---|---|
| Базовый образ | `debian:bookworm-slim` | маленький, glibc (musl-сборка opencode не нужна) |
| OpenCode | официальный standalone-бинарь v2 | качается с `opencode.ai/update/api/latest`, артефакт один — 98 МБ |
| Терминал | `ttyd` 1.7.7, статическая сборка | в Debian bookworm его нет (только sid/forky), поэтому берём готовый бинарь с GitHub |
| Авторизация | Basic auth внутри `ttyd` | Railway-ссылки публичные, без пароля любой может жечь ваши ключи |

`ENTRYPOINT` — `tini`, чтобы `SIGTERM` от Railway доходил до `opencode`, а не терялся.

Поддерживаются обе архитектуры: Railway выдаёт `amd64`, но `arm64` тоже собирается
(архитектура берётся из `TARGETARCH`, который проставляет buildx).

---

## Деплой

1. Создайте репозиторий на GitHub и запушьте содержимое этой папки.
2. В Railway: **New Project → Deploy from GitHub Repo** → выберите репозиторий.
   Railway сам увидит `Dockerfile` и `railway.json`, ничего настраивать не нужно.
3. Railway выдаст домен вида `https://<имя>.up.railway.app`.

Первый build занимает несколько минут: качается бинарь opencode (~210 МБ распакованного)
и ttyd.

### Обязательные переменные

Задаются в Railway → Variables:

| Переменная | Обязательна | По умолчанию | Назначение |
|---|---|---|---|
| `TTYD_PASSWORD` | **да** | `opencode` | пароль для входа в веб-консоль |
| `TTYD_USER` | нет | `opencode` | логин |
| `PORT` | нет | `8080` | Railway подставляет сам |
| `MAX_CLIENTS` | нет | `5` | сколько одновременных сессий |

**Пароль по умолчанию — это не защита.** Railway-ссылка публична: без смены `TTYD_PASSWORD`
любой, кто её угадает, получит доступ к вашим API-ключам. Образецно ругается в логах при старте.

### Необязательные

| Переменная | Назначение |
|---|---|
| `OPENCODE_CONFIG` | JSON с провайдерами (см. ниже) |
| `WORKDIR` | рабочая директория, по умолчанию `/workspace` |

---

## Настройка провайдера

Два способа, выбирайте любой.

### Способ 1 — прямо в консоли

После входа выполните в TUI:

```
/connect
```

и подключите провайдера. Конфиг сохранится в `/workspace` — если подключить
к этому сервису Railway Volume, настройки переживут передеплой.

### Способ 2 — переменная `OPENCODE_CONFIG`

Удобно, если не хотите вводить ключи руками или нужен конкретный провайдер.
В Railway → Variables, значение — одна строка JSON:

```json
{"$schema":"https://opencode.ai/config.json","provider":{"myprov":{"npm":"@ai-sdk/openai-compatible","name":"My Provider","options":{"baseURL":"https://example.com/v1","apiKey":"ВАШ_КЛЮЧ"},"models":{"my-model":{"name":"My Model"}}}}}
```

Секреты можно выносить в отдельные переменные и подставлять так:

```json
{"$schema":"https://opencode.ai/config.json","provider":{"myprov":{"npm":"@ai-sdk/openai-compatible","name":"My Provider","options":{"baseURL":"https://example.com/v1","apiKey":"{env:MY_PROVIDER_KEY}"},"models":{"my-model":{"name":"My Model"}}}}}
```

---

## Railway Volume (чтобы не терять сессии)

Без Volume файловая система контейнера ephemeral: при каждом деплое
конфигурация, сессии и история стираются.

1. Railway → сервис → **Volumes** → Add Volume, mount path `/workspace`.
2. Передеплойте.

`opencode` хранит конфиг и базу сессий рядом с рабочей директорией, поэтому
подключение Volume на `/workspace` закрывает задачу целиком.

---

## Доступ из Tor Browser

Railway-ссылка открывается в любом браузере. Чтобы заходить через Tor,
просто откройте её в Tor Browser — приложение не делает ничего, что мешало бы
работе через прокси.

Имейте в виду: инстанс на бесплатном тарифе засыпает при простое. Первое
обращение после сна занимает до десятка секунд — это нормально.

---

## Если нужно доустановить что-то

Базовый образ минимальный: `ca-certificates`, `curl`, `git`, `ripgrep`, `tini`.
Если понадобится Node.js (для MCP-серверов на `npx`) или что-то ещё —
добавьте в `Dockerfile` в секцию `apt-get install`:

```dockerfile
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git ripgrep tini \
      nodejs npm \
 && rm -rf /var/lib/apt/lists/*
```

Чтобы изменения применились, сделайте redeploy — Railway пересоберёт образ.

---

## Диагностика

**Контейнер перезапускается по кругу.** Скорее всего, `opencode` не запустился.
Смотрите логи в Railway — `entrypoint.sh` печатает версию opencode перед стартом.

**Открывается страница, но терминал не принимает ввод.** В `ttyd` ключ `--writable`
обязателен: без него терминал создаётся read-only. В `entrypoint.sh` он уже есть.

**`403` / пустая страница.** Проверьте `TTYD_USER` / `TTYD_PASSWORD` — ttyd отдаёт
`401` при неверных данных.

**Не находится opencode при сборке.** Проверьте, что `OPENCODE_CHANNEL=latest`
и архитектура из `TARGETARCH` — в `Dockerfile` есть осознанный `exit 1`
на неподдерживаемую архитектуру с понятным сообщением.