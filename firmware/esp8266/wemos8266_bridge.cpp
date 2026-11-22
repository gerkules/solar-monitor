#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPUpdateServer.h>
#include <EEPROM.h>
#include <SoftwareSerial.h>

#define FW_VERSION "123_esp8266_rs232_bridge"
#define CONFIG_MAGIC 8266060UL
#define CONFIG_MAGIC_OLD 8266054UL
#define DEFAULT_BRIDGE_PORT 9999
#define DEFAULT_BAUD 2400
#define EEPROM_SIZE 256
#define WIFI_TIMEOUT_MS 18000UL
#define POLL_INTERVAL_MS 2000UL
#define FAST_POLL_INTERVAL_MS 800UL
#define STARTUP_FAST_MS 45000UL
#define OFFLINE_MS 15000UL
#define WRITE_TIMEOUT_MS 5000UL

// Wemos D1 mini ESP8266: D5=GPIO14 reads inverter TX, D6=GPIO12 writes inverter RX.
#define INV_RX_PIN D5
#define INV_TX_PIN D6
#define LED_PIN LED_BUILTIN

const char* AP_SSID = "InverterMonitor";
const char* AP_PASS = "12345678";

struct LiteConfig {
  uint32_t magic = CONFIG_MAGIC;
  char ssid[32] = "";
  char pass[32] = "";
  char adminPass[16] = "admin";
  uint16_t bridgePort = DEFAULT_BRIDGE_PORT;
  uint16_t baud = DEFAULT_BAUD;
} conf;

struct InverterData {
  float gridVolts = 0;
  float gridFreq = 0;
  float outVolts = 0;
  float outFreq = 0;
  int outVA = 0;
  int outWatts = 0;
  int loadPercent = 0;
  float battVolts = 0;
  int battChargeCurrent = 0;
  int battDischargeCurrent = 0;
  int battCapacity = 0;
  int temp = 0;
  float pvCurrent = 0;
  float pvVolts = 0;
  int pvWatts = 0;
  String mode = "-";
  bool updated = false;
} inv;

ESP8266WebServer server(80);
ESP8266HTTPUpdateServer httpUpdater;
WiFiServer bridgeServer(DEFAULT_BRIDGE_PORT);
WiFiClient bridgeClient;
String brClientIp = "-";
uint32_t brTcpToUart = 0;
uint32_t brUartToTcp = 0;
uint32_t brSessions = 0;
unsigned long brLastMs = 0;

bool bridgeActive();
SoftwareSerial invSerial(INV_RX_PIN, INV_TX_PIN);

bool apMode = false;
bool nextModePoll = false;
unsigned long bootMs = 0;
unsigned long lastPoll = 0;
unsigned long lastSeen = 0;
uint32_t packetsOk = 0;
uint32_t parseFail = 0;
String lastRaw = "Нет данных";
String lastCommand = "-";
String pendingWriteCommand = "";
String pendingWriteName = "";
String settingStatus = "No command";
unsigned long pendingWriteStarted = 0;
unsigned long pollPausedUntil = 0;

uint16_t axpertCrc(const uint8_t* data, size_t len) {
  uint16_t crc = 0;
  for (size_t i = 0; i < len; i++) {
    crc ^= (uint16_t)data[i] << 8;
    for (uint8_t b = 0; b < 8; b++) {
      crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
    }
  }
  return crc;
}

void sendCommand(const char* cmd) {
  uint16_t crc = axpertCrc((const uint8_t*)cmd, strlen(cmd));
  invSerial.write((const uint8_t*)cmd, strlen(cmd));
  invSerial.write((uint8_t)(crc >> 8));
  invSerial.write((uint8_t)(crc & 0xff));
  invSerial.write('\r');
  lastCommand = cmd;
}

bool writeBusy() {
  return pendingWriteCommand.length() > 0;
}

void sendWriteCommand(const String& cmd, const String& name) {
  pendingWriteCommand = cmd;
  pendingWriteName = name;
  pendingWriteStarted = millis();
  pollPausedUntil = millis() + 2500;
  settingStatus = "Sending: " + name;
  sendCommand(cmd.c_str());
}

String htmlEscape(const String& s) {
  String out;
  out.reserve(s.length() + 8);
  for (uint16_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '&') out += "&amp;";
    else if (c == '<') out += "&lt;";
    else if (c == '>') out += "&gt;";
    else if (c == '"') out += "&quot;";
    else out += c;
  }
  return out;
}

String jsonEscape(const String& s) {
  String out;
  out.reserve(s.length() + 8);
  for (uint16_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '"' || c == '\\') {
      out += '\\';
      out += c;
    } else if (c >= 32) {
      out += c;
    }
  }
  return out;
}

