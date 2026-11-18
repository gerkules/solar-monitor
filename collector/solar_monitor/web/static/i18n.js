/* i18n: русский / английский / греческий.
   Язык берётся из браузера (navigator.language), переопределяется
   ?lang=xx в адресе или сохранённым выбором в localStorage. */
'use strict';

const I18N = {
  ru: {
    'nav.overview': 'Обзор', 'nav.grid': 'Сеть', 'nav.energy': 'Энергия',
    'nav.charts': 'Графики', 'nav.settings': 'Настройки',
    'sub.inverter': 'Инвертор', 'sub.battery': 'АКБ', 'sub.connection': 'Подключение',
    'sub.automation': 'Автоматизация', 'sub.codes': 'Коды', 'sub.setpoints': 'Уставки',

    'ov.flow': 'Потоки энергии', 'ov.gauges': 'Мощности', 'ov.energy_today': 'Энергия за сегодня',
    'ov.pv_arrays': 'Массивы PV', 'ov.state': 'Состояние',
    'flow.pv': 'PV', 'flow.grid': 'Сеть', 'flow.load': 'Нагрузка', 'flow.house': 'Дом',
    'flow.battery': 'АКБ', 'flow.inverter': 'Инвертор', 'flow.pv_dual': 'PV1 · PV2',
    'flow.pv_two_arrays': 'PV · 2 массива',
    'inv.offgrid': 'off-grid', 'inv.hybrid': 'гибридный', 'inv.gridtie': 'сетевой',
    'inv.parallel': 'параллельная система',
    'batt.discharge': 'разряд', 'batt.charge': 'заряд', 'batt.idle': 'ожидание',

    'energy.pv': 'Выработано PV', 'energy.load': 'Потреблено', 'energy.grid': 'Импорт из сети',
    'energy.charge': 'Заряд АКБ', 'energy.discharge': 'Разряд АКБ',
    'energy.forecast': 'Прогноз PV на сегодня',
    'energy.period': 'Период:', 'energy.day': 'Сутки', 'energy.7d': '7 дней',
    'energy.30d': '30 дней', 'energy.refresh': 'Обновить', 'energy.by_source': 'Энергия по источникам',

    'state.mode': 'Режим', 'state.battery': 'АКБ', 'state.soc': 'State of charge',
    'state.batt_power': 'Мощность АКБ', 'state.temp': 'Температура',
    'state.warnings': 'Предупреждения', 'state.none': 'нет',

    'inv.cur': 'Текущие показатели', 'inv.passport': 'Паспорт устройства',
    'grid.detail': 'Подробно',

    'bat.bms_inverter': 'BMS инвертора (CAN / RS485)',
    'bat.protocol': 'Протокол BMS инвертора:', 'bat.save': 'Сохранить',
    'bat.confirm_now': 'Подтвердить сейчас', 'bat.revert': 'Вернуть прежний',
    'bat.history': 'История кодов BMS (60 / 62 / 69 / 70 / 71)',
    'bat.time': 'Время', 'bat.code': 'Код', 'bat.value': 'Значение', 'bat.duration': 'Длительность',
    'bat.no_events': 'Событий пока нет — это хорошо',
    'bat.monitor': 'Мониторинг АКБ', 'bat.pick_source': 'Выбрать источник АКБ',
    'bat.source': 'Источник (как в SolarAssistant)', 'bat.port': 'Порт',
    'bat.speed': 'Скорость', 'bat.unit': 'Modbus unit id', 'bat.capacity': 'Ёмкость, А·ч',
    'bat.can': 'CAN интерфейс', 'bat.connect': 'Подключить',
    'bat.inverter_values': 'Значения инвертора', 'bat.battery': 'Батарея',
    'bat.voltage_setpoints': 'Уставки напряжений', 'bat.current_protocol': 'Текущий протокол:',
    'bat.now': 'сейчас:', 'bat.no_data': 'BMS не отдаёт данные',
    'bat.inverter_bms': 'BMS инвертора', 'bat.link': 'BMS',
    'bat.checking': 'Проверяю связь с АКБ по протоколу «{proto}» (обычно 20–30 с): осталось {left} с',
    'bat.confirmed': '✓ протокол «{proto}» подтверждён, BMS на связи',
    'bat.rolled_back': '↩️ протокол возвращён на «{prev}» ({why})',
    'bat.why_timeout': 'нет связи с АКБ', 'bat.why_manual': 'вручную',
    'bat.import_notice': 'Сейчас данные импортируются из <b>SolarAssistant</b> (sa-mqtt). Нажатие «Применить» переключит этот сайт на <b>прямое подключение</b> и перезапустит его коллектор. Важно: USB-порт инвертора занят SolarAssistant, а коллектор этого сайта работает на VDS (USB там нет) — поэтому «прямое» подключение возможно только по сети (TCP: ser2net на Orange Pi) либо после переноса коллектора на сам Orange Pi.',
    'bat.warn69': '⚠️ Код {code} на дисплее инвертора — BMS {what}',
    'bat.link_down': '🔌 Связи с BMS нет — на дисплее может быть код 62.',

    'ch.period': 'Период:', 'ch.hint': 'Выделите область на графике — остальные перейдут на тот же период',
    'ch.1h': '1ч', 'ch.6h': '6ч', 'ch.24h': '24ч', 'ch.7d': '7д', 'ch.30d': '30д',
    'ch.no_data': 'Нет данных за выбранный период', 'ch.no_data_period': 'нет данных за период',
    'ch.overview': 'Обзор', 'ch.pv_power': 'PV мощность', 'ch.load_power': 'Нагрузка',
    'ch.grid_power': 'Сеть: мощность', 'ch.batt_power': 'АКБ: мощность (+заряд / −разряд)',
    'ch.soc': 'АКБ: заряд (SOC)', 'ch.batt_voltage': 'АКБ: напряжение', 'ch.batt_current': 'АКБ: ток',
    'ch.pv_voltage': 'PV: напряжение по MPPT', 'ch.pv_current': 'PV: ток по MPPT',
    'ch.grid_voltage': 'Сеть: напряжение', 'ch.grid_freq': 'Сеть: частота',
    'ch.temp': 'Температура инвертора', 'ch.ac_out': 'Выходное напряжение',
    'ch.bus': 'Bus voltage', 'ch.forecast': 'прогноз PV', 'ch.total': 'сумма',

    'auto.test': 'Тест уведомлений', 'auto.rules': 'Правила', 'auto.new_rule': 'Новое правило',
    'auto.name': 'Название', 'auto.metric': 'Метрика', 'auto.condition': 'Условие',
    'auto.value': 'Значение', 'auto.hold': 'Держать, с', 'auto.cooldown': 'Не чаще, с',
    'auto.action': 'Действие', 'auto.text': 'Текст', 'auto.setting': 'Настройка',
    'auto.setting_value': 'Значение настройки', 'auto.topic': 'Топик', 'auto.payload': 'Payload',
    'auto.add': 'Добавить правило', 'auto.example': 'Вставить пример',
    'auto.notify': 'уведомить', 'auto.set': 'записать настройку', 'auto.mqtt': 'опубликовать в MQTT',
    'auto.off': 'выкл', 'auto.on': 'вкл', 'auto.delete': 'удалить', 'auto.empty': 'Правил пока нет — добавь первое ниже.',
    'auto.channels': 'каналы: {list} · не чаще {sec} с',
    'auto.no_channels': 'каналы уведомлений не настроены (TELEGRAM_BOT_TOKEN / WEBHOOK_URL)',

    'conn.current': 'Текущее подключение', 'conn.setup': 'Настройка подключения к инвертору',
    'conn.transport': 'Транспорт', 'conn.source': 'Источник', 'conn.link': 'Связь',
    'conn.exchange': 'Обмен', 'conn.method': 'Способ подключения', 'conn.host': 'Хост',
    'conn.port': 'Порт', 'conn.adapter_port': 'Порт адаптера', 'conn.speed': 'Скорость',
    'conn.topic': 'Топик EW10', 'conn.apply': 'Применить', 'conn.probe': 'Проверить связь',
    'conn.direct': 'инвертор напрямую', 'conn.import': 'импорт из SolarAssistant',
    'conn.yes': 'есть', 'conn.no': 'нет', 'conn.checking': 'проверяю…', 'conn.applying': 'применяю…',
    'conn.mode.tcp': 'Виртуальный RS232 (TCP)', 'conn.mode.serial': 'Физический USB-RS232 / RS485',
    'conn.mode.hid': 'USB-HID (нативный USB инвертора)', 'conn.mode.mqtt': 'MQTT-сокет (EW10 в режиме MQTT)',
    'conn.hint.tcp': 'Донгл EW10 :9999, ser2net, ESP32-шлюз, usbip',
    'conn.hint.serial': 'USB-адаптер в инвертор (обычно 2400 8N1)',
    'conn.hint.hid': 'Порт инвертора напрямую, без переходников',
    'conn.hint.mqtt': 'Кадры уходят в <topic>/cmd, ответы приходят в <topic>/data',
    'conn.ok': '✓ {target}: АКБ {batt} В, сеть {grid} В, нагрузка {load} Вт{sn} · {ms} мс',
    'conn.err': '✗ {error}', 'conn.restarting': '✓ источник: прямое подключение — перезапускаю коллектор…',
    'conn.restarted': '✓ коллектор поднялся, подключение применено',
    'conn.restart_wait': 'перезапуск… ({n})', 'conn.restart_fail': '✗ коллектор не отвечает после перезапуска',
    'conn.switched': '✓ подключено: {transport}',

    'codes.filter': 'Фильтр: номер или текст (например 69, BMS, Fan)',
    'codes.count': '{n} кодов', 'codes.no_match': 'нет совпадений',
    'codes.event': 'Событие', 'codes.what': 'Что делать', 'codes.action': 'Действие',
    'codes.bms': 'Коды BMS (60 / 62 / 69 / 70 / 71)',
    'codes.faults': 'Ошибки инвертора (постоянный красный LED)',
    'codes.warnings': 'Предупреждения (мигающий LED, звук)',
    'codes.parallel': 'Параллельная система', 'codes.normal': 'норма',

    'set.reload': 'Перечитать из инвертора', 'set.save': 'Сохранить', 'set.now': 'сейчас:',
    'set.writing': 'запись…', 'set.reading': 'читаю…',
    'auth.title': 'Доступ к интерфейсу', 'auth.current': 'Текущий пароль',
    'auth.new': 'Новый пароль', 'auth.repeat': 'Повторите пароль',
    'auth.save': 'Сменить пароль', 'auth.user': 'пользователь',
    'auth.src_env': 'пароль из .env', 'auth.src_file': 'пароль изменён в интерфейсе',
    'auth.src_off': 'авторизация выключена', 'auth.disabled': 'Авторизация выключена (задайте AUTH_USER/AUTH_PASSWORD в .env)',
    'auth.unavailable': 'не удалось получить данные авторизации',
    'auth.mismatch': 'пароли не совпадают', 'auth.too_short': 'пароль короче 6 символов',
    'auth.note': 'Пароль хранится как PBKDF2-хэш в /data/auth.json и перекрывает .env. Grafana (порт 3443) имеет свой пароль — он не меняется.',
    'site.select': 'Сайт', 'job.done': 'готово',
    'unit.W': 'Вт', 'unit.kW': 'кВт', 'unit.kWh': 'кВт·ч', 'unit.V': 'В', 'unit.A': 'А',
    'unit.pct': '%', 'unit.C': '°C', 'unit.Hz': 'Гц', 'unit.VA': 'ВА', 'unit.min': 'мин',
  },

  en: {
    'nav.overview': 'Overview', 'nav.grid': 'Grid', 'nav.energy': 'Energy',
    'nav.charts': 'Charts', 'nav.settings': 'Settings',
    'sub.inverter': 'Inverter', 'sub.battery': 'Battery', 'sub.connection': 'Connection',
    'sub.automation': 'Automation', 'sub.codes': 'Codes', 'sub.setpoints': 'Settings',

    'ov.flow': 'Energy flow', 'ov.gauges': 'Power', 'ov.energy_today': 'Energy today',
    'ov.pv_arrays': 'PV arrays', 'ov.state': 'Status',
    'flow.pv': 'PV', 'flow.grid': 'Grid', 'flow.load': 'Load', 'flow.house': 'House',
    'flow.battery': 'Battery', 'flow.inverter': 'Inverter', 'flow.pv_dual': 'PV1 · PV2',
    'flow.pv_two_arrays': 'PV · 2 arrays',
    'inv.offgrid': 'off-grid', 'inv.hybrid': 'hybrid', 'inv.gridtie': 'grid-tie',
    'inv.parallel': 'parallel system',
    'batt.discharge': 'discharging', 'batt.charge': 'charging', 'batt.idle': 'idle',

    'energy.pv': 'PV produced', 'energy.load': 'Consumed', 'energy.grid': 'Grid import',
    'energy.charge': 'Battery charged', 'energy.discharge': 'Battery discharged',
    'energy.forecast': 'PV forecast today',
    'energy.period': 'Period:', 'energy.day': 'Day', 'energy.7d': '7 days',
    'energy.30d': '30 days', 'energy.refresh': 'Refresh', 'energy.by_source': 'Energy by source',

    'state.mode': 'Mode', 'state.battery': 'Battery', 'state.soc': 'State of charge',
    'state.batt_power': 'Battery power', 'state.temp': 'Temperature',
    'state.warnings': 'Warnings', 'state.none': 'none',

    'inv.cur': 'Current values', 'inv.passport': 'Device information',
    'grid.detail': 'Details',

    'bat.bms_inverter': 'Inverter BMS (CAN / RS485)',
    'bat.protocol': 'Inverter BMS protocol:', 'bat.save': 'Save',
    'bat.confirm_now': 'Confirm now', 'bat.revert': 'Revert',
    'bat.history': 'BMS code history (60 / 62 / 69 / 70 / 71)',
    'bat.time': 'Time', 'bat.code': 'Code', 'bat.value': 'Value', 'bat.duration': 'Duration',
    'bat.no_events': 'No events yet — good',
    'bat.monitor': 'Battery monitoring', 'bat.pick_source': 'Choose battery source',
    'bat.source': 'Source (as in SolarAssistant)', 'bat.port': 'Port',
    'bat.speed': 'Baud rate', 'bat.unit': 'Modbus unit id', 'bat.capacity': 'Capacity, Ah',
    'bat.can': 'CAN interface', 'bat.connect': 'Connect',
    'bat.inverter_values': 'Inverter values', 'bat.battery': 'Battery',
    'bat.voltage_setpoints': 'Voltage setpoints', 'bat.current_protocol': 'Current protocol:',
    'bat.now': 'now:', 'bat.no_data': 'BMS reports nothing',
    'bat.inverter_bms': 'Inverter BMS', 'bat.link': 'BMS',
    'bat.checking': 'Checking the battery link on «{proto}» (usually 20–30 s): {left} s left',
    'bat.confirmed': '✓ protocol «{proto}» confirmed, BMS online',
    'bat.rolled_back': '↩️ protocol reverted to «{prev}» ({why})',
    'bat.why_timeout': 'no battery link', 'bat.why_manual': 'manually',
    'bat.import_notice': 'Data is currently imported from <b>SolarAssistant</b> (sa-mqtt). “Apply” switches this site to a <b>direct connection</b> and restarts its collector. Note: the inverter USB port belongs to SolarAssistant and this site’s collector runs on a VDS (no USB) — so a direct connection is only possible over the network (TCP: ser2net on the Orange Pi) or after moving the collector onto the Orange Pi itself.',
    'bat.warn69': '⚠️ Code {code} on the inverter display — BMS {what}',
    'bat.link_down': '🔌 No BMS link — code 62 may be shown.',

    'ch.period': 'Period:', 'ch.hint': 'Drag a region on any chart — the others follow the same period',
    'ch.1h': '1h', 'ch.6h': '6h', 'ch.24h': '24h', 'ch.7d': '7d', 'ch.30d': '30d',
    'ch.no_data': 'No data for the selected period', 'ch.no_data_period': 'no data for the period',
    'ch.overview': 'Overview', 'ch.pv_power': 'PV power', 'ch.load_power': 'Load',
    'ch.grid_power': 'Grid: power', 'ch.batt_power': 'Battery: power (+charge / −discharge)',
    'ch.soc': 'Battery: state of charge', 'ch.batt_voltage': 'Battery: voltage',
    'ch.batt_current': 'Battery: current',
    'ch.pv_voltage': 'PV: voltage per MPPT', 'ch.pv_current': 'PV: current per MPPT',
    'ch.grid_voltage': 'Grid: voltage', 'ch.grid_freq': 'Grid: frequency',
    'ch.temp': 'Inverter temperature', 'ch.ac_out': 'AC output voltage',
    'ch.bus': 'Bus voltage', 'ch.forecast': 'PV forecast', 'ch.total': 'total',

    'auto.test': 'Test notification', 'auto.rules': 'Rules', 'auto.new_rule': 'New rule',
    'auto.name': 'Name', 'auto.metric': 'Metric', 'auto.condition': 'Condition',
    'auto.value': 'Value', 'auto.hold': 'Hold, s', 'auto.cooldown': 'Not more often, s',
    'auto.action': 'Action', 'auto.text': 'Text', 'auto.setting': 'Setting',
    'auto.setting_value': 'Setting value', 'auto.topic': 'Topic', 'auto.payload': 'Payload',
    'auto.add': 'Add rule', 'auto.example': 'Insert example',
    'auto.notify': 'notify', 'auto.set': 'set inverter setting', 'auto.mqtt': 'publish to MQTT',
    'auto.off': 'off', 'auto.on': 'on', 'auto.delete': 'delete', 'auto.empty': 'No rules yet — add the first one below.',
    'auto.channels': 'channels: {list} · at most every {sec} s',
    'auto.no_channels': 'no notification channels configured (TELEGRAM_BOT_TOKEN / WEBHOOK_URL)',

    'conn.current': 'Current connection', 'conn.setup': 'Inverter connection',
    'conn.transport': 'Transport', 'conn.source': 'Source', 'conn.link': 'Link',
    'conn.exchange': 'Traffic', 'conn.method': 'Connection type', 'conn.host': 'Host',
    'conn.port': 'Port', 'conn.adapter_port': 'Adapter port', 'conn.speed': 'Baud rate',
    'conn.topic': 'EW10 topic', 'conn.apply': 'Apply', 'conn.probe': 'Test connection',
    'conn.direct': 'inverter directly', 'conn.import': 'imported from SolarAssistant',
    'conn.yes': 'up', 'conn.no': 'down', 'conn.checking': 'testing…', 'conn.applying': 'applying…',
    'conn.mode.tcp': 'Virtual RS232 (TCP)', 'conn.mode.serial': 'Physical USB-RS232 / RS485',
    'conn.mode.hid': 'USB-HID (native inverter USB)', 'conn.mode.mqtt': 'MQTT socket (EW10 in MQTT mode)',
    'conn.hint.tcp': 'EW10 dongle :9999, ser2net, ESP32 gateway, usbip',
    'conn.hint.serial': 'USB adapter into the inverter (usually 2400 8N1)',
    'conn.hint.hid': 'Inverter port directly, no adapters',
    'conn.hint.mqtt': 'Frames go to <topic>/cmd, replies arrive on <topic>/data',
    'conn.ok': '✓ {target}: battery {batt} V, grid {grid} V, load {load} W{sn} · {ms} ms',
    'conn.err': '✗ {error}', 'conn.restarting': '✓ direct connection selected — restarting the collector…',
    'conn.restarted': '✓ collector is back, connection applied',
    'conn.restart_wait': 'restarting… ({n})', 'conn.restart_fail': '✗ collector does not answer after restart',
    'conn.switched': '✓ connected: {transport}',

    'codes.filter': 'Filter: number or text (e.g. 69, BMS, Fan)',
    'codes.count': '{n} codes', 'codes.no_match': 'no matches',
    'codes.event': 'Event', 'codes.what': 'What to do', 'codes.action': 'Action',
    'codes.bms': 'BMS codes (60 / 62 / 69 / 70 / 71)',
    'codes.faults': 'Inverter faults (steady red LED)',
    'codes.warnings': 'Warnings (flashing LED, buzzer)',
    'codes.parallel': 'Parallel system', 'codes.normal': 'normal',

    'set.reload': 'Re-read from inverter', 'set.save': 'Save', 'set.now': 'now:',
    'set.writing': 'writing…', 'set.reading': 'reading…',
    'auth.title': 'Interface access', 'auth.current': 'Current password',
    'auth.new': 'New password', 'auth.repeat': 'Repeat password',
    'auth.save': 'Change password', 'auth.user': 'user',
    'auth.src_env': 'password from .env', 'auth.src_file': 'password changed in the UI',
    'auth.src_off': 'auth disabled', 'auth.disabled': 'Auth is off (set AUTH_USER/AUTH_PASSWORD in .env)',
    'auth.unavailable': 'cannot read auth state',
    'auth.mismatch': 'passwords do not match', 'auth.too_short': 'password is shorter than 6 characters',
    'auth.note': 'The password is stored as a PBKDF2 hash in /data/auth.json and overrides .env. Grafana (port 3443) keeps its own password.',
    'site.select': 'Site', 'job.done': 'done',
    'unit.W': 'W', 'unit.kW': 'kW', 'unit.kWh': 'kWh', 'unit.V': 'V', 'unit.A': 'A',
    'unit.pct': '%', 'unit.C': '°C', 'unit.Hz': 'Hz', 'unit.VA': 'VA', 'unit.min': 'min',
  },

  el: {
    'nav.overview': 'Επισκόπηση', 'nav.grid': 'Δίκτυο', 'nav.energy': 'Ενέργεια',
    'nav.charts': 'Γραφήματα', 'nav.settings': 'Ρυθμίσεις',
    'sub.inverter': 'Μετατροπέας', 'sub.battery': 'Μπαταρία', 'sub.connection': 'Σύνδεση',
    'sub.automation': 'Αυτοματισμοί', 'sub.codes': 'Κωδικοί', 'sub.setpoints': 'Ρυθμίσεις',

    'ov.flow': 'Ροή ενέργειας', 'ov.gauges': 'Ισχύς', 'ov.energy_today': 'Ενέργεια σήμερα',
    'ov.pv_arrays': 'Συστοιχίες PV', 'ov.state': 'Κατάσταση',
    'flow.pv': 'PV', 'flow.grid': 'Δίκτυο', 'flow.load': 'Φορτίο', 'flow.house': 'Σπίτι',
    'flow.battery': 'Μπαταρία', 'flow.inverter': 'Μετατροπέας', 'flow.pv_dual': 'PV1 · PV2',
    'flow.pv_two_arrays': 'PV · 2 συστοιχίες',
    'inv.offgrid': 'off-grid', 'inv.hybrid': 'υβριδικός', 'inv.gridtie': 'grid-tie',
    'inv.parallel': 'παράλληλο σύστημα',
    'batt.discharge': 'εκφόρτιση', 'batt.charge': 'φόρτιση', 'batt.idle': 'αναμονή',

    'energy.pv': 'Παραγωγή PV', 'energy.load': 'Κατανάλωση', 'energy.grid': 'Εισαγωγή από δίκτυο',
    'energy.charge': 'Φόρτιση μπαταρίας', 'energy.discharge': 'Εκφόρτιση μπαταρίας',
    'energy.forecast': 'Πρόβλεψη PV σήμερα',
    'energy.period': 'Περίοδος:', 'energy.day': 'Ημέρα', 'energy.7d': '7 ημέρες',
    'energy.30d': '30 ημέρες', 'energy.refresh': 'Ανανέωση', 'energy.by_source': 'Ενέργεια ανά πηγή',

    'state.mode': 'Λειτουργία', 'state.battery': 'Μπαταρία', 'state.soc': 'Φόρτιση',
    'state.batt_power': 'Ισχύς μπαταρίας', 'state.temp': 'Θερμοκρασία',
    'state.warnings': 'Προειδοποιήσεις', 'state.none': 'καμία',

    'inv.cur': 'Τρέχουσες τιμές', 'inv.passport': 'Στοιχεία συσκευής',
    'grid.detail': 'Λεπτομέρειες',

    'bat.bms_inverter': 'BMS μετατροπέα (CAN / RS485)',
    'bat.protocol': 'Πρωτόκολλο BMS μετατροπέα:', 'bat.save': 'Αποθήκευση',
    'bat.confirm_now': 'Επιβεβαίωση τώρα', 'bat.revert': 'Επαναφορά',
    'bat.history': 'Ιστορικό κωδικών BMS (60 / 62 / 69 / 70 / 71)',
    'bat.time': 'Ώρα', 'bat.code': 'Κωδικός', 'bat.value': 'Τιμή', 'bat.duration': 'Διάρκεια',
    'bat.no_events': 'Κανένα συμβάν — καλό',
    'bat.monitor': 'Παρακολούθηση μπαταρίας', 'bat.pick_source': 'Επιλογή πηγής μπαταρίας',
    'bat.source': 'Πηγή (όπως στο SolarAssistant)', 'bat.port': 'Θύρα',
    'bat.speed': 'Baud rate', 'bat.unit': 'Modbus unit id', 'bat.capacity': 'Χωρητικότητα, Ah',
    'bat.can': 'Διεπαφή CAN', 'bat.connect': 'Σύνδεση',
    'bat.inverter_values': 'Τιμές μετατροπέα', 'bat.battery': 'Μπαταρία',
    'bat.voltage_setpoints': 'Τάσεις ρύθμισης', 'bat.current_protocol': 'Τρέχον πρωτόκολλο:',
    'bat.now': 'τώρα:', 'bat.no_data': 'Το BMS δεν δίνει δεδομένα',
    'bat.inverter_bms': 'BMS μετατροπέα', 'bat.link': 'BMS',
    'bat.checking': 'Έλεγχος σύνδεσης μπαταρίας στο «{proto}» (συνήθως 20–30 s): απομένουν {left} s',
    'bat.confirmed': '✓ πρωτόκολλο «{proto}» επιβεβαιώθηκε, BMS σε σύνδεση',
    'bat.rolled_back': '↩️ επαναφορά πρωτοκόλλου σε «{prev}» ({why})',
    'bat.why_timeout': 'χωρίς σύνδεση μπαταρίας', 'bat.why_manual': 'χειροκίνητα',
    'bat.import_notice': 'Τα δεδομένα εισάγονται από το <b>SolarAssistant</b> (sa-mqtt). Με «Εφαρμογή» ο ιστότοπος περνά σε <b>απευθείας σύνδεση</b> και ο collector επανεκκινεί. Σημείωση: η θύρα USB ανήκει στο SolarAssistant και ο collector τρέχει σε VDS (χωρίς USB) — άρα απευθείας σύνδεση μόνο μέσω δικτύου (TCP: ser2net στο Orange Pi).',
    'bat.warn69': '⚠️ Κωδικός {code} στην οθόνη — BMS {what}',
    'bat.link_down': '🔌 Χωρίς σύνδεση BMS — πιθανός κωδικός 62.',

    'ch.period': 'Περίοδος:', 'ch.hint': 'Επιλέξτε περιοχή σε ένα γράφημα — τα υπόλοιπα ακολουθούν',
    'ch.1h': '1ω', 'ch.6h': '6ω', 'ch.24h': '24ω', 'ch.7d': '7ημ', 'ch.30d': '30ημ',
    'ch.no_data': 'Δεν υπάρχουν δεδομένα για την περίοδο', 'ch.no_data_period': 'χωρίς δεδομένα',
    'ch.overview': 'Επισκόπηση', 'ch.pv_power': 'Ισχύς PV', 'ch.load_power': 'Φορτίο',
    'ch.grid_power': 'Δίκτυο: ισχύς', 'ch.batt_power': 'Μπαταρία: ισχύς (+φόρτιση / −εκφόρτιση)',
    'ch.soc': 'Μπαταρία: φόρτιση (SOC)', 'ch.batt_voltage': 'Μπαταρία: τάση',
    'ch.batt_current': 'Μπαταρία: ρεύμα',
    'ch.pv_voltage': 'PV: τάση ανά MPPT', 'ch.pv_current': 'PV: ρεύμα ανά MPPT',
    'ch.grid_voltage': 'Δίκτυο: τάση', 'ch.grid_freq': 'Δίκτυο: συχνότητα',
    'ch.temp': 'Θερμοκρασία μετατροπέα', 'ch.ac_out': 'Τάση εξόδου',
    'ch.bus': 'Bus voltage', 'ch.forecast': 'πρόβλεψη PV', 'ch.total': 'σύνολο',

    'auto.test': 'Δοκιμή ειδοποίησης', 'auto.rules': 'Κανόνες', 'auto.new_rule': 'Νέος κανόνας',
    'auto.name': 'Όνομα', 'auto.metric': 'Μέτρηση', 'auto.condition': 'Συνθήκη',
    'auto.value': 'Τιμή', 'auto.hold': 'Διάρκεια, s', 'auto.cooldown': 'Όχι συχνότερα, s',
    'auto.action': 'Ενέργεια', 'auto.text': 'Κείμενο', 'auto.setting': 'Ρύθμιση',
    'auto.setting_value': 'Τιμή ρύθμισης', 'auto.topic': 'Topic', 'auto.payload': 'Payload',
    'auto.add': 'Προσθήκη κανόνα', 'auto.example': 'Εισαγωγή παραδείγματος',
    'auto.notify': 'ειδοποίηση', 'auto.set': 'αλλαγή ρύθμισης', 'auto.mqtt': 'δημοσίευση σε MQTT',
    'auto.off': 'off', 'auto.on': 'on', 'auto.delete': 'διαγραφή', 'auto.empty': 'Κανένας κανόνας — προσθέστε τον πρώτο.',
    'auto.channels': 'κανάλια: {list} · έως κάθε {sec} s',
    'auto.no_channels': 'δεν έχουν ρυθμιστεί κανάλια (TELEGRAM_BOT_TOKEN / WEBHOOK_URL)',

    'conn.current': 'Τρέχουσα σύνδεση', 'conn.setup': 'Σύνδεση μετατροπέα',
    'conn.transport': 'Μεταφορά', 'conn.source': 'Πηγή', 'conn.link': 'Σύνδεση',
    'conn.exchange': 'Κίνηση', 'conn.method': 'Τύπος σύνδεσης', 'conn.host': 'Host',
    'conn.port': 'Θύρα', 'conn.adapter_port': 'Θύρα adapter', 'conn.speed': 'Baud rate',
    'conn.topic': 'Topic EW10', 'conn.apply': 'Εφαρμογή', 'conn.probe': 'Δοκιμή σύνδεσης',
    'conn.direct': 'απευθείας από μετατροπέα', 'conn.import': 'εισαγωγή από SolarAssistant',
    'conn.yes': 'ναι', 'conn.no': 'όχι', 'conn.checking': 'έλεγχος…', 'conn.applying': 'εφαρμογή…',
    'conn.mode.tcp': 'Εικονικό RS232 (TCP)', 'conn.mode.serial': 'Φυσικό USB-RS232 / RS485',
    'conn.mode.hid': 'USB-HID (εγγενής θύρα USB)', 'conn.mode.mqtt': 'MQTT socket (EW10 σε λειτουργία MQTT)',
    'conn.hint.tcp': 'Dongle EW10 :9999, ser2net, πύλη ESP32, usbip',
    'conn.hint.serial': 'USB adapter στον μετατροπέα (συνήθως 2400 8N1)',
    'conn.hint.hid': 'Θύρα μετατροπέα απευθείας',
    'conn.hint.mqtt': 'Τα frames πάνε στο <topic>/cmd, οι απαντήσεις στο <topic>/data',
    'conn.ok': '✓ {target}: μπαταρία {batt} V, δίκτυο {grid} V, φορτίο {load} W{sn} · {ms} ms',
    'conn.err': '✗ {error}', 'conn.restarting': '✓ απευθείας σύνδεση — επανεκκίνηση collector…',
    'conn.restarted': '✓ ο collector επέστρεψε, η σύνδεση εφαρμόστηκε',
    'conn.restart_wait': 'επανεκκίνηση… ({n})', 'conn.restart_fail': '✗ ο collector δεν απαντά',
    'conn.switched': '✓ συνδέθηκε: {transport}',

    'codes.filter': 'Φίλτρο: αριθμός ή κείμενο (π.χ. 69, BMS, Fan)',
    'codes.count': '{n} κωδικοί', 'codes.no_match': 'καμία αντιστοιχία',
    'codes.event': 'Συμβάν', 'codes.what': 'Τι να κάνετε', 'codes.action': 'Ενέργεια',
    'codes.bms': 'Κωδικοί BMS (60 / 62 / 69 / 70 / 71)',
    'codes.faults': 'Σφάλματα μετατροπέα (σταθερό κόκκινο LED)',
    'codes.warnings': 'Προειδοποιήσεις (αναβοσβήνει, buzzer)',
    'codes.parallel': 'Παράλληλο σύστημα', 'codes.normal': 'κανονικό',

    'set.reload': 'Επανάγνωση από μετατροπέα', 'set.save': 'Αποθήκευση', 'set.now': 'τώρα:',
    'set.writing': 'εγγραφή…', 'set.reading': 'ανάγνωση…',
    'auth.title': 'Πρόσβαση διεπαφής', 'auth.current': 'Τρέχων κωδικός',
    'auth.new': 'Νέος κωδικός', 'auth.repeat': 'Επανάληψη κωδικού',
    'auth.save': 'Αλλαγή κωδικού', 'auth.user': 'χρήστης',
    'auth.src_env': 'κωδικός από .env', 'auth.src_file': 'ο κωδικός άλλαξε από το UI',
    'auth.src_off': 'η πιστοποίηση είναι ανενεργή', 'auth.disabled': 'Η πιστοποίηση είναι ανενεργή (AUTH_USER/AUTH_PASSWORD στο .env)',
    'auth.unavailable': 'δεν διαβάζεται η κατάσταση πιστοποίησης',
    'auth.mismatch': 'οι κωδικοί δεν ταιριάζουν', 'auth.too_short': 'ο κωδικός είναι κάτω από 6 χαρακτήρες',
    'auth.note': 'Ο κωδικός αποθηκεύεται ως PBKDF2 hash στο /data/auth.json και υπερισχύει του .env. Το Grafana (θύρα 3443) έχει δικό του κωδικό.',
    'site.select': 'Τοποθεσία', 'job.done': 'έτοιμο',
    'unit.W': 'W', 'unit.kW': 'kW', 'unit.kWh': 'kWh', 'unit.V': 'V', 'unit.A': 'A',
    'unit.pct': '%', 'unit.C': '°C', 'unit.Hz': 'Hz', 'unit.VA': 'VA', 'unit.min': 'min',
  },
};

