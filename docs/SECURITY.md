# Безопасность

## Что по умолчанию открыто (и почему это важно)

Коллектор отдаёт UI и API на `0.0.0.0:8080` **без авторизации**, если не заданы `AUTH_USER` /
`AUTH_PASSWORD`. Это удобно в домашней сети, но означает: любой в сети может

* смотреть данные;
* **менять уставки инвертора** (`POST /api/v1/settings`) — в том числе напряжения заряда;
* переключать протокол BMS и транспорт подключения.

Если к сети есть доступ у гостей/устройств IoT — включите авторизацию.

## Пароль: где он лежит

| Что | Где | Примечание |
|---|---|---|
| Логин/пароль по умолчанию | `.env` → `AUTH_USER=admin`, `AUTH_PASSWORD=admin` | **смените после установки** |
| Пароль, изменённый в интерфейсе | `/data/auth.json` (PBKDF2-хэш, `0600`) | перекрывает `.env` |
| Grafana за Caddy (`:3443`) | `data/caddy.env` (bcrypt) | генерируется `tools/set-grafana-proxy.sh` |
| Сам Grafana | `GRAFANA_PASSWORD` в `.env` (первый старт) | логин внутри Grafana |

Если задан пароль в интерфейсе, `auth.json` главнее; «забыл» = удалить файл
(`docker compose exec collector rm /data/auth.json`) и перезапустить → вернётся `.env`-пароль.
Пока действует `admin/admin`, в интерфейсе висит красная плашка с напоминанием, а в лог пишется
предупреждение.

## Вариант 1: HTTP Basic (минимум)

```dotenv
AUTH_USER=admin
AUTH_PASSWORD=admin        # смените сразу после установки (или ./tools/deploy.sh --auth --random-password)
```

* закрывает UI и весь `/api/v1/*`, кроме `/healthz` (нужен docker healthcheck);
* для скриптов удобнее токен: `API_TOKEN=<токен>` → `Authorization: Bearer <токен>`;
* **Basic без TLS передаёт пароль в base64 открытым текстом** — годится для доверенной LAN,
  но не для интернета и не для Wi-Fi-гостя.

Быстро включить: `./tools/deploy.sh --auth` (сгенерирует пароль и покажет его).

## Вариант 2: Basic + HTTPS (рекомендуется)

```bash
./tools/gen-cert.sh solar-monitor.local 192.168.1.50   # самоподписанный, 10 лет
```

```dotenv
TLS_CERT=/certs/server.crt
TLS_KEY=/certs/server.key
AUTH_USER=admin
AUTH_PASSWORD=<пароль>
```

или одной командой: `./tools/deploy.sh --auth --tls`.

* Сервер поднимается по **HTTPS на том же `API_PORT`** (HTTP отключается); healthcheck понимает
  оба протокола.
* Браузер покажет предупреждение о самоподписанном сертификате — это ожидаемо; можно добавить
  сертификат в доверенные на своих устройствах.
* Сертификаты лежат в `data/certs/` и монтируются в контейнер как `/certs:ro`.

## Grafana за Caddy (HTTPS + Basic)

Grafana слушает только `127.0.0.1:3000`, наружу — Caddy на `https://<host>:3443/`:

```bash
./tools/set-grafana-proxy.sh 'пароль' admin     # создаёт data/caddy.env
docker compose up -d --force-recreate caddy
```

**Грабли:** Compose интерполирует значения из `env_file`, поэтому `$` в bcrypt-хэше надо
экранировать как `$$` — иначе хэш превращается в `$2a$14` и Caddy отвечает
`hashedSecret too short to be a bcrypted password`. Скрипт делает это сам.

## Смена пароля из интерфейса

**Настройки → Уставки → «Доступ к интерфейсу»**: текущий пароль, новый и подтверждение.

* пароль хранится как **PBKDF2-SHA256** (200 000 итераций, соль 16 байт) в
  `/data/auth.json` (права `0600`), открытого пароля в файле нет;
* файл **перекрывает** `AUTH_USER`/`AUTH_PASSWORD` из `.env` — старый пароль перестаёт работать
  сразу, перезапуск не нужен;
* API: `GET /api/v1/auth` (кто и откуда), `POST /api/v1/auth/password`
  `{"current_password","new_password"[,"user"]}`;
* минимум 6 символов, текущий пароль обязателен;
* «забыл пароль» = удалить `/data/auth.json` (или `docker compose exec collector rm /data/auth.json`)
  и перезапустить — вернётся пароль из `.env`;
* **Grafana (порт 3443) и Caddy имеют свой пароль** — их это не меняет (Caddy — `GRAFANA_PROXY_HASH`,
  Grafana — `GRAFANA_PASSWORD`).

## Мультисайт и авторизация

Прокси `?site=<peer>` пересылает заголовок `Authorization` как есть, поэтому:

* **проще всего** — одинаковые `AUTH_USER`/`AUTH_PASSWORD` на всех коллекторах;
* если креды разные, задайте их для пира:

```dotenv
PEER_SITES={"office":{"url":"https://192.168.1.51:8080","user":"admin","pass":"..."}}
PEER_TLS_VERIFY=false        # самоподписанный сертификат соседа
```

## Инфраструктура

| Что | Рекомендация |
|---|---|
| MQTT-брокер | не оставляйте `allow_anonymous true` в открытой сети: логин/пароль + ACL на `solar/#` |
| InfluxDB | публикуйте только на `127.0.0.1` (так и сделано), Grafana — с паролем администратора |
| Grafana | смените `GRAFANA_PASSWORD`, не публикуйте порт наружу без TLS |
| SSH к хосту | ключи вместо пароля (как на этом проекте), отдельный пользователь для деплоя |
| Публикация в интернет | только через reverse-proxy с TLS + auth (Caddy/Traefik/nginx) или Tailscale/WireGuard |
| Секреты | `.env` (chmod 600) и `/data/*.json`; в git их нет (`.gitignore`) |

## Что делает сам коллектор

* `AUTH_*` — Basic на UI и API (кроме `/healthz`);
* `API_TOKEN` — Bearer для машинного доступа (обходит Basic);
* `TLS_CERT`/`TLS_KEY` — HTTPS;
* `/healthz` намеренно открыт: он отдаёт только счётчики, без данных инвертора;
* уведомления и прогноз ходят наружу по HTTPS (Telegram API, forecast.solar).

## Аудит

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://<host>:8080/                 # 200 = открыто
curl -s -o /dev/null -w '%{http_code}\n' -u admin:pass http://<host>:8080/    # 200 = авторизация работает
curl -sk -o /dev/null -w '%{http_code}\n' https://<host>:8080/healthz         # 200 = TLS живой
```