bool hasWiFi() {
  return conf.ssid[0] != 0;
}

void loadConfig() {
  EEPROM.begin(EEPROM_SIZE);
  EEPROM.get(0, conf);
  if (conf.magic != CONFIG_MAGIC) {
    LiteConfig fresh;
    if (conf.magic == CONFIG_MAGIC_OLD) {
      // миграция с FW 118: переносим Wi-Fi и пароль админа, порт/скорость — по умолчанию
      strncpy(fresh.ssid, conf.ssid, sizeof(fresh.ssid) - 1);
      strncpy(fresh.pass, conf.pass, sizeof(fresh.pass) - 1);
      strncpy(fresh.adminPass, conf.adminPass, sizeof(fresh.adminPass) - 1);
    }
    conf = fresh;
    EEPROM.put(0, conf);
    EEPROM.commit();
  }
  if (conf.bridgePort < 1024) conf.bridgePort = DEFAULT_BRIDGE_PORT;
  if (conf.baud < 1200 || conf.baud > 19200) conf.baud = DEFAULT_BAUD;
}

void saveConfig(const String& ssid, const String& pass, const String& admin) {
  uint16_t keepPort = conf.bridgePort;
  uint16_t keepBaud = conf.baud;
  memset(&conf, 0, sizeof(conf));
  conf.magic = CONFIG_MAGIC;
  conf.bridgePort = keepPort;
  conf.baud = keepBaud;
  ssid.substring(0, sizeof(conf.ssid) - 1).toCharArray(conf.ssid, sizeof(conf.ssid));
  pass.substring(0, sizeof(conf.pass) - 1).toCharArray(conf.pass, sizeof(conf.pass));
  admin.substring(0, sizeof(conf.adminPass) - 1).toCharArray(conf.adminPass, sizeof(conf.adminPass));
  if (conf.adminPass[0] == 0) strncpy(conf.adminPass, "admin", sizeof(conf.adminPass) - 1);
  EEPROM.put(0, conf);
  EEPROM.commit();
}

bool isAdmin() {
  if (!server.authenticate("admin", conf.adminPass)) {
    server.requestAuthentication();
    return false;
  }
  return true;
}

int battWatts() {
  return (int)(inv.battVolts * (inv.battChargeCurrent - inv.battDischargeCurrent));
}

int gridWatts() {
  int bw = battWatts();
  int chargeFromGrid = bw > inv.pvWatts ? bw - inv.pvWatts : 0;
  if (inv.gridVolts > 180 && inv.gridFreq > 40) return inv.outWatts + chargeFromGrid;
  return 0;
}

void parseQPIGS(String r) {
  r.replace("\n", "");
  r.replace("\r", "");
  lastRaw = r;
  int start = r.indexOf('(');
  if (start >= 0) r = r.substring(start + 1);

  float gv, gf, ov, of, busv, bv, pvToBattCurrent, pvv, bvscc;
  int va, w, lp, bcc, cap, temp, bdc, pvW = 0;
  int n = sscanf(r.c_str(), "%f %f %f %f %d %d %d %f %f %d %d %d %f %f %f %d",
                 &gv, &gf, &ov, &of, &va, &w, &lp, &busv, &bv, &bcc, &cap, &temp,
                 &pvToBattCurrent, &pvv, &bvscc, &bdc);
  if (n >= 12) {
    inv.gridVolts = gv;
    inv.gridFreq = gf;
    inv.outVolts = ov;
    inv.outFreq = of;
    inv.outVA = va;
    inv.outWatts = w;
    inv.loadPercent = lp;
    inv.battVolts = bv;
    inv.battChargeCurrent = bcc;
    inv.battCapacity = cap;
    inv.temp = temp;
    if (n >= 14) {
      inv.pvCurrent = pvToBattCurrent;
      inv.pvVolts = pvv;
      inv.pvWatts = (int)(inv.pvCurrent * inv.battVolts);
    }
    if (n >= 16) inv.battDischargeCurrent = bdc;
    if (sscanf(r.c_str(), "%*s %*s %*s %*s %*d %*d %*d %*s %*s %*d %*d %*d %*s %*s %*s %*d %*d %*d %*d %d", &pvW) == 1) {
      inv.pvWatts = pvW;
    }
    inv.updated = true;
    lastSeen = millis();
    packetsOk++;
  } else {
    parseFail++;
  }
}

