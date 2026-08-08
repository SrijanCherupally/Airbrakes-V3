const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { SerialPort } = require('serialport');
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs/promises');
const fss = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const DATA_DIR = path.join(process.env.USERPROFILE || app.getPath('home'), '.airbrakes_ground_station', 'flight_data');
const FIELDS = ['time_ms','altitude_m','velocity_ms','accel_bias_ms2','raw_accel_ms2','vertical_accel_ms2','raw_baro_m','motor_pos','motor_vel','motor_cmd_pos','roll_rad','pitch_rad','yaw_rad','Cd','desired_Cd','motor_current','battery_voltage','state','axis_error'];
const STATES = ['IDLE','PAD','BOOST','CONTROL','DESCENT','LANDED','GROUND_TEST_ARMED','GROUND_TEST_RECORDING'];
let port;

function win() { return BrowserWindow.getAllWindows()[0]; }
function emit(channel, value) { win()?.webContents.send(channel, value); }
function wait(ms) { return new Promise(r => setTimeout(r, ms)); }
function transaction(cmd, done, timeout = 3500) {
  if (!port?.isOpen) return Promise.reject(new Error('Connect to the flight computer first.'));
  return new Promise((resolve, reject) => {
    let buffer = Buffer.alloc(0); let timer;
    const cleanup = () => { clearTimeout(timer); port?.off('data', onData); };
    const finish = (error, value) => { cleanup(); error ? reject(error) : resolve(value); };
    const onData = chunk => {
      buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
      for (;;) { const end = buffer.indexOf(10); if (end < 0) break; const line = buffer.subarray(0, end).toString('utf8').trim(); buffer = buffer.subarray(end + 1); if (!line) continue; emit('serial-line', line); const value = done(line); if (value !== undefined) return finish(null, value); }
    };
    port.on('data', onData); // Listener is registered BEFORE write: fast INFO replies cannot be lost.
    timer = setTimeout(() => finish(new Error(`Timed out waiting for ${cmd} response.`)), timeout);
    port.flush(() => port.write(`${cmd}\n`, error => error && finish(error)));
  });
}
async function command(cmd, prefix, timeout) { return transaction(cmd, line => !prefix || line.startsWith(prefix) ? line : undefined, timeout); }
function takeLine(timeout = 3000) { return new Promise((resolve, reject) => { let text=''; const onData=chunk=>{text+=chunk.toString('utf8');const i=text.indexOf('\n');if(i>=0){clean();resolve(text.slice(0,i).trim())}}; const timer=setTimeout(()=>{clean();reject(new Error('Timed out waiting for flight computer response.'))},timeout); const clean=()=>{clearTimeout(timer);port?.off('data',onData)};port.on('data',onData); }); }
async function closePort() { if (port?.isOpen) await new Promise(r => port.close(r)); port = null; }
async function connectDevice(device) { await closePort(); port = new SerialPort({path:device,baudRate:115200,autoOpen:false}); try { await new Promise((res,rej)=>port.open(e=>e?rej(e):res())); await wait(2100); const info=await command('INFO','FLASH:STORAGE:', 5000); return info.replace('FLASH:STORAGE:','').trim(); } catch (error) { await closePort(); if (error?.code === 'EACCES' || /access denied/i.test(error?.message || '')) throw new Error(`${device} is already in use by another program. Close PlatformIO/VS Code serial monitor, Arduino Serial Monitor, and any prior ground-station window, then retry.`); throw error; } }
function runPio(args) {
  return new Promise((resolve, reject) => {
    // The old app deliberately used Python's module invocation: `pio` is not
    // on PATH on this machine even though PlatformIO itself is installed.
    const child = spawn('py', ['-3', '-m', 'platformio', ...args], { cwd: ROOT, shell: false });
    child.stdout.on('data', x => emit('operation-log', x.toString()));
    child.stderr.on('data', x => emit('operation-log', x.toString()));
    child.on('error', e => reject(new Error(`Could not start PlatformIO. Install it with \`py -3 -m pip install platformio\`. Details: ${e.message}`)));
    child.on('close', code => code === 0 ? resolve('PlatformIO completed successfully.') : reject(new Error(`PlatformIO exited with code ${code}.`)));
  });
}
function generateCoastTable(conditions = {}) {
  return new Promise((resolve, reject) => {
    const env = {...process.env, AIRBRAKES_MASS_KG:String(conditions.mass || '0.608'), AIRBRAKES_TEMP_F:String(conditions.temp || '68'), AIRBRAKES_HUMIDITY_PCT:String(conditions.humidity || '55'), AIRBRAKES_PRESSURE_HPA:String(conditions.pressure || '1015')};
    const child = spawn('py', ['-3', 'sim/generate_coast_table.py'], { cwd: ROOT, shell: false, env });
    child.stdout.on('data', x => emit('operation-log', x.toString())); child.stderr.on('data', x => emit('operation-log', x.toString()));
    child.on('error', e => reject(new Error(`Could not run coast-table generator: ${e.message}`))); child.on('close', code => code === 0 ? resolve('Coast table regenerated.') : reject(new Error(`Coast-table generator exited with code ${code}.`)));
  });
}
async function readDefines() {
  const file = path.join(ROOT, 'include', 'config.h'); const text = await fs.readFile(file, 'utf8');
  return { file, values: [...text.matchAll(/^\s*#define\s+([A-Za-z_]\w*)\s+([^\s/]+)(?:\s*\/\/\s*(.*))?$/gm)].filter(x => !x[1].endsWith('_H')).map(x => ({ name:x[1], value:x[2], comment:x[3] || '' })) };
}
async function saveDefines(values) {
  const file = path.join(ROOT, 'include', 'config.h'); let text = await fs.readFile(file, 'utf8');
  for (const {name, value} of values) { const re = new RegExp(`^(\\s*#define\\s+${name}\\s+)([^\\s/]+)`, 'm'); text = text.replace(re, `$1${String(value).trim()}`); }
  await fs.writeFile(file, text); return file;
}
function csv(records) { return FIELDS.join(',') + '\n' + records.map(r => FIELDS.map(k => r[k] ?? '').join(',')).join('\n'); }
async function localEntries(category) { const root=path.join(DATA_DIR,category); try { const names=await fs.readdir(root); const entries=[]; for(const name of names){try{const meta=JSON.parse(await fs.readFile(path.join(root,name,'metadata.json'),'utf8'));entries.push({...meta,folder:name,path:path.join(root,name)})}catch(_){}} return entries.sort((a,b)=>a.folder.localeCompare(b.folder)); } catch(_) { return []; } }
async function saveFlight(number, records, payload) {
  const category=records.some(r=>r.state>=6)?'ground_tests':'flights'; const prefix=category==='ground_tests'?'ground_test':'flight'; const root=path.join(DATA_DIR,category); const fingerprint=crypto.createHash('sha256').update(payload).digest('hex'); const existing=await localEntries(category); const duplicate=existing.find(x=>x.fingerprint===fingerprint); if(duplicate)return {folder:duplicate.path,duplicate:true,category};
  await fs.mkdir(root,{recursive:true}); const next=Math.max(0,...existing.map(x=>Number((x.folder.match(/_(\d+)$/)||[])[1])||0))+1; const folder=`${prefix}_${String(next).padStart(4,'0')}`; const dir=path.join(root,folder); await fs.mkdir(dir); await fs.writeFile(path.join(dir,'data.csv'),csv(records)); await fs.writeFile(path.join(dir,'metadata.json'),JSON.stringify({flight_num:number,category,fingerprint,num_records:records.length,downloaded_at:new Date().toISOString()},null,2)); return {folder:dir,duplicate:false,category};
}
function decodeRecords(buffer) { if (buffer.length % 76) throw new Error('Corrupt flight payload: length is not a multiple of 76 bytes.'); const rows=[]; for(let o=0;o<buffer.length;o+=76) { let r={time_ms:buffer.readUInt32LE(o)}; for(let i=1;i<FIELDS.length;i++) r[FIELDS[i]]=i < 17 ? buffer.readFloatLE(o+4+(i-1)*4) : buffer.readUInt32LE(o+4+(i-1)*4); r.state_name=STATES[r.state] || `UNKNOWN(${r.state})`; rows.push(r); } return rows; }
async function download(number) {
  if (!port?.isOpen) throw new Error('Connect to the flight computer first.');
  const payload=await new Promise((resolve,reject)=>{let buffer=Buffer.alloc(0),expected=null,timer;const clean=()=>{clearTimeout(timer);port.off('data',on)};const done=(e,v)=>{clean();e?reject(e):resolve(v)};const on=chunk=>{buffer=Buffer.concat([buffer,Buffer.from(chunk)]);if(expected===null){const end=buffer.indexOf(10);if(end<0)return;const header=buffer.subarray(0,end).toString('utf8').trim();emit('serial-line',header);if(header.startsWith('FLASH:ERROR'))return done(new Error(header));if(!header.startsWith('FLASH:DATA_START:'))return done(new Error(`Unexpected GET response: ${header}`));expected=Number(header.split(':').pop());buffer=buffer.subarray(end+1)}if(buffer.length>=expected){const data=buffer.subarray(0,expected);return done(null,data)}emit('download-progress',{received:buffer.length,expected})};port.on('data',on);timer=setTimeout(()=>done(new Error('Flight transfer timed out.')),20000);port.flush(()=>port.write(`GET ${number}\n`,e=>e&&done(e)))});
  const records=decodeRecords(payload); return {...await saveFlight(number,records,payload),records:records.length,bytes:payload.length};
}

app.whenReady().then(() => { const w = new BrowserWindow({width:1440,height:920,minWidth:1080,minHeight:700,backgroundColor:'#08111f',webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false}}); w.loadFile(path.join(__dirname,'renderer.html')); });
ipcMain.handle('ports', async () => (await SerialPort.list()).map(p => ({path:p.path,label:`${p.path} — ${p.manufacturer || p.friendlyName || 'Serial device'}`})));
ipcMain.handle('connect', (_, device) => connectDevice(device));
ipcMain.handle('auto-connect', async () => { const ports = await SerialPort.list(); for (const item of ports) { for (let attempt=1;attempt<=2;attempt++) { try { emit('operation-log',`Auto-connect: trying ${item.path} (attempt ${attempt}/2)`); const info = await connectDevice(item.path); emit('operation-log',`Auto-connect: verified Airbrakes board on ${item.path}`); return {path:item.path, info}; } catch (error) { emit('operation-log',`Auto-connect: ${item.path} did not respond (${error.message})`); await wait(250); } } } throw new Error('No serial device responded to the Airbrakes INFO handshake. See Activity for each attempted port.'); });
ipcMain.handle('disconnect', closePort);
ipcMain.handle('board-command', async (_, cmd) => command(cmd, cmd==='INFO'?'FLASH:STORAGE:':cmd==='BARO STATUS'?'DPS368_DIAG:':cmd.startsWith('GROUND_TEST')?'GROUND_TEST:':undefined));
ipcMain.handle('list-flights', async () => { const out=[]; return transaction('LIST', line => { if(line==='FLASH:END') return out; if(line.startsWith('FLASH:FLIGHT:')) { const s=line.slice(13).trim(), m=s.match(/flight_(\d+)\.bin\s*\(([^)]+)\)/); if(m) out.push({num:Number(m[1]),label:s,active:s.includes('[ACTIVE]')}); } }); });
ipcMain.handle('download', (_, n) => download(n));
ipcMain.handle('delete-flight', (_, n) => command(`DELETE ${n}`,'FLASH:'));
ipcMain.handle('local-entries', (_, category) => localEntries(category));
ipcMain.handle('local-delete', async (_, category, folder) => { if(!/^(flight|ground_test)_\d{4}$/.test(folder)) throw new Error('Invalid local log folder.'); await fs.rm(path.join(DATA_DIR,category,folder),{recursive:true,force:false}); return true; });
ipcMain.handle('build', () => runPio(['run'])); ipcMain.handle('flash', async () => { await closePort(); return runPio(['run','-t','upload']); });
ipcMain.handle('generate-coast', (_, conditions) => generateCoastTable(conditions));
ipcMain.handle('defines-read', readDefines); ipcMain.handle('defines-save', (_, values) => saveDefines(values));
ipcMain.handle('open-data', async () => { await fs.mkdir(DATA_DIR,{recursive:true}); require('electron').shell.openPath(DATA_DIR); return DATA_DIR; });
ipcMain.handle('open-dashboard', () => { const child=new BrowserWindow({width:1500,height:960,webPreferences:{contextIsolation:true}}); child.loadFile(path.join(ROOT,'airbrakesDashboard.html')); });
