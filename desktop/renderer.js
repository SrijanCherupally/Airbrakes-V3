const $=s=>document.querySelector(s),api=window.groundStation;let flights=[];

// Telemetry State & Event Feed
let telemetry = { state: 'IDLE', battery: null, lastUpdate: Date.now() };
let eventHistory = [];

// Activity Card Controller
class ActivityController {
  constructor() {
    this.header = $('#activityHeader');
    this.content = $('#activityContent');
    this.toggle = $('#activityToggle');
    this.icon = $('#activityIcon');
    this.status = $('#activityStatus');
    this.step = $('#activityStep');
    this.progressBar = $('#activityProgressBar');
    this.expanded = false;
    this.setupListeners();
  }

  setupListeners() {
    this.toggle.onclick = () => this.expanded ? this.collapse() : this.expand();
    this.header.onclick = (e) => {
      if (e.target !== this.toggle) this.expanded ? this.collapse() : this.expand();
    };
    $('#logsToggle').onclick = () => {
      const log = $('#log');
      log.classList.toggle('show');
      $('#logsToggle').textContent = log.classList.contains('show') ? 'Hide raw output ▲' : 'Show raw output ▼';
    };
  }

  expand() {
    this.expanded = true;
    this.content.classList.add('expanded');
    this.toggle.classList.add('expanded');
    setTimeout(() => this.header.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100);
  }

  collapse() {
    this.expanded = false;
    this.content.classList.remove('expanded');
    this.toggle.classList.remove('expanded');
  }

  autoExpand() {
    this.expand();
  }

  setStatus(status, icon = '⏸') {
    this.status.textContent = status;
    this.icon.textContent = icon;
    this.icon.classList.remove('running');
    if (status.includes('…') || status.includes('ing')) {
      this.icon.classList.add('running');
    }
  }

  setStep(step) {
    this.step.textContent = step;
  }

  setProgress(percent) {
    this.progressBar.style.width = percent + '%';
  }
}

const activityCtrl = new ActivityController();

// Dashboard Manager
class DashboardManager {
  constructor() {
    this.stateBadge = $('#stateBadge');
    this.batteryDisplay = $('#batteryDisplay');
    this.eventFeed = $('#eventFeed');
    this.activityIndicator = $('#activityIndicator');
    this.lastUpdateTime = Date.now();
    this.updateTimerInterval = setInterval(() => this.updateLastUpdateTime(), 1000);
  }

  updateState(state) {
    const stateMap = {
      'IDLE': { label: 'IDLE', class: 'idle' },
      'PAD': { label: 'PAD', class: 'pad' },
      'BOOST': { label: 'BOOST', class: 'boost' },
      'CONTROL': { label: 'CONTROL', class: 'control' },
      'DESCENT': { label: 'DESCENT', class: 'descent' },
      'LANDED': { label: 'LANDED', class: 'landed' },
      'GROUND_TEST_ARMED': { label: 'TEST ARMED', class: 'pad' },
      'GROUND_TEST_RECORDING': { label: 'TEST RECORDING', class: 'boost' }
    };
    const info = stateMap[state] || { label: state, class: 'idle' };
    this.stateBadge.textContent = info.label;
    this.stateBadge.className = `state-badge ${info.class}`;
    telemetry.state = state;
  }

  updateBattery(voltage) {
    const v = Number(voltage).toFixed(2);
    let status = 'good';
    if (v < 3.0) status = 'critical';
    else if (v < 3.3) status = 'warning';

    const el = this.batteryDisplay;
    el.textContent = `${v} V`;
    el.className = `telemetry-value ${status}`;
    el.classList.add('updating');
    setTimeout(() => el.classList.remove('updating'), 500);
    telemetry.battery = v;
  }

  addEvent(message, type = 'info') {
    const event = { message, type, timestamp: Date.now() };
    eventHistory.unshift(event);
    if (eventHistory.length > 20) eventHistory.pop();

    const item = document.createElement('div');
    item.className = `event-item ${type}`;
    item.innerHTML = `<span>${message}</span><button class="event-dismiss" onclick="this.parentElement.remove()">✕</button>`;
    this.eventFeed.insertBefore(item, this.eventFeed.firstChild);

    if (this.eventFeed.children.length > 5) {
      const old = this.eventFeed.children[this.eventFeed.children.length - 1];
      old.remove();
    }

    this.lastUpdateTime = Date.now();
  }

  updateLastUpdateTime() {
    const elapsed = Math.round((Date.now() - this.lastUpdateTime) / 1000);
    if (elapsed < 60) this.activityIndicator.textContent = `Last update: ${elapsed}s ago`;
    else this.activityIndicator.textContent = `Last update: ${(elapsed / 60).toFixed(1)}m ago`;
  }
}