void parseQMOD(String r) {
  int start = r.indexOf('(');
  if (start >= 0 && r.length() > start + 1) {
    char m = r[start + 1];
    if (m == 'L') inv.mode = "Line";
    else if (m == 'B') inv.mode = "Battery";
    else if (m == 'S') inv.mode = "Standby";
    else if (m == 'F') inv.mode = "Fault";
    else if (m == 'P') inv.mode = "Power on";
    else inv.mode = "Unknown";
  }
}

void handleFrame(String r) {
  r.replace("\n", "");
  r.replace("\r", "");
  lastRaw = r;
  if (r.indexOf('(') < 0) {
    parseFail++;
    return;
  }
  if (writeBusy()) {
    bool ack = r.indexOf("ACK") >= 0;
    settingStatus = String(ack ? "Accepted: " : "Rejected: ") + pendingWriteName;
    pendingWriteCommand = "";
    pendingWriteName = "";
    pollPausedUntil = millis() + 2500;
    return;
  }
  if (lastCommand == "QMOD") parseQMOD(r);
  else parseQPIGS(r);
}

String threeDigits(int v) {
  if (v < 0) v = 0;
  if (v > 999) v = 999;
  if (v < 10) return "00" + String(v);
  if (v < 100) return "0" + String(v);
  return String(v);
}

bool ampAllowed(int amps, bool grid) {
  const int gridVals[] = {2, 10, 20, 30, 40, 50, 60};
  const int chargeVals[] = {10, 20, 30, 40, 50, 60};
  const int* vals = grid ? gridVals : chargeVals;
  uint8_t count = grid ? 7 : 6;
  for (uint8_t i = 0; i < count; i++) {
    if (amps == vals[i]) return true;
  }
  return false;
}

void handleSet() {
  if (!isAdmin()) return;
  if (writeBusy()) {
    server.send(409, "text/plain", "Busy: " + pendingWriteName);
    return;
  }

  String key = server.arg("key");
  String val = server.arg("value");
  if (key == "output") {
    if (val == "usb") sendWriteCommand("POP00", "Output USB");
    else if (val == "sub") sendWriteCommand("POP01", "Output SUB");
    else if (val == "sbu") sendWriteCommand("POP02", "Output SBU");
    else {
      server.send(400, "text/plain", "Bad output value");
      return;
    }
  } else if (key == "charger") {
    if (val == "utility") sendWriteCommand("PCP00", "Charger utility only");
    else if (val == "solar_first") sendWriteCommand("PCP01", "Charger solar first");
    else if (val == "both") sendWriteCommand("PCP02", "Charger solar + utility");
    else if (val == "solar_only") sendWriteCommand("PCP03", "Charger solar only");
    else {
      server.send(400, "text/plain", "Bad charger value");
      return;
    }
  } else if (key == "battery_type") {
    if (val == "agm") sendWriteCommand("PBT00", "Battery type AGM");
    else if (val == "flooded") sendWriteCommand("PBT01", "Battery type Flooded");
    else if (val == "user") sendWriteCommand("PBT02", "Battery type User");
    else {
      server.send(400, "text/plain", "Bad battery type");
      return;
    }
  } else if (key == "max_grid_charge") {
    int amps = val.toInt();
    if (!ampAllowed(amps, true)) {
      server.send(400, "text/plain", "Bad grid charge amps");
      return;
    }
    sendWriteCommand("MUCHGC" + threeDigits(amps), "Max grid charge " + String(amps) + "A");
  } else if (key == "max_charge") {
    int amps = val.toInt();
    if (!ampAllowed(amps, false)) {
      server.send(400, "text/plain", "Bad max charge amps");
      return;
    }
    sendWriteCommand("MCHGC" + threeDigits(amps), "Max charge " + String(amps) + "A");
  } else {
    server.send(400, "text/plain", "Unknown setting");
    return;
  }

  server.send(200, "text/plain", settingStatus);
}

