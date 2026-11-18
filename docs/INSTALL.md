# Установка

## Что понадобится

* Docker Engine 24+ и Docker Compose v2 на машине, где будет работать стек.
* Связь с инвертором одним из способов:
  * **нативный USB** инвертора (USB-HID) — только на машине, куда воткнут кабель;
  * **USB-RS232 / RS485** адаптер — то же;
  * **сеть**: донгл EW10 (`:9999`), `ser2net`, ESP32-шлюз, `usbip`;
  * **импорт** из уже работающей SolarAssistant (её MQTT-выход).
* Для VDS: физического USB там нет — подойдёт только сетевой путь.

## Развёртывание одним скриптом

```bash
git clone <repo> /opt/solar-monitor     # или скопируйте каталог проекта
cd /opt/solar-monitor
./tools/deploy.sh                       # всё по умолчанию
```

Скрипт `tools/deploy.sh` делает:

1. проверяет `docker` и `docker compose` (v2) и доступ к демону;
2. если `.env` нет — создаёт из `.env.example` и **генерирует секреты**
   (`INFLUX_TOKEN`, `INFLUX_PASSWORD`, `GRAFANA_PASSWORD`), ставит `chmod 600`;
3. применяет параметры из аргументов (`--site`, `--transport`, `--tcp-host`, `--tcp-port`,
   `--mqtt-host`);
4. создаёт каталоги `data/{influxdb,influxdb-config,grafana,collector}` и (под root) выставляет
   `data/grafana` владельца uid 472;
5. собирает и поднимает стек, ждёт `/healthz` до 90 с и печатает адреса + пароль Grafana.

Полезные флаги:

```bash
./tools/deploy.sh --site office --transport sa-mqtt --office   # второй сайт
./tools/deploy.sh --transport serial                           # USB-RS232
./tools/deploy.sh --no-build                                   # без пересборки образа
./tools/deploy.sh --no-start                                   # только подготовить .env и каталоги
```

Повторный запуск безопасен: существующий `.env` не перезаписывается, данные не трогаются.

## Быстрый старт

```bash
git clone <repo> ~/solar-monitor && cd ~/solar-monitor
cp .env.example .env
$EDITOR .env                     # SITE, TRANSPORT, MQTT_*, токены (см. CONFIGURATION.md)
docker compose up -d --build
docker compose logs -f collector
```

После первого запуска: **логин `admin`, пароль `admin`** (из `.env`) — сразу смените его в
интерфейсе: Настройки → Уставки → «Доступ к интерфейсу».

Открыть:
* UI + API — `http://<host>:8080/`
* Grafana — `http://<host>:3000/` (папка Solar → Solar overview)
* health — `http://<host>:8080/healthz`

`docker compose config` покажет итоговую конфигурацию, `docker compose ps` — состояние.

## Mini PC (USB в инвертор)

1. Найти устройство: `ls -l /dev/hidraw* /dev/ttyUSB* /dev/serial/by-id/`.
2. В `.env`:
   ```dotenv
   TRANSPORT=hid                 # или serial
   HID_DEVICE=/dev/hidraw0       # или SERIAL_PORT=/dev/ttyUSB0, SERIAL_BAUD=2400
   ```
3. В `docker-compose.yml` раскомментировать проброс:
   ```yaml
   devices:
     - /dev/hidraw0:/dev/hidraw0
     # - /dev/ttyUSB0:/dev/ttyUSB0
   group_add:
     - dialout
   ```
4. `docker compose up -d --build`.

Проверка без контейнера (на хосте): `lsusb` → должно быть `0665:5161` (инвертор) либо
USB-serial мост (`1a86`, `10c4`, `0403` и т.п.).

## VDS / удалённая машина (сеть)

```dotenv
TRANSPORT=tcp
TCP_HOST=<ip донгла или шлюза>
TCP_PORT=9999
```

Варианты сетевого пути:

| Способ | Как настроить |
|---|---|
| Донгл EW10 | он сам слушает TCP `:9999` (инвертор отвечает на кадры PI30) |
| `ser2net` на Raspberry/Orange Pi | `2000:raw:0:/dev/ttyUSB0:2400 8DATABITS NONE 1STOPBIT` |
| ESP32-шлюз | свой TCP-сервер, прокидывающий кадры на UART |
| `usbip` | `usbipd` на машине с USB, `usbip attach` на VDS (нестабильно для HID) |

## Synology NAS

Docker на DSM работает только через `sudo`:

```bash
sudo /var/packages/ContainerManager/target/usr/bin/docker compose up -d --build
```

Особенности:

* **InfluxDB 2.x на DSM зависает** (bolt + btrfs + старое ядро) — используйте
  `docker-compose.synology.yml` (InfluxDB 1.8, InfluxQL):
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.synology.yml up -d --build
  ```
  и в `.env`: `INFLUX_MODE=1.8`, `INFLUX_DB=solar`, дашборд пересобрать:
  `INFLUX_MODE=1.8 python3 tools/make_dashboard.py`.
* USB-устройства в DSM прокидывать ненадёжно — на NAS используйте `TRANSPORT=tcp`.
* Каталоги `./data/*` нужно создать заранее (`mkdir -p data/{influxdb,influxdb-config,grafana,collector}`),
  иначе DSM-докер откажется стартовать bind-mount.
* Каталог `data/grafana` должен принадлежать uid **472**: `chown -R 472:472 data/grafana`.

## Второй сайт (второй инвертор)

```bash
cp .env.office.example .env.office      # SITE=office, свой MQTT_PREFIX и транспорт
docker compose -f docker-compose.yml -f docker-compose.office.yml up -d --build
```

Каждый коллектор публикует состояние в `<SITE_ROOT>/<site>/state`; UI одного коллектора видит
все сайты (селектор в шапке). Подробнее — [INTEGRATIONS.md](INTEGRATIONS.md).

## Обновление

```bash
git pull
docker compose up -d --build          # коллектор пересобирается
docker compose -f docker-compose.yml -f docker-compose.office.yml up -d --build   # если есть 2-й сайт
```

Данные в `./data` сохраняются; конфигурация в `/data/*.json` переживает обновление.

## Удаление

```bash
docker compose down            # остановить
docker compose down -v         # + удалить тома (история InfluxDB!)
rm -rf data/                   # + локальные данные и конфиги
```