const dashboard = new DashboardManager();

// Operation UI Manager
class OperationUI {
  constructor() {
    this.panel = $('#operationPanel');
    this.title = $('#opTitle');
    this.steps = $('#opSteps');
    this.step = $('#opStep');
    this.percent = $('#opPercent');
    this.progress = $('#opProgress');
    this.message = $('#opMessage');
    this.currentSteps = [];
    this.currentIndex = 0;
  }

  start(label, stepNames = []) {
    this.title.textContent = label;
    this.currentSteps = stepNames;
    this.currentIndex = 0;
    this.percent.textContent = '0%';
    this.progress.style.width = '0%';
    this.message.textContent = '';
    this.message.style.display = 'none';
    this.renderSteps();
    this.panel.classList.add('active');
  }

  renderSteps() {
    this.steps.innerHTML = '';
    this.currentSteps.forEach((name, i) => {
      const div = document.createElement('div');
      div.className = `op-step ${i < this.currentIndex ? 'done' : i === this.currentIndex ? 'active' : ''}`;
      const dot = document.createElement('div');
      dot.className = 'op-step-dot';
      if (i < this.currentIndex) dot.textContent = '✓';
      else if (i === this.currentIndex) dot.textContent = '•';
      else dot.textContent = i + 1;
      div.appendChild(dot);
      const label = document.createElement('span');
      label.textContent = name;
      div.appendChild(label);
      this.steps.appendChild(div);
    });
  }

  setStep(name, index = null) {
    if (index !== null) {
      this.currentIndex = index;
    } else {
      this.currentIndex = Math.max(0, this.currentSteps.findIndex(s => s === name));
    }
    this.step.textContent = name;
    this.renderSteps();
  }

  updateProgress(current, total) {
    const pct = Math.min(100, Math.round((current / total) * 100));
    this.percent.textContent = pct + '%';
    this.progress.style.width = pct + '%';
    if (total > 0) {
      this.currentIndex = Math.ceil((current / total) * (this.currentSteps.length - 1));
      this.renderSteps();
    }
  }

  setMessage(msg, isError = false) {
    this.message.textContent = msg;
    this.message.style.display = 'block';
    if (isError) this.progress.parentElement.classList.add('error');
  }

  complete(success = true) {
    if (success) {
      this.percent.textContent = '100%';
      this.progress.style.width = '100%';
      this.progress.parentElement.classList.add('success');
      this.currentIndex = this.currentSteps.length;
      this.renderSteps();
    }
  }

  hide() {
    this.panel.classList.remove('active');
  }

  addLog(text) {
    log(text);
  }
}

const opUI = new OperationUI();

// Enhanced toast with icons
function toast(m, isError=false, icon=null){
  const x=$('#toast');
  if (!icon) {
    if (m.includes('complete')) icon = '✓';
    else if (isError) icon = '✗';
    else if (m.includes('…')) icon = '⏳';
    else icon = 'ⓘ';
  }
  x.setAttribute('data-icon', icon || '');
  x.textContent = m;
  x.className=`toast show${isError?' error':''}`;
  clearTimeout(toast.t);
  toast.t=setTimeout(()=>{x.classList.add('hide');setTimeout(()=>x.className='toast',300)},4200);
}

function log(m){
  const x=$('#log');
  x.textContent+=`\n${m}`;
  x.scrollTop=x.scrollHeight;
}

// Enhanced serial monitor with syntax highlighting
function formatSerialLine(m) {
  const line = document.createElement('div');
  line.className = 'data-line';

  if (m.match(/^BATTERY_VOLTAGE:/)) {
    line.className += ' data-battery';
  } else if (m.match(/^ERROR|error|ERROR:/i)) {
    line.className += ' data-error';
  } else if (m.match(/STATE:|state change/i)) {
    line.className += ' data-state';
  }

  line.textContent = m;
  return line;
}

// Enhanced run function with progress UI
async function run(label, fn, stepNames = []) {
  const isLongOp = /Building|Flashing|Downloading/.test(label);

  if (isLongOp && stepNames.length > 0) {
    activityCtrl.autoExpand();
    activityCtrl.setStatus(`${label}…`, '⏳');
    opUI.start(label, stepNames);
  } else {
    $('#opstatus').textContent = `${label}…`;
  }

  toast(`${label}…`);

  try {
    const x = await fn();

    if (isLongOp && stepNames.length > 0) {
      activityCtrl.setStatus(`${label} complete`, '✓');
      opUI.complete(true);
      setTimeout(() => {
        opUI.hide();
        activityCtrl.setStatus('Ready', '⏸');
      }, 2000);
    } else {
      $('#opstatus').textContent = `${label} complete`;
    }

    toast(typeof x === 'string' ? x : `${label} complete`);
    return x;
  } catch (e) {
    activityCtrl.setStatus(`${label} failed`, '✗');
    $('#opstatus').textContent = `${label} failed`;

    if (isLongOp && stepNames.length > 0) {
      opUI.setMessage(e.message, true);
      setTimeout(() => activityCtrl.setStatus('Ready', '⏸'), 3000);
    }

    toast(e.message, true);
    if (/Building|Flashing/.test(label)) log(`ERROR: ${e.message}`);
    throw e;
  }
}