void handleData() {
  if (!isAdmin()) return;
  bool online = inv.updated && (millis() - lastSeen < OFFLINE_MS);
  String j = "{";
  j += "\"fw\":\"" FW_VERSION "\",";
  j += "\"online\":\"" + String(online ? "Да" : "Нет") + "\",";
  j += "\"mode\":\"" + jsonEscape(inv.mode) + "\",";
  j += "\"load_w\":" + String(inv.outWatts) + ",";
  j += "\"load_pct\":" + String(inv.loadPercent) + ",";
  j += "\"pv_w\":" + String(inv.pvWatts) + ",";
  j += "\"pv_v\":" + String(inv.pvVolts, 1) + ",";
  j += "\"pv_a\":" + String(inv.pvCurrent, 1) + ",";
  j += "\"bat_w\":" + String(battWatts()) + ",";
  j += "\"bat_a\":" + String(inv.battChargeCurrent - inv.battDischargeCurrent) + ",";
  j += "\"bat_v\":" + String(inv.battVolts, 1) + ",";
  j += "\"bat_pct\":" + String(inv.battCapacity) + ",";
  j += "\"grid_w\":" + String(gridWatts()) + ",";
  j += "\"grid_v\":" + String(inv.gridVolts, 1) + ",";
  j += "\"grid_hz\":" + String(inv.gridFreq, 1) + ",";
  j += "\"temp\":" + String(inv.temp) + ",";
  j += "\"last_age\":" + String(lastSeen ? (millis() - lastSeen) / 1000 : 0) + ",";
  j += "\"ok\":" + String(packetsOk) + ",";
  j += "\"fail\":" + String(parseFail) + ",";
  j += "\"setting\":\"" + jsonEscape(settingStatus) + "\",";
  j += "\"busy\":\"" + String(writeBusy() ? "Да" : "Нет") + "\",";
  j += "\"cmd\":\"" + jsonEscape(lastCommand) + "\",";
  j += "\"br_client\":\"" + jsonEscape(brClientIp) + "\",";
  j += "\"br_active\":" + String(bridgeActive() ? "true" : "false") + ",";
  j += "\"br_tcp2uart\":" + String(brTcpToUart) + ",";
  j += "\"br_uart2tcp\":" + String(brUartToTcp) + ",";
  j += "\"br_sessions\":" + String(brSessions) + ",";
  j += "\"br_age\":" + String(brLastMs ? (millis() - brLastMs) / 1000 : 0) + ",";
  j += "\"br_port\":" + String(conf.bridgePort) + ",";
  j += "\"baud\":" + String(conf.baud) + ",";
  j += "\"raw\":\"" + jsonEscape(lastRaw) + "\"}";
  server.send(200, "application/json", j);
}