let LANG = (new URLSearchParams(location.search).get('lang')
  || localStorage.getItem('solar.lang')
  || (navigator.language || 'en').slice(0, 2)).toLowerCase();
if (!I18N[LANG]) LANG = I18N[LANG === 'gr' ? 'el' : LANG] ? LANG : 'en';

function t(key, vars) {
  const table = I18N[LANG] || I18N.en;
  let s = table[key];
  if (s === undefined) s = I18N.en[key];
  if (s === undefined) s = key;
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? vars[k] : ''));
}

function setLang(lang) {
  if (!I18N[lang]) lang = 'en';
  LANG = lang;
  localStorage.setItem('solar.lang', lang);
  document.documentElement.lang = lang;
  applyI18n();
  if (typeof onLanguageChanged === 'function') onLanguageChanged();
}

// Обратная карта «русский текст -> ключ»: позволяет переводить статическую разметку,
// не расставляя data-i18n в каждом теге (в меню текст соседствует с <svg>).
const RU_MAP = (() => {
  const map = {};
  Object.keys(I18N.ru).forEach((k) => {
    const v = I18N.ru[k];
    if (v && !v.includes('{') && !v.includes('<')) map[v] = k;
  });
  return map;
})();

function translateTextNodes(scope) {
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      const tag = parent.tagName.toLowerCase();
      if (['script', 'style', 'option'].includes(tag)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    const raw = node.textContent.trim();
    if (!raw) return;
    const key = node.__i18nKey || RU_MAP[raw];
    if (!key) return;
    node.__i18nKey = key;
    const value = t(key);
    node.textContent = node.textContent.replace(raw, value);
  });
}

function applyI18n(root) {
  translateTextNodes(root || document.body);
  const scope = root || document;
  scope.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  scope.querySelectorAll('[data-i18n-html]').forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  scope.querySelectorAll('[data-i18n-title]').forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  scope.querySelectorAll('[data-i18n-ph]').forEach((el) => {
    el.placeholder = t(el.dataset.i18nPh);
  });
  document.documentElement.lang = LANG;
}