const themeStyle=document.createElement('style');themeStyle.textContent='body.dark{--bg:#11161c;--panel:#1b222b;--panel2:#202a35;--line:#34414e;--text:#edf2f7;--muted:#9aaaba;--cyan:#35c1b4;--green:#55c985;--orange:#e4a14a;--pink:#ef78a4;color-scheme:dark}body.dark header{background:#171d24}body.dark button,body.dark select,body.dark input{background:#202a35;border-color:#43515f;color:var(--text)}body.dark button:hover,body.dark select:hover{background:#2a3643;border-color:#617181}body.dark .tab.active{background:#173b3a;border-color:#2d8e85;color:#8fe5dd}body.dark .monitor,body.dark pre{background:#141a21;color:#d7e0e8}body.dark .field,body.dark .hud>div{background:#202a35}body.dark .analytics{background:#1b222b}body.dark #r3dStage{background:#151b22}body.dark .r3d-hint{background:rgba(24,31,39,.88)}body.dark .toast{background:#202a35;box-shadow:0 8px 24px rgba(0,0,0,.35)}body.dark .operation-panel{background:#202a35;border-color:#43515f}body.dark .op-status-message{background:#141a21;border-color:#2d8e85}.theme-toggle{white-space:nowrap}';document.head.append(themeStyle);const themeButton=document.createElement('button');themeButton.id='themeToggle';themeButton.className='theme-toggle';themeButton.type='button';document.querySelector('header')?.append(themeButton);function setTheme(mode){const dark=mode==='dark';document.body.classList.toggle('dark',dark);themeButton.textContent=dark?'☀ Light mode':'☾ Dark mode';themeButton.setAttribute('aria-label',dark?'Switch to light mode':'Switch to dark mode');localStorage.setItem('airbrakes-theme',dark?'dark':'light')}themeButton.onclick=()=>setTheme(document.body.classList.contains('dark')?'light':'dark');setTheme(localStorage.getItem('airbrakes-theme')||'light');
const battery=document.createElement('article');battery.className='card span4';battery.innerHTML='<div class="title">BATTERY</div><div id="batteryVoltage" style="font-size:32px;font-weight:800;color:var(--cyan)">--.-- V</div><div id="batteryStatus" class="hint">Waiting for live telemetry</div>';document.querySelector('#ops .grid').prepend(battery);
api.on('serial-line',m=>{const match=m.match(/^BATTERY_VOLTAGE:(-?\d+(?:\.\d+)?)$/);if(match){$('#batteryVoltage').textContent=`${Number(match[1]).toFixed(2)} V`;$('#batteryStatus').textContent=`Live - updated ${new Date().toLocaleTimeString()}`;dashboard.updateBattery(match[1])}const stateMatch=m.match(/^STATE:\s*(\w+)/i);if(stateMatch){dashboard.updateState(stateMatch[1])}if(/error|ERROR/i.test(m)){dashboard.addEvent(m,'error')}else if(/warning|WARNING/i.test(m)){dashboard.addEvent(m,'warning')}});
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-view],.view').forEach(x=>x.classList.remove('active'));b.classList.add('active');$(`#${b.dataset.view}`).classList.add('active')});document.querySelectorAll('[data-config]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-config],.config-page').forEach(x=>x.classList.remove('active'));b.classList.add('active');$(`#${b.dataset.config}`).classList.add('active')});
async function refresh(){const p=await api.ports(),box=$('#ports');box.innerHTML='';p.forEach(v=>box.add(new Option(v.label,v.path)));if(!p.length)box.add(new Option('No serial ports found',''));toast(p.length?`${p.length} serial port(s) found`:'No serial ports found',!p.length)}function connected(info,device=''){ $('#conn').textContent='● CONNECTED';$('#conn').classList.add('online');$('#storage').textContent=`${device?'Connected to '+device+'. ':''}Storage: ${info}`}
$('#refresh').onclick=()=>run('Refreshing serial ports',refresh);$('#connect').onclick=async()=>{const p=$('#ports').value;if(!p)return toast('Choose a serial port first',true);connected(await run('Connecting',()=>api.connect(p)),p)};$('#auto').onclick=async()=>{const r=await run('Auto-connecting',api.autoConnect);connected(r.info,r.path);await refresh()};$('#disconnect').onclick=async()=>{await api.disconnect();$('#conn').textContent='● OFFLINE';$('#conn').classList.remove('online');$('#storage').textContent='Disconnected.';toast('Disconnected')};document.querySelectorAll('[data-cmd]').forEach(b=>b.onclick=()=>run(b.textContent,()=>api.command(b.dataset.cmd)));$('#arm').onclick=()=>run('Arming ground test',()=>api.command('GROUND_TEST START'));$('#abort').onclick=()=>run('Aborting ground test',()=>api.command('GROUND_TEST ABORT'));$('#build').onclick=()=>run('Building firmware',api.build,['Compiling','Linking','Verifying']);$('#flash').onclick=()=>run('Flashing firmware',api.flash,['Erasing','Writing','Verifying']);$('#generate').onclick=()=>run('Regenerating coast table',api.generateCoast);
async function config(){const r=await api.readDefines(),shell=$('#fields');shell.innerHTML='';r.values.forEach(v=>{const e=document.createElement('div');e.className='field';e.innerHTML=`<label>${v.name}</label><small>${v.comment||'Configuration value'}</small><input data-name="${v.name}" value="${v.value}">`;shell.append(e)})}$('#reloadConfig').onclick=()=>run('Loading config.h',config);$('#saveConfig').onclick=()=>run('Saving config.h',()=>api.saveDefines([...document.querySelectorAll('#fields input')].map(x=>({name:x.dataset.name,value:x.value}))));api.on('serial-line',m=>{const x=$('#serial');const line=formatSerialLine(m);x.appendChild(line);if(x.children.length>100)x.removeChild(x.firstChild);x.scrollTop=x.scrollHeight});api.on('pio-log',log);api.on('download-progress',p=>{opUI.updateProgress(p.received,p.expected);opUI.setMessage(`${p.received}/${p.expected} bytes`);dashboard.lastUpdateTime=Date.now()});refresh().catch(()=>{});config().catch(e=>toast(e.message,true));
async function listFlights(){flights=await run('Listing device flights',api.listFlights);const shell=$('#flightList');shell.innerHTML=flights.length?'':'No saved flights on the board.';flights.forEach(f=>{const row=document.createElement('div');row.className='flight';row.innerHTML=`<span>${f.label}</span><span><button>Download</button> <button class="danger">Delete</button></span>`;row.querySelector('button').onclick=()=>run(`Downloading flight ${f.num}`,()=>api.download(f.num),['Transferring','Saving','Complete']).then(r=>toast(`${r.records} records saved`));row.querySelector('.danger').onclick=()=>confirm(`Delete flight ${f.num} from the board?`)&&run(`Deleting flight ${f.num}`,()=>api.deleteFlight(f.num)).then(listFlights);shell.append(row)})}$('#listFlights').onclick=listFlights;$('#downloadAll').onclick=async()=>{if(!flights.length)await listFlights();for(const f of flights)if(!f.active)await run(`Downloading flight ${f.num}`,()=>api.download(f.num),['Transferring','Saving']);toast('All non-active flights downloaded')};$('#openData').onclick=()=>run('Opening flight folder',api.openData);
// Safety strip and local-log management are intentionally separate from the
// on-board flight list: a ground test is never presented as a flight.
api.on('connection-state',state=>{if(state.connected) connected(state.info,state.device);else {$('#conn').textContent='● OFFLINE';$('#conn').classList.remove('online');$('#storage').textContent='Board disconnected. Searching automatically...';$('#batteryVoltage').textContent='--.-- V';$('#batteryStatus').textContent='Waiting for live telemetry'}});
const local=document.createElement('section');local.className='card';local.innerHTML='<div class="title">LOCAL LOGS</div><div class="actions"><button id="localFlights">Flights</button><button id="localGround">Ground tests</button></div><div id="localList" class="status">Choose a category to manage local logs.</div>';document.querySelector('#analytics').insertBefore(local,document.querySelector('.analytics-embedded'));
api.autoConnect().then(r=>{if(r.path)connected(r.info,r.path)}).catch(()=>{});
async function showLocal(category){const entries=await api.localEntries(category);const shell=$('#localList');shell.innerHTML=entries.length?'':`No saved ${category.replace('_',' ')}.`;entries.forEach(e=>{const row=document.createElement('div');row.className='flight';row.innerHTML=`<span>${e.folder} · ${e.num_records||0} records</span><button class="danger">Delete locally</button>`;row.querySelector('button').onclick=async()=>{if(confirm(`Permanently delete local ${e.folder}?`)){await api.localDelete(category,e.folder);showLocal(category)}};shell.append(row)})}$('#localFlights').onclick=()=>showLocal('flights');$('#localGround').onclick=()=>showLocal('ground_tests');