void handleRoot() {
  if (!isAdmin()) return;
  String h;
  h.reserve(10500);
  h += "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>";
  h += "<title>ESP8266 Solar Lite</title><style>";
  h += ":root{--bg:#eef2f7;--card:#fff;--ink:#1f2a37;--muted:#64748b;--line:#e2e8f0;--accent:#2563eb;--warn:#f59e0b;--good:#16a34a;--bad:#dc2626;--radius:14px}";
  h += "@media(prefers-color-scheme:dark){:root{--bg:#0b1220;--card:#141d2e;--ink:#e7ecf5;--muted:#8b96a8;--line:#233046}}";
  h += "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif}";
  h += ".top{background:linear-gradient(135deg,#0f2f4c,#1d6fa5);color:#fff;padding:20px 5vw 0;box-shadow:0 2px 12px rgba(0,0,0,.18)}";
  h += ".brand{font-size:22px;font-weight:800;letter-spacing:.2px}.brand .fw{display:block;font-size:12px;font-weight:400;opacity:.75;margin-top:2px}";
  h += ".tabs{display:flex;gap:6px;margin-top:16px}.tab{border:0;background:rgba(255,255,255,.14);color:#fff;padding:12px 20px;border-radius:10px 10px 0 0;font-weight:700;cursor:pointer}";
  h += ".tab.active{background:var(--bg);color:var(--ink)}.page{display:none;padding:22px 5vw 40px;max-width:1100px;margin:0 auto}.page.active{display:block}";
  h += ".grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}";
  h += ".card{background:var(--card);border-radius:var(--radius);padding:18px;box-shadow:0 1px 3px rgba(15,23,42,.08),0 1px 2px rgba(15,23,42,.05);margin-bottom:12px}";
  h += ".card b{display:block;font-size:26px;margin:6px 0;font-weight:800}";
  h += ".muted{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.4px;font-weight:700}";
  h += ".ok{color:var(--good)}.bad{color:var(--bad)}";
  h += ".raw{font:12px/1.5 ui-monospace,Menlo,monospace;background:#0f172a;color:#c7d2fe;padding:14px;overflow:auto;border-radius:10px}";
  h += ".btn{background:var(--accent);color:#fff;border:0;padding:11px 16px;border-radius:9px;font-weight:700;margin:4px 6px 4px 0;cursor:pointer}";
  h += ".btn.alt{background:var(--warn)}";
  h += ".wifi input,.settings select{width:100%;padding:11px;margin:6px 0 12px;border:1px solid var(--line);border-radius:8px;font-size:14px;background:var(--card);color:var(--ink)}";
  h += ".bar{position:relative;height:18px;background:var(--line);border-radius:9px;overflow:hidden;margin-top:9px}";
  h += ".fill{position:absolute;top:0;bottom:0;left:0;width:0;background:linear-gradient(90deg,#22c55e,#16a34a);transition:width .4s}";
  h += ".fill.rev{left:auto;right:0;background:linear-gradient(90deg,#f87171,#dc2626)}";
  h += ".barlabel{position:absolute;inset:0;text-align:center;font-size:11px;line-height:18px;font-weight:700;color:var(--ink)}";
  h += ".settings{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.status{font-size:13px;color:var(--muted);margin-top:10px}";
  h += "@media(max-width:900px){.settings{grid-template-columns:1fr 1fr}}@media(max-width:760px){.grid{grid-template-columns:1fr 1fr}.tab{flex:1;text-align:center}}";
  h += "</style><script>";
  h += "function by(i){return document.getElementById(i)}function set(i,v){let e=by(i);if(e)e.textContent=v}function pct(v){return Math.max(0,Math.min(100,Number(v)||0))}function tab(n){document.querySelectorAll('.tab,.page').forEach(e=>e.classList.remove('active'));by('tab_'+n).classList.add('active');by('page_'+n).classList.add('active')}function upd(){fetch('/data').then(r=>r.json()).then(d=>{set('online',d.online);by('online').className=d.online==='Да'?'ok':'bad';set('mode',d.mode);set('load',d.load_w+' W');set('lp',d.load_pct+' %');set('pv',d.pv_w+' W');set('pv2',d.pv_v+' V / '+d.pv_a+' A');set('bat',d.bat_w+' W');set('bat2',d.bat_v+' V / '+d.bat_a+' A / '+d.bat_pct+' %');set('grid',d.grid_w+' W');set('grid2',d.grid_v+' V / '+d.grid_hz+' Hz');set('age',d.last_age+' s');set('ok',d.ok);set('fail',d.fail);set('cmd',d.cmd);set('raw',d.raw);set('setting',d.setting);set('busy',d.busy);let lp=pct(d.load_pct),lf=by('lf');if(lf)lf.style.width=lp+'%';set('ll',lp+'%');let bp=pct(d.bat_pct),bf=by('bf'),bw=Number(d.bat_w)||0;if(bf){bf.style.width=bp+'%';bf.className=bw<0?'fill rev':'fill'}set('bl',bp+'%');set('brcli',d.br_client);set('brst',d.br_active?'клиент подключён':'ждёт клиента');by('brst').className=d.br_active?'ok':'bad';set('brrx',d.br_tcp2uart);set('brtx',d.br_uart2tcp);set('brage',d.br_age+' s');set('brsess',d.br_sessions);set('brport',d.br_port);set('baudv',d.baud)})}function postSet(k,id){let s=by('setting');if(s)s.textContent='Sending...';fetch('/set',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'key='+encodeURIComponent(k)+'&value='+encodeURIComponent(by(id).value)}).then(r=>r.text().then(t=>{set('setting',t);setTimeout(upd,900)})).catch(()=>set('setting','Error'))}setInterval(upd,2000);window.onload=upd;";
  h += "</script></head><body><div class='top'><div class='brand'>&#9728;&#65039; ESP8266 Solar Lite<span class='fw'>" FW_VERSION "</span></div><div class='tabs'><button id='tab_dash' class='tab active' onclick=\"tab('dash')\">Dashboard</button><button id='tab_settings' class='tab' onclick=\"tab('settings')\">Settings</button></div></div>";
  h += "<div id='page_dash' class='page active'>";
  h += "<div class='card'><b id='online'>-</b><span id='mode' class='muted'>-</span></div><br><div class='grid'>";
  h += "<div class='card'><span class='muted'>&#9889; Load</span><b id='load'>-</b><span id='lp'>-</span><div class='bar'><div id='lf' class='fill'></div><span id='ll' class='barlabel'>-</span></div></div>";
  h += "<div class='card'><span class='muted'>&#9728;&#65039; Solar PV</span><b id='pv'>-</b><span id='pv2'>-</span></div>";
  h += "<div class='card'><span class='muted'>&#128267; Battery</span><b id='bat'>-</b><span id='bat2'>-</span><div class='bar'><div id='bf' class='fill'></div><span id='bl' class='barlabel'>-</span></div></div>";
  h += "<div class='card'><span class='muted'>&#128268; Grid</span><b id='grid'>-</b><span id='grid2'>-</span></div></div>";
  h += "<br><div class='grid'><div class='card'><span class='muted'>Last data</span><b id='age'>-</b></div><div class='card'><span class='muted'>Packets OK</span><b id='ok'>-</b></div><div class='card'><span class='muted'>Parse fail</span><b id='fail'>-</b></div><div class='card'><span class='muted'>Last cmd</span><b id='cmd'>-</b></div></div>";
  h += "<br><div class='card'><span class='muted'>&#128268; RS232 bridge (Orange Pi &rarr; TCP :<span id='brport'>-</span>)</span>";
  h += "<b id='brst' class='bad'>-</b><span class='muted'>client: <span id='brcli'>-</span></span>";
  h += "<div class='grid' style='margin-top:10px'><div><span class='muted'>TCP &rarr; UART, bytes</span><b id='brrx'>-</b></div>";
  h += "<div><span class='muted'>UART &rarr; TCP, bytes</span><b id='brtx'>-</b></div>";
  h += "<div><span class='muted'>Last byte</span><b id='brage'>-</b></div>";
  h += "<div><span class='muted'>Sessions / baud</span><b id='brsess'>-</b> / <span id='baudv'>-</span></div></div></div>";
  h += "</div><div id='page_settings' class='page'>";
  h += "<br><div class='card'><h3>Settings</h3><div class='settings'>";
  h += "<div><span class='muted'>Output priority</span><select id='set_out'><option value='usb'>USB: Utility first</option><option value='sub'>SUB: Solar first</option><option value='sbu'>SBU: Battery first</option></select><button class='btn' onclick=\"postSet('output','set_out')\">Save</button></div>";
  h += "<div><span class='muted'>Charger priority</span><select id='set_chg'><option value='solar_first'>Solar first</option><option value='both'>Solar + Utility</option><option value='utility'>Utility only</option><option value='solar_only'>Solar only</option></select><button class='btn' onclick=\"postSet('charger','set_chg')\">Save</button></div>";
  h += "<div><span class='muted'>Battery type</span><select id='set_btype'><option value='agm'>AGM</option><option value='flooded'>Flooded</option><option value='user'>User</option></select><button class='btn' onclick=\"postSet('battery_type','set_btype')\">Save</button></div>";
  h += "<div><span class='muted'>Max charge</span><select id='set_max'><option>10</option><option>20</option><option>30</option><option>40</option><option>50</option><option>60</option></select><button class='btn alt' onclick=\"postSet('max_charge','set_max')\">Save</button></div>";
  h += "<div><span class='muted'>Max grid charge</span><select id='set_grid'><option>2</option><option>10</option><option>20</option><option>30</option><option>40</option><option>50</option><option>60</option></select><button class='btn alt' onclick=\"postSet('max_grid_charge','set_grid')\">Save</button></div>";
  h += "</div><div class='status'>Status: <span id='setting'>-</span> | Busy: <span id='busy'>-</span></div></div>";
  h += "<br><div class='card'><h3>RS232 bridge (TCP &rarr; инвертор)</h3><form method='POST' action='/bridge'>TCP port:<input name='port' value='" + String(conf.bridgePort) + "'>";
  h += "UART baud:<select name='baud'><option" + String(conf.baud == 1200 ? " selected" : "") + ">1200</option><option" + String(conf.baud == 2400 ? " selected" : "") + ">2400</option>";
  h += "<option" + String(conf.baud == 4800 ? " selected" : "") + ">4800</option><option" + String(conf.baud == 9600 ? " selected" : "") + ">9600</option><option" + String(conf.baud == 19200 ? " selected" : "") + ">19200</option></select>";
  h += "<button class='btn'>Save bridge</button></form><div class='status'>Пока TCP-клиент подключён, локальный опрос пауза: на линии один мастер.</div></div>";
  h += "<br><div class='card'><div class='muted'>Raw</div><pre id='raw' class='raw'>-</pre></div>";
  h += "<br><div class='card wifi'><form method='POST' action='/wifi'>SSID:<input name='s' maxlength='31' value='" + htmlEscape(conf.ssid) + "'>Wi-Fi password:<input name='p' maxlength='31' type='password' value='" + htmlEscape(conf.pass) + "'>Admin password:<input name='a' maxlength='15' type='password' value='" + htmlEscape(conf.adminPass) + "'><button class='btn'>Save Wi-Fi</button></form></div>";
  h += "<br><div class='card'><a href='/update'>BIN upload / OTA update</a></div></div></body></html>";
  server.send(200, "text/html; charset=utf-8", h);
}

