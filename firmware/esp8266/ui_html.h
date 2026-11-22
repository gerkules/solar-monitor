// UI прошивки Wemos/ESP8266: схема потоков (солнце-панели, сеть, инвертор, дом, АКБ),
// график, настройки, мост TCP<->RS232, диагностика. Всё статично и лежит в PROGMEM,
// данные тянутся из /data и /history (JSON).
static const char UI_HTML[] PROGMEM = R"HTML(<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Solar · Wemos</title><style>
:root{--bg:#eef2f7;--card:#fff;--ink:#1f2a37;--muted:#64748b;--line:#e2e8f0;--blue:#2563eb;--sun:#f6b93b;--green:#16a34a;--red:#dc2626;--radius:14px}
@media(prefers-color-scheme:dark){:root{--bg:#0b1220;--card:#141d2e;--ink:#e7ecf5;--muted:#8b96a8;--line:#233046}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif}
.top{background:linear-gradient(135deg,#0f2f4c,#1d6fa5);color:#fff;padding:18px 5vw 0;box-shadow:0 2px 12px rgba(0,0,0,.18)}
.brand{font-size:20px;font-weight:800}.brand small{display:block;font-size:12px;font-weight:400;opacity:.75;margin-top:2px}
.tabs{display:flex;gap:6px;margin-top:14px}.tab{border:0;background:rgba(255,255,255,.14);color:#fff;padding:11px 16px;border-radius:10px 10px 0 0;font-weight:700;cursor:pointer;font-size:14px}
.tab.active{background:var(--bg);color:var(--ink)}.page{display:none;padding:18px 5vw 40px;max-width:1060px;margin:0 auto}.page.active{display:block}
.card{background:var(--card);border-radius:var(--radius);padding:16px;box-shadow:0 1px 3px rgba(15,23,42,.08);margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.metric b{display:block;font-size:22px;font-weight:800;margin:4px 0}
.muted{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.4px;font-weight:700}
.ok{color:var(--green)}.bad{color:var(--red)}.warn{color:#d97706}
.flowbox{padding:6px 4px}.flow{width:100%;height:auto;display:block}
.flow .wire{stroke:var(--line);stroke-width:7;fill:none;stroke-linecap:round}
.flow .wire.on{stroke:var(--blue);stroke-dasharray:10 10;animation:dash 1s linear infinite}
.flow .wire.on.rev{animation-direction:reverse}
.flow .wire.live{stroke:var(--green)}
@keyframes dash{to{stroke-dashoffset:-20}}
.flow text{fill:var(--ink);font-family:inherit}.flow .s{font-size:13px;font-weight:700;fill:var(--muted);text-anchor:middle;text-transform:uppercase;letter-spacing:.4px}
.flow .t{font-size:17px;font-weight:800;text-anchor:middle}.flow .c{font-size:11px;fill:var(--muted);text-anchor:middle}
.row{display:grid;grid-template-columns:1.6fr 1fr;gap:10px;padding:7px 0;border-bottom:1px solid var(--line);color:var(--muted)}
.row:last-child{border-bottom:0}.row b{color:var(--ink);font-weight:600;text-align:right}
select,input{width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;font-size:14px;background:var(--card);color:var(--ink);margin:5px 0 10px}
.btn{background:var(--blue);color:#fff;border:0;padding:11px 16px;border-radius:9px;font-weight:700;margin:4px 6px 4px 0;cursor:pointer}
.btn.alt{background:#d97706}input[type=checkbox]{width:auto;height:18px;margin:0 8px 0 0;vertical-align:-3px}label{display:block;margin:4px 0 10px;font-size:13px;color:var(--muted)}canvas{width:100%;height:150px;display:block}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted);margin-top:6px}
.dot{display:inline-block;width:14px;height:3px;margin-right:5px;vertical-align:middle}
@media(max-width:820px){.grid{grid-template-columns:1fr 1fr}}
</style></head><body>
<div class="top"><div class="brand">☀️ Solar Wemos<span id="sub">подключение…</span></div>
<div class="tabs"><button class="tab active" data-tab="flow">Схема</button><button class="tab" data-tab="set">Настройки</button><button class="tab" data-tab="br">Мост</button><button class="tab" data-tab="diag">Диагностика</button></div></div>

<div class="page active" id="p-flow">
<div class="card"><div style="display:flex;justify-content:space-between;align-items:center">
<div><span class="muted">Состояние</span><br><b id="state" style="font-size:18px">—</b> <span id="mode" class="muted"></span></div>
<div style="text-align:right"><span class="muted">Температура</span><br><b id="temp" style="font-size:18px">—</b></div></div></div>
<div class="card flowbox"><svg class="flow" viewBox="0 0 520 350" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="sunG" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#ffd54a"/><stop offset="1" stop-color="#f1852b"/></linearGradient>
<clipPath id="batClip"><rect x="228" y="258" width="34" height="30" rx="2"/></clipPath>
</defs>
<path id="w-pv" class="wire" d="M260 96 L260 132"/>
<path id="w-grid" class="wire" d="M128 168 L206 168"/>
<path id="w-load" class="wire" d="M314 168 L392 168"/>
<path id="w-bat" class="wire" d="M260 204 L260 258"/>
<text class="s" x="260" y="12">Солнце / PV</text>
<g><circle cx="238" cy="30" r="9" fill="url(#sunG)"/>
<g stroke="#f6b93b" stroke-width="2" stroke-linecap="round"><path d="M238 14v5M238 41v5M222 30h5M249 30h5M227 19l3.5 3.5M245.5 37.5l3.5 3.5M249 19l-3.5 3.5M230.5 37.5L227 41"/></g>
<g transform="translate(172 34) skewX(-12)"><rect width="118" height="52" rx="3" fill="#1e3a5f" stroke="#4f8fd6" stroke-width="2"/>
<path d="M39 0v52M78 0v52M0 26h118" stroke="#4f8fd6" stroke-width="1.5" opacity=".85"/></g>
<text class="c" x="231" y="104" id="pvV">— В / — А</text>
<text class="t" x="260" y="92" id="pvW">—</text></g>
<text class="s" x="66" y="140">Сеть</text>
<g><path d="M66 152l10 40M66 152l-10 40" stroke="#4f8fd6" stroke-width="3" fill="none" stroke-linecap="round"/>
<path d="M59 160h14M57 168h18M55 176h22M53 184h26M48 192h36" stroke="#4f8fd6" stroke-width="2.6" stroke-linecap="round"/>
<text class="t" x="66" y="214" id="gridW">—</text><text class="c" x="66" y="230" id="gridV">—</text></g>
<g><rect x="212" y="132" width="96" height="72" rx="6" fill="#f4f6f8" stroke="#9aa4b0" stroke-width="2"/>
<rect x="212" y="176" width="96" height="22" rx="2" fill="#16202b"/><rect x="212" y="173" width="96" height="4" fill="#1e9ee8"/>
<rect x="222" y="184" width="34" height="10" rx="1.5" fill="#0a2a4a" stroke="#2ea8e8"/>
<path d="M226 189h8M238 186v6M243 186l4 3-4 3" stroke="#7fd1ff" stroke-width="1.2" fill="none"/>
<g fill="#5f6b7a"><circle cx="268" cy="189" r="1.4"/><circle cx="274" cy="189" r="1.4"/><circle cx="280" cy="189" r="1.4"/></g>
<text class="t" x="260" y="224" id="invW">—</text><text class="c" x="260" y="240" id="invCap">—</text></g>
<text class="s" x="454" y="140">Дом</text>
<g><rect x="410" y="156" width="88" height="46" fill="#f2ede4" stroke="#c9c2b6"/>
<path d="M402 156l52-38 52 38z" fill="#1e3a5f" stroke="#26313f" stroke-width="2"/>
<g stroke="#5c9be0" stroke-width="1" opacity=".9"><path d="M418 156l36-26 36 26M454 130v26M430 147h48"/></g>
<rect x="420" y="164" width="16" height="14" fill="#ffca6a"/><rect x="474" y="164" width="16" height="14" fill="#ffca6a"/>
<rect x="444" y="168" width="18" height="34" rx="1" fill="#6b4a2f"/>
<text class="t" x="454" y="218" id="loadW">—</text><text class="c" x="454" y="234" id="loadP">—</text></g>
<text class="s" x="260" y="256">АКБ</text>
<g><rect x="243" y="286" width="18" height="6" rx="2" fill="#8b9bb0"/>
<rect x="230" y="262" width="44" height="42" rx="4" fill="none" stroke="#16a34a" stroke-width="2.6"/>
<rect id="batFill" x="234" y="266" width="36" height="34" rx="2" fill="#16a34a" opacity=".8" clip-path="url(#batClip)"/>
<text id="batPct" x="252" y="287" font-size="13" font-weight="800" text-anchor="middle" fill="#fff">—</text>
<text class="t" x="260" y="324" id="batW">—</text><text class="c" x="260" y="340" id="batV">—</text></g>
</svg></div>
<div class="grid"><div class="card metric"><span class="muted">Нагрузка</span><b id="m-load">—</b><span class="muted" id="m-lp">—</span></div>
<div class="card metric"><span class="muted">PV</span><b id="m-pv">—</b><span class="muted" id="m-pvv">—</span></div>
<div class="card metric"><span class="muted">АКБ</span><b id="m-bat">—</b><span class="muted" id="m-batv">—</span></div>
<div class="card metric"><span class="muted">Сеть</span><b id="m-grid">—</b><span class="muted" id="m-gridv">—</span></div></div>
<div class="card"><span class="muted">Мощности за последний час</span><canvas id="ch"></canvas>
<div class="legend"><span><i class="dot" style="background:#2563eb"></i>нагрузка</span><span><i class="dot" style="background:#f6b93b"></i>PV</span><span><i class="dot" style="background:#16a34a"></i>АКБ</span><span><i class="dot" style="background:#dc2626"></i>сеть</span></div></div>
</div>

<div class="page" id="p-set">
<div class="card"><span class="muted">Уставки инвертора</span><div class="grid" style="grid-template-columns:1fr 1fr;margin-top:8px">
<div><span class="muted">Output source</span><select id="s-out"><option value="usb">USB: Utility first</option><option value="sub">SUB: Solar first</option><option value="sbu">SBU: Battery first</option></select><button class="btn" onclick="setv('output','s-out')">Сохранить</button></div>
<div><span class="muted">Charger source</span><select id="s-chg"><option value="solar_first">Solar first</option><option value="both">Solar + Utility</option><option value="utility">Utility only</option><option value="solar_only">Solar only</option></select><button class="btn" onclick="setv('charger','s-chg')">Сохранить</button></div>
<div><span class="muted">Тип АКБ</span><select id="s-bt"><option value="agm">AGM</option><option value="flooded">Flooded</option><option value="user">User</option></select><button class="btn" onclick="setv('battery_type','s-bt')">Сохранить</button></div>
<div><span class="muted">Max charge, A</span><select id="s-mc"><option>10</option><option>20</option><option>30</option><option>40</option><option>50</option><option>60</option></select><button class="btn alt" onclick="setv('max_charge','s-mc')">Сохранить</button></div>
<div><span class="muted">Max grid charge, A</span><select id="s-gc"><option>2</option><option>10</option><option>20</option><option>30</option><option>40</option><option>50</option><option>60</option></select><button class="btn alt" onclick="setv('max_grid_charge','s-gc')">Сохранить</button></div>
</div><div class="row" style="margin-top:10px"><span>Статус записи</span><b id="setmsg">—</b></div></div>
<div class="card"><span class="muted">Wi-Fi и доступ</span>
<div class="row"><span>Сеть</span><b id="w-ssid">—</b></div>
<div class="row"><span>IP / RSSI</span><b id="w-ip">—</b></div>
<form method="POST" action="/wifi"><span class="muted">SSID</span><input name="s" maxlength="31" placeholder="имя сети"><span class="muted">Пароль Wi-Fi</span><input name="p" maxlength="31" type="password"><span class="muted">Пароль admin</span><input name="a" maxlength="15" type="password" placeholder="оставьте пустым, чтобы не менять"><button class="btn">Сохранить и перезагрузить</button></form></div>
<div class="card"><a href="/update">Обновление прошивки (OTA, .bin)</a></div>
</div>

<div class="page" id="p-br">
<div class="card"><span class="muted">Мост TCP ⇄ RS232 (для Orange Pi / solar-monitor)</span>
<div class="row"><span>Трансляция на другое устройство</span><b id="b-en">—</b></div>
<div class="row"><span>Состояние</span><b id="b-state">—</b></div>
<div class="row"><span>Клиент</span><b id="b-cli">—</b></div>
<div class="row"><span>TCP → UART, байт</span><b id="b-rx">—</b></div>
<div class="row"><span>UART → TCP, байт</span><b id="b-tx">—</b></div>
<div class="row"><span>Последний байт</span><b id="b-age">—</b></div>
<div class="row"><span>Сессий</span><b id="b-sess">—</b></div>
<form method="POST" action="/bridge"><label><input type="checkbox" name="en" id="b-en-chk" value="1"> разрешить трансляцию (Wemos = TCP-сервер для Orange Pi/VDS)</label><span class="muted">TCP-порт</span><input name="port" id="b-port" value="9999">
<span class="muted">Скорость линии инвертора</span><select name="baud" id="b-baud"><option>1200</option><option>2400</option><option>4800</option><option>9600</option><option>19200</option></select>
<button class="btn">Сохранить мост</button></form>
<div class="row"><span>Локальный опрос</span><b id="b-local">—</b></div></div>
</div>

<div class="page" id="p-diag">
<div class="card"><div class="row"><span>Прошивка</span><b id="d-fw">—</b></div>
<div class="row"><span>Время работы</span><b id="d-up">—</b></div>
<div class="row"><span>Свободно RAM</span><b id="d-heap">—</b></div>
<div class="row"><span>RSSI</span><b id="d-rssi">—</b></div>
<div class="row"><span>Кадров OK / ошибок</span><b id="d-pk">—</b></div>
<div class="row"><span>Последняя команда</span><b id="d-cmd">—</b></div>
<div class="row"><span>Возраст данных</span><b id="d-age">—</b></div></div>
<div class="card"><span class="muted">Последний кадр</span><pre id="d-raw" style="overflow:auto;font-size:12px">—</pre></div>
</div>

<script>
const $=i=>document.getElementById(i);
function tab(n){document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===n));
document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='p-'+n))}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
const fmt=(v,d=0)=>(v===null||v===undefined||isNaN(v))?'—':Number(v).toFixed(d);
function setw(id,val,rev,live){const e=$(id);if(!e)return;const on=Math.abs(val)>5;e.classList.toggle('on',on);e.classList.toggle('rev',!!rev);e.classList.toggle('live',!!live)}
let hist=[];
function draw(){
 const c=$('ch');if(!c)return;const w=c.width=c.clientWidth*2,h=c.height=300,x=c.getContext('2d');
 x.clearRect(0,0,w,h);x.strokeStyle='#e2e8f0';x.lineWidth=2;for(let i=0;i<4;i++){const y=20+i*(h-40)/3;x.beginPath();x.moveTo(40,y);x.lineTo(w-8,y);x.stroke()}
 const n=hist.length;if(!n)return;let max=200;hist.forEach(p=>{for(const v of p)max=Math.max(max,Math.abs(v))});max*=1.1;
 const line=(k,col)=>{x.strokeStyle=col;x.lineWidth=3;x.beginPath();hist.forEach((p,i)=>{const xx=40+i*(w-50)/Math.max(1,n-1),yy=h-20-Math.max(0,Math.min(max,p[k]))*(h-45)/max;i?x.lineTo(xx,yy):x.moveTo(xx,yy)});x.stroke()};
 line(0,'#2563eb');line(1,'#f6b93b');line(2,'#16a34a');line(3,'#dc2626');
}
function upd(){
 fetch('/data').then(r=>r.json()).then(d=>{
  const on=d.online==='Да';$('state').textContent=on?'Инвертор на связи':'Нет связи с инвертором';$('state').className=on?'ok':'bad';
  $('mode').textContent=d.mode||'';$('sub').textContent=d.fw+' · '+d.cmd;
  const lw=+d.load_w||0,pv=+d.pv_w||0,bw=+d.bat_w||0,gw=+d.grid_w||0;
  $('pvW').textContent=pv+' W';$('pvV').textContent=fmt(d.pv_v,1)+' В / '+fmt(d.pv_a,1)+' А';
  $('gridW').textContent=gw+' W';$('gridV').textContent=fmt(d.grid_v,1)+' В / '+fmt(d.grid_hz,1)+' Гц';
  $('invW').textContent=lw+' W';$('invCap').textContent=(d.mode||'')+' · '+d.load_pct+' %';
  $('loadW').textContent=lw+' W';$('loadP').textContent=d.load_pct+' %';
  $('batW').textContent=bw+' W';$('batV').textContent=fmt(d.bat_v,1)+' В / '+d.bat_pct+' %';
  $('batPct').textContent=d.bat_pct+' %';const f=$('batFill');if(f){f.setAttribute('height',Math.max(0,Math.min(34,34*d.bat_pct/100)));f.setAttribute('y',300-4-Math.max(0,Math.min(34,34*d.bat_pct/100)));f.setAttribute('fill',bw<0?'#dc2626':'#16a34a')}
  $('m-load').textContent=lw+' W';$('m-lp').textContent=d.load_pct+' %';$('m-pv').textContent=pv+' W';$('m-pvv').textContent=fmt(d.pv_v,1)+' В';
  $('m-bat').textContent=bw+' W';$('m-batv').textContent=fmt(d.bat_v,1)+' В';$('m-grid').textContent=gw+' W';$('m-gridv').textContent=fmt(d.grid_v,0)+' В';
  $('temp').textContent=(d.temp||'—')+' °C';
  setw('w-pv',pv,false,true);setw('w-grid',gw,false);setw('w-load',lw,false);setw('w-bat',Math.abs(bw),bw<0);
  $('b-en').textContent=d.br_enabled?'включена':'выключена';$('b-en').className=d.br_enabled?'ok':'warn';$('b-en-chk').checked=d.br_enabled;
 $('b-state').textContent=d.br_enabled?(d.br_active?'клиент подключён':'ждёт клиента'):'трансляция выключена';$('b-state').className=d.br_enabled?(d.br_active?'ok':'warn'):'warn';
  $('b-cli').textContent=d.br_client;$('b-rx').textContent=d.br_tcp2uart;$('b-tx').textContent=d.br_uart2tcp;
  $('b-age').textContent=d.br_age+' с назад';$('b-sess').textContent=d.br_sessions;
  $('b-local').textContent=d.br_active?'пауза (линию ведёт сервер)':(d.br_enabled?'активен':'активен (трансляция выкл.)');$('b-port').value=d.br_port;$('b-baud').value=d.baud;
  $('w-ssid').textContent=d.ssid||'(AP режим)';$('w-ip').textContent=d.ip+' / '+d.rssi+' dBm';
  $('d-fw').textContent=d.fw;$('d-up').textContent=d.up+' мин';$('d-heap').textContent=d.heap+' Б';$('d-rssi').textContent=d.rssi+' dBm';
  $('d-pk').textContent=d.ok+' / '+d.fail;$('d-cmd').textContent=d.cmd;$('d-age').textContent=d.last_age+' с';
  $('d-raw').textContent=d.raw;$('setmsg').textContent=d.setting;
 }).catch(()=>{$('state').textContent='Нет ответа от платы';$('state').className='bad'});
 fetch('/history').then(r=>r.json()).then(d=>{hist=d.pts||[];draw()}).catch(()=>{});
}
function setv(k,id){const v=$(id).value;$('setmsg').textContent='Отправляю…';
 fetch('/set',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'key='+encodeURIComponent(k)+'&value='+encodeURIComponent(v)})
 .then(r=>r.text()).then(t=>{$('setmsg').textContent=t;setTimeout(upd,900)}).catch(()=>$('setmsg').textContent='Ошибка')}
setInterval(upd,2000);window.onload=upd;window.onresize=draw;
</script></body></html>)HTML";