void handleWiFiSave() {
  if (!isAdmin()) return;
  saveConfig(server.arg("s"), server.arg("p"), server.arg("a"));
  server.send(200, "text/html; charset=utf-8", "<html><body>Saved. Rebooting...</body></html>");
  delay(800);
  ESP.restart();
}

bool bridgeActive() {
  return bridgeClient && bridgeClient.connected();
}

void bridgePump() {
  uint16_t budget = 64;
  while (budget-- && bridgeClient.available()) {
    int b = bridgeClient.read();
    if (b < 0) break;
    invSerial.write((uint8_t)b);
    brTcpToUart++;
    brLastMs = millis();
  }
  budget = 128;
  while (budget-- && invSerial.available()) {
    int b = invSerial.read();
    if (b < 0) break;
    bridgeClient.write((uint8_t)b);
    brUartToTcp++;
    brLastMs = millis();
  }
  digitalWrite(LED_PIN, (millis() - brLastMs < 120) ? LOW : HIGH);
}

// Один активный TCP-клиент: на линии 2400 бод два мастера несовместимы.
void bridgeService() {
  if (!bridgeActive()) {
    if (bridgeClient) {
      bridgeClient.stop();
      bridgeClient = WiFiClient();
      brClientIp = "-";
      pollPausedUntil = millis() + 800;
      while (invSerial.available()) invSerial.read();
    }
    WiFiClient c = bridgeServer.accept();
    if (c) {
      bridgeClient = c;
      bridgeClient.setNoDelay(true);
      brClientIp = c.remoteIP().toString();
      brSessions++;
      brLastMs = millis();
      pendingWriteCommand = "";
      pendingWriteName = "";
      settingStatus = "Bridge client connected: " + brClientIp;
    }
  }
}

void handleBridgeSave() {
  if (!isAdmin()) return;
  int port = server.arg("port").toInt();
  int baud = server.arg("baud").toInt();
  if (port < 1024 || port > 65535) {
    server.send(400, "text/plain; charset=utf-8", "Bad port (1024-65535)");
    return;
  }
  if (!(baud == 1200 || baud == 2400 || baud == 4800 || baud == 9600 || baud == 19200)) {
    server.send(400, "text/plain; charset=utf-8", "Bad baud (1200/2400/4800/9600/19200)");
    return;
  }
  conf.bridgePort = (uint16_t)port;
  conf.baud = (uint16_t)baud;
  EEPROM.put(0, conf);
  EEPROM.commit();
  bridgeServer.begin(conf.bridgePort);
  invSerial.begin(conf.baud);
  server.send(200, "text/plain; charset=utf-8",
              "Saved: port " + String(conf.bridgePort) + ", " + String(conf.baud) + " baud");
}


// ---------- настройка по USB-serial (UART0, 115200) ----------
void cliHelp() {
  Serial.println(F("--- solar-monitor Wemos bridge ---"));
  Serial.println(F("show                       текущие настройки"));
  Serial.println(F("ssid <имя сети>            Wi-Fi SSID"));
  Serial.println(F("pass <пароль>              Wi-Fi пароль"));
  Serial.println(F("admin <пароль>             пароль веб/OTA"));
  Serial.println(F("port <1024..65535>         TCP-порт моста (по умолчанию 9999)"));
  Serial.println(F("baud <1200|2400|4800|9600|19200>  скорость линии инвертора"));
  Serial.println(F("reboot | factory           перезагрузка / сброс настроек"));
}

void cliSave() {
  saveConfig(String(conf.ssid), String(conf.pass), String(conf.adminPass));
}

void cliHandle(String l) {
  l.trim();
  int sp = l.indexOf(' ');
  String cmd = sp < 0 ? l : l.substring(0, sp);
  String arg = sp < 0 ? "" : l.substring(sp + 1);
  arg.trim();
  cmd.toLowerCase();
  if (cmd == "help" || cmd == "?") { cliHelp(); return; }
  if (cmd == "show") {
    Serial.printf("ssid=%s pass=%s admin=%s port=%u baud=%u ip=%s ap=%d\n",
                  conf.ssid, conf.pass, conf.adminPass, conf.bridgePort, conf.baud,
                  WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "-",
                  apMode ? 1 : 0);
    return;
  }
  if (cmd == "ssid") {
    if (!arg.length()) { Serial.println(F("ERR: ssid <name>")); return; }
    arg.substring(0, sizeof(conf.ssid) - 1).toCharArray(conf.ssid, sizeof(conf.ssid));
    cliSave();
    Serial.printf("OK ssid=%s (reboot to apply)\n", conf.ssid);
    return;
  }
  if (cmd == "pass") {
    arg.substring(0, sizeof(conf.pass) - 1).toCharArray(conf.pass, sizeof(conf.pass));
    cliSave();
    Serial.println(F("OK pass saved (reboot to apply)"));
    return;
  }
  if (cmd == "admin") {
    if (!arg.length()) { Serial.println(F("ERR: admin <password>")); return; }
    arg.substring(0, sizeof(conf.adminPass) - 1).toCharArray(conf.adminPass, sizeof(conf.adminPass));
    cliSave();
    Serial.println(F("OK admin password saved"));
    return;
  }
  if (cmd == "port") {
    int v = arg.toInt();
    if (v < 1024 || v > 65535) { Serial.println(F("ERR: port 1024..65535")); return; }
    conf.bridgePort = (uint16_t)v;
    cliSave();
    bridgeServer.begin(conf.bridgePort);
    Serial.printf("OK port=%u\n", conf.bridgePort);
    return;
  }
  if (cmd == "baud") {
    int v = arg.toInt();
    if (!(v == 1200 || v == 2400 || v == 4800 || v == 9600 || v == 19200)) {
      Serial.println(F("ERR: baud 1200/2400/4800/9600/19200")); return;
    }
    conf.baud = (uint16_t)v;
    cliSave();
    invSerial.begin(conf.baud);
    Serial.printf("OK baud=%u\n", conf.baud);
    return;
  }
  if (cmd == "reboot") { Serial.println(F("rebooting...")); delay(200); ESP.restart(); return; }
  if (cmd == "factory") {
    conf = LiteConfig();
    EEPROM.put(0, conf); EEPROM.commit();
    Serial.println(F("factory reset, rebooting..."));
    delay(200); ESP.restart(); return;
  }
  Serial.println(F("ERR: unknown, type help"));
}

void cliLoop() {
  static String line;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c != '\n') {
      if (line.length() < 150) line += c;
      continue;
    }
    if (line.length()) cliHandle(line);
    line = "";
  }
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setSleepMode(WIFI_NONE_SLEEP);
  if (!hasWiFi()) {
    apMode = true;
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);
    return;
  }

  WiFi.begin(conf.ssid, conf.pass);
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < WIFI_TIMEOUT_MS) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    apMode = false;
  } else {
    apMode = true;
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);
  }
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);
  Serial.begin(115200);
  bootMs = millis();
  loadConfig();
  invSerial.begin(conf.baud);
  pinMode(INV_RX_PIN, INPUT_PULLUP);  // свободный RX не должен ловить шум (FW122)
  connectWiFi();

  server.on("/", handleRoot);
  server.on("/data", handleData);
  server.on("/set", HTTP_POST, handleSet);
  server.on("/wifi", HTTP_POST, handleWiFiSave);
  server.on("/bridge", HTTP_POST, handleBridgeSave);
  httpUpdater.setup(&server, "/update", "admin", conf.adminPass);
  server.begin();
  Serial.setTimeout(50);
  cliHelp();
  bridgeServer.begin(conf.bridgePort);
  bridgeServer.setNoDelay(true);

  sendCommand("QPIGS");
  lastPoll = millis();
  Serial.printf("ready: %s\n", apMode ? WiFi.softAPIP().toString().c_str() : WiFi.localIP().toString().c_str());
}

void loop() {
  server.handleClient();
  cliLoop();

  // TCP-клиент (Orange Pi / solar-monitor) — прозрачный мост и полная пауза локального опроса.
  bridgeService();
  if (bridgeActive()) {
    bridgePump();
    return;
  }

  unsigned long interval = (millis() - bootMs < STARTUP_FAST_MS || !inv.updated) ? FAST_POLL_INTERVAL_MS : POLL_INTERVAL_MS;
  if (writeBusy() && millis() - pendingWriteStarted > WRITE_TIMEOUT_MS) {
    settingStatus = "Timeout: " + pendingWriteName;
    pendingWriteCommand = "";
    pendingWriteName = "";
    pollPausedUntil = millis() + 1000;
  }

  if (!writeBusy() && millis() > pollPausedUntil && millis() - lastPoll > interval) {
    lastPoll = millis();
    if (!inv.updated) {
      sendCommand("QPIGS");
    } else if (nextModePoll) {
      nextModePoll = false;
      sendCommand("QMOD");
    } else {
      nextModePoll = (packetsOk % 15 == 0);
      sendCommand("QPIGS");
    }
  }

  if (invSerial.available()) {
    String r = invSerial.readStringUntil('\r');
    handleFrame(r);
    digitalWrite(LED_PIN, LOW);
    delay(20);
    digitalWrite(LED_PIN, HIGH);
  }
}
