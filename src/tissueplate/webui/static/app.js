// @ts-check
// Local web UI of the parking plate generator (webui design 3.3). Every API call carries the per-launch token in a
// header; the token comes from the URL fragment (never sent to a server) and is then removed from the address bar.
// The numbers and texts stay in this page's memory: no localStorage, no IndexedDB.

const TOKEN = readToken();
const DEBOUNCE_MS = 300;
const POLL_MS = 1000;
const STAGE_TITLES = ['', '读配置、建模', '几何验证', '导出 STL / STEP', '检查 ①–⑩', '出盘和 Bambu 命令行切片', '渲染和装配卡', '报告'];
// seconds from the start when each stage began (Mac, webui design 4.4), for the progress bar
const STAGE_START = [0, 0, 10, 54, 58, 160, 197, 201, 203];
const STATE_TITLES = {
  queued: '排队', running: '构建中', ok: '完成', unsliced: '完成（没切片）', failed: '检查没过', config_error: '配置错误',
  crashed: '内部错误', cancelled: '已取消', interrupted: '已中断',
};
const DONE_STATES = ['ok', 'unsliced'];
const EXAMPLE_NUMBERS = { a: '13800138000', b: '13900139000' };

/** @typedef {{key: string, name: string, title: string, help: string, unit: string, kind: string, default: any,
 *   readonly: boolean, min?: number, max?: number, step?: number, choices?: {value: any, title: string}[]}} KeyRow */
/** @typedef {{name: string, title: string, help: string, keys: KeyRow[]}} Section */
/** @typedef {{field: string|null, level: string, text: string, blocks_save?: boolean}} Message */

/** @type {{sections: Section[], mount_presets: {id: string, title: string, values: Object<string, number>}[],
 *   font_url: string}|null} */
let schema = null;
/** @type {any} */
let status = null;
let configSha = /** @type {string|null} */ (null);
let saveBlocked = false;
/** @type {any} */
let currentJob = null;
let logNext = 0;
let pollTimer = 0;
let loadingTimer = 0;
let serverStopped = false;
/** @type {Object<string, number>} */
const timers = {};
/** Read-in values a number box cannot show (a TOML date, "13,62"): sent as they are until the box is edited, so the
 * checks keep flagging them instead of the default quietly taking their place. @type {Object<string, any>} */
const unshown = {};
/** @type {Object<string, {errors: string[], checked: boolean}>} */
const faceResults = {};
/** @type {Object<string, string>} */
const lastPreview = {};
let validation = { ok: false };

// ---------------------------------------------------------------- helpers
function readToken() {
  const match = location.hash.match(/token=([A-Za-z0-9_-]+)/);
  if (match) {
    sessionStorage.setItem('plate-token', match[1]);
    history.replaceState(null, '', location.pathname);
  }
  return sessionStorage.getItem('plate-token');
}

/** @param {string} id @returns {any} */
function byId(id) {
  return document.getElementById(id);
}

/**
 * @param {string} tag
 * @param {Object<string, string>} attributes
 * @param {(Node|string)[]} children
 */
function element(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === 'text') node.textContent = value;
    else if (name === 'class') node.className = value;
    else node.setAttribute(name, value);
  }
  node.append(...children);
  return node;
}

/** @param {string} path @param {any} [body] */
async function api(path, body) {
  /** @type {RequestInit} */
  const options = { method: body === undefined ? 'GET' : 'POST', headers: { 'X-Plate-Token': TOKEN || '' }, cache: 'no-store' };
  if (body !== undefined) {
    options.headers = { ...options.headers, 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  return fetch(path, options);
}

/** @param {Response} response */
async function json(response) {
  try {
    return await response.json();
  } catch {
    return { error: `服务器返回 ${response.status}` };
  }
}

/** @param {string} name @param {() => void} action */
function debounce(name, action) {
  clearTimeout(timers[name]);
  timers[name] = setTimeout(action, DEBOUNCE_MS);
}

/** @param {number} bytes */
function sizeText(bytes) {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** An in-page confirmation (no browser dialog). @param {string} text @returns {Promise<boolean>} */
function confirmAction(text) {
  const dialog = byId('confirm');
  byId('confirm-text').textContent = text;
  return new Promise((resolve) => {
    /** @param {boolean} answer */
    const finish = (answer) => {
      dialog.close();
      resolve(answer);
    };
    byId('confirm-yes').onclick = () => finish(true);
    byId('confirm-no').onclick = () => finish(false);
    dialog.showModal();
  });
}

/** @param {string} path @param {string} fallbackName @param {any} [body] */
async function download(path, fallbackName, body) {
  const response = await api(path, body);
  if (!response.ok) {
    showGeneral([{ field: null, level: 'error', text: (await json(response)).error || `下载失败（${response.status}）` }]);
    return;
  }
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  const url = URL.createObjectURL(await response.blob());
  const link = element('a', { href: url, download: match ? decodeURIComponent(match[1]) : fallbackName });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

// ---------------------------------------------------------------- form
/** @param {string} name */
function fieldId(name) {
  return `field-${name.replace('.', '-')}`;
}

/** @param {KeyRow} row */
function inputFor(row) {
  if (row.choices) {
    const select = element('select', { id: fieldId(row.name) });
    for (const choice of row.choices) select.append(element('option', { value: String(choice.value), text: choice.title }));
    return select;
  }
  return element('input', { id: fieldId(row.name), type: 'number', step: String(row.step), min: String(row.min),
    max: String(row.max), inputmode: 'decimal' });
}

/** @param {KeyRow} row */
function keyRow(row) {
  const input = inputFor(row);
  input.disabled = row.readonly;
  input.addEventListener('input', () => {
    delete unshown[row.name];                  // what the user types replaces a value the box could not show
    onChange();
  });
  const range = row.kind === 'float' ? `${row.min}–${row.max}${row.unit ? ` ${row.unit}` : ''}` : '';
  const reset = element('button', { type: 'button', class: 'link', title: `恢复默认 ${row.default}`, text: '↺' });
  reset.addEventListener('click', () => {
    setValue(row, row.default);
    onChange();
  });
  const line = element('div', { class: 'row', id: `row-${row.name.replace('.', '-')}` }, [
    element('label', { for: input.id, text: row.title }), input,
    element('span', { class: 'range' }, [range, row.readonly ? '' : reset]),
  ]);
  if (row.help) line.append(element('span', { class: 'help', text: row.help }));
  line.append(element('span', { class: 'field-message' }));
  return line;
}

function mountPresets() {
  const select = element('select', { id: 'mount-preset' });
  for (const preset of schema?.mount_presets || []) select.append(element('option', { value: preset.id, text: preset.title }));
  select.append(element('option', { value: 'custom', text: '自定义' }));
  select.addEventListener('input', () => {
    const preset = schema?.mount_presets.find((item) => item.id === select.value);
    if (preset) for (const [key, value] of Object.entries(preset.values)) setValue(rowOf(`mount.${key}`), value);
    lockMount();
    onChange();
  });
  return element('div', { class: 'row' }, [element('label', { for: 'mount-preset', text: '垫厚预设' }), select,
    element('span', { class: 'help', text: '这两档打出来的零件相同，只是装配卡和报告里写的胶厚不同。三项要一起改；不提供"不贴胶"。' })]);
}

function buildForm() {
  const form = byId('form');
  form.textContent = '';
  for (const section of schema?.sections || []) {
    const box = element('details', { class: 'section', id: `section-${section.name}` },
      [element('summary', { text: section.title })]);
    if (section.name === 'display' || section.name === 'fit') box.setAttribute('open', '');
    if (section.help) box.append(element('p', { class: 'help', text: section.help }));
    if (section.name === 'mount') box.append(mountPresets());
    for (const row of section.keys) {
      if (row.name !== 'display.logo') box.append(keyRow(row));
    }
    form.append(box);
  }
}

/** @param {string} name @returns {KeyRow} */
function rowOf(name) {
  for (const section of schema?.sections || []) {
    const row = section.keys.find((item) => item.name === name);
    if (row) return row;
  }
  throw new Error(`no key ${name}`);
}

/** @param {KeyRow} row @param {any} value */
function setValue(row, value) {
  if (row.name === 'display.logo') {
    for (const radio of document.querySelectorAll('input[name="logo"]')) {
      /** @type {HTMLInputElement} */ (radio).checked = /** @type {HTMLInputElement} */ (radio).value === (value === 'none' ? 'none' : 'final');
    }
    return;
  }
  const input = byId(fieldId(row.name));
  input.value = value === null || value === undefined ? '' : String(value);
  if (row.kind !== 'str' && input.value === '' && value !== null && value !== undefined) unshown[row.name] = value;
  else delete unshown[row.name];
}

/** @param {KeyRow} row */
function readValue(row) {
  if (row.name === 'display.logo') {
    const picked = /** @type {HTMLInputElement|null} */ (document.querySelector('input[name="logo"]:checked'));
    return picked ? picked.value : 'final';
  }
  const raw = byId(fieldId(row.name)).value.trim();
  if (row.kind === 'str') return raw;
  if (raw === '') return row.name in unshown ? unshown[row.name] : null;
  return row.kind === 'int' ? Number.parseInt(raw, 10) : Number.parseFloat(raw);
}

/** @param {string} key */
function faceMode(key) {
  const picked = /** @type {HTMLInputElement|null} */ (document.querySelector(`input[name="mode-${key}"]:checked`));
  return picked ? picked.value : 'number';
}

/** The config.toml layout of the form (faces left out while empty). */
function currentState() {
  /** @type {Object<string, Object<string, any>>} */
  const state = { numbers: {}, text: {} };
  for (const key of ['a', 'b']) {
    const value = byId(`face-${key}`).value;
    if (value.trim() !== '') state[faceMode(key) === 'number' ? 'numbers' : 'text'][key] = faceMode(key) === 'number' ? value.trim() : value;
  }
  const line = byId('face-l').value;
  if (line.trim() !== '') state.text.l = line;
  for (const section of schema?.sections || []) {
    state[section.name] = {};
    for (const row of section.keys) {
      const value = readValue(row);
      if (value !== null) state[section.name][row.key] = value;
    }
  }
  return state;
}

/** @param {any} state */
function fillForm(state) {
  for (const key of ['a', 'b']) {
    const isText = state.text && key in state.text;
    const value = isText ? state.text[key] : (state.numbers || {})[key];
    for (const radio of document.querySelectorAll(`input[name="mode-${key}"]`)) {
      /** @type {HTMLInputElement} */ (radio).checked = /** @type {HTMLInputElement} */ (radio).value === (isText ? 'text' : 'number');
    }
    byId(`face-${key}`).value = value ?? '';
  }
  byId('face-l').value = (state.text || {}).l ?? '';
  fillSettings(state);
}

/** @param {any} state */
function fillSettings(state) {
  for (const section of schema?.sections || []) {
    for (const row of section.keys) {
      const table = state[section.name] || {};
      setValue(row, row.key in table ? table[row.key] : row.default);
    }
  }
  pickMountPreset();
}

function pickMountPreset() {
  const values = Object.fromEntries(['pad_t', 'delta_up', 'tab_bottom'].map((key) => [key, readValue(rowOf(`mount.${key}`))]));
  const preset = schema?.mount_presets.find((item) => Object.entries(item.values).every(([key, value]) => values[key] === value));
  byId('mount-preset').value = preset ? preset.id : 'custom';
  lockMount();
}

function lockMount() {
  const custom = byId('mount-preset').value === 'custom';
  for (const key of ['pad_t', 'delta_up', 'tab_bottom']) byId(fieldId(`mount.${key}`)).disabled = !custom;
}

function onChange() {
  debounce('check', () => {
    validate();
    refreshPreviews();
  });
}

// ---------------------------------------------------------------- messages
/** @param {Message[]} messages */
function showGeneral(messages) {
  const box = byId('messages');
  box.textContent = '';
  for (const message of messages) box.append(element('p', { class: message.level, text: message.text }));
}

/** @param {Message[]} messages */
function showMessages(messages) {
  for (const line of document.querySelectorAll('.row, .face-row')) {
    line.classList.remove('error', 'warning');
    const slot = line.querySelector('.field-message');
    if (slot) slot.textContent = '';
  }
  const general = [];
  for (const message of messages) {
    const name = message.field || '';
    const faceKey = /^(numbers|text|face)\.([abl])$/.exec(name);
    const line = faceKey ? document.querySelector(`.face-row[data-face="${faceKey[2].toLowerCase()}"]`)
      : name ? byId(`row-${name.replace('.', '-')}`) : null;
    if (line) {
      line.classList.add(message.level === 'error' ? 'error' : 'warning');
      const slot = line.querySelector('.field-message');
      if (slot) slot.textContent = [slot.textContent, message.text].filter(Boolean).join('；');
    } else {
      general.push(message);
    }
  }
  showGeneral(general);
}

async function validate() {
  const response = await api('/api/validate', { state: currentState() });
  const result = await json(response);
  validation = response.ok ? result : { ok: false };
  showMessages(result.messages || [{ field: null, level: 'error', text: result.error || `校验失败（${response.status}）` }]);
  updateBuildButton();
}

// ---------------------------------------------------------------- previews
/** @param {string} face @param {any} state */
function previewRequest(face, state) {
  const key = face.toLowerCase();
  if (face === 'L') return { display: state.display, text: 'l' in state.text ? { l: state.text.l } : {} };
  const request = { display: state.display, numbers: {}, text: {} };
  if (key in state.numbers) request.numbers[key] = state.numbers[key];
  if (key in state.text) request.text[key] = state.text[key];
  return request;
}

async function refreshPreviews() {
  const state = currentState();
  await Promise.all(['A', 'B', 'L'].map((face) => refreshPreview(face, previewRequest(face, state))));
  updateBuildButton();
}

/** Layout first (milliseconds), then the full check (seconds for a long text). @param {string} face @param {any} request */
async function refreshPreview(face, request) {
  const signature = JSON.stringify(request);
  if (lastPreview[face] === signature) return;
  lastPreview[face] = signature;
  faceResults[face] = { errors: [], checked: false };
  for (const step of ['layout', 'full']) {
    const response = await api('/api/preview', { face, state: request, step });
    if (lastPreview[face] !== signature) return;           // the input changed meanwhile
    const result = await json(response);
    showPreview(face, response.ok ? result : { errors: result.errors || [result.error || '预览失败'], checked: true });
    if (!response.ok || result.checked) break;
  }
}

/** @param {string} face @param {any} result */
function showPreview(face, result) {
  const box = document.querySelector(`.preview[data-face="${face}"]`);
  if (!box) return;
  faceResults[face] = { errors: result.errors || [], checked: Boolean(result.checked) };
  if (result.svg) {
    const holder = box.querySelector('.preview-image');
    const old = holder.querySelector('img');
    const image = element('img', { alt: `${face} 面预览` });
    image.src = URL.createObjectURL(new Blob([result.svg], { type: 'image/svg+xml' }));
    image.onload = () => {
      if (old) {
        URL.revokeObjectURL(old.src);
        old.remove();
      }
    };
    holder.append(image);
  }
  const facts = box.querySelector('.facts');
  facts.textContent = '';
  const summary = [result.summary, result.ms !== undefined ? `${result.ms} ms` : '', result.checked ? '' : '检查中…'];
  facts.append(element('span', { text: summary.filter(Boolean).join(' · ') }));
  for (const text of result.errors || []) facts.append(element('span', { class: 'error', text }));
  for (const text of result.warnings || []) facts.append(element('span', { class: 'warning', text }));
}

// ---------------------------------------------------------------- build
function facesFilled() {
  return ['a', 'b'].every((key) => byId(`face-${key}`).value.trim() !== '');
}

function updateBuildButton() {
  const running = currentJob && ['queued', 'running'].includes(currentJob.state);
  const faceErrors = Object.values(faceResults).some((result) => result.errors.length > 0);
  const checking = Object.values(faceResults).some((result) => !result.checked);
  let hint = '';
  if (!status?.font?.present) hint = '先放好字体';
  else if (!facesFilled()) hint = 'A、B 两面都填了才能构建';
  else if (faceErrors) hint = '有一面打不出来，先改好';
  else if (checking) hint = '还在检查文字…';
  else if (!validation.ok) hint = '配置有错，先改好';
  byId('build').disabled = Boolean(running) || hint !== '';
  byId('build-hint').textContent = running ? '' : hint;
}

async function startBuild() {
  byId('build').disabled = true;
  const response = await api('/api/build', { state: currentState() });
  const result = await json(response);
  if (!response.ok) {
    if (result.messages) showMessages(result.messages);
    else showGeneral([{ field: null, level: 'error', text: result.error || `构建没有开始（${response.status}）` }]);
    updateBuildButton();
    return;
  }
  openJob(result.job.id);
}

/** @param {string} jobId */
function openJob(jobId) {
  currentJob = { id: jobId, state: 'queued' };
  logNext = 0;
  byId('log').textContent = '';
  byId('outputs').textContent = '…';
  byId('renders').textContent = '';
  byId('viewer').classList.add('hidden');
  byId('job-name').textContent = jobId;
  clearTimeout(pollTimer);
  poll();
}

/** @param {any} job */
function progressOf(job) {
  if (!['queued', 'running'].includes(job.state)) return 100;
  const stage = job.stage || 0;
  // within the current stage's span: a slower computer waits at its end instead of running ahead
  const seconds = Math.min(Math.max(job.elapsed || 0, STAGE_START[stage]), STAGE_START[stage + 1] ?? STAGE_START[stage]);
  return Math.min(97, (seconds / STAGE_START[STAGE_START.length - 1]) * 100);
}

async function poll() {
  const response = await api(`/api/jobs/${currentJob.id}?since=${logNext}`);
  if (!response.ok) return;
  const result = await json(response);
  currentJob = result.job;
  logNext = result.next;
  const log = byId('log');
  for (const [seconds, text] of result.lines) log.append(`${seconds === null ? '' : `[${seconds}s] `}${text}\n`);
  log.scrollTop = log.scrollHeight;
  byId('bar').style.width = `${progressOf(currentJob)}%`;
  const stage = currentJob.stage ? `第 ${currentJob.stage}/7 步 · ${STAGE_TITLES[currentJob.stage]}` : '准备';
  byId('stage').textContent = `${STATE_TITLES[currentJob.state] || currentJob.state} · ${stage} · ${currentJob.elapsed ?? 0} s`;
  const running = ['queued', 'running'].includes(currentJob.state);
  byId('cancel').disabled = !running;
  updateBuildButton();
  if (running) {
    pollTimer = setTimeout(poll, POLL_MS);
  } else {
    loadOutputs();
    loadJobs();
  }
}

async function cancelBuild() {
  if (currentJob) await api(`/api/jobs/${currentJob.id}/cancel`, {});
}

// ---------------------------------------------------------------- outputs
/** @param {string} text @param {() => void} action @param {string} [className] */
function button(text, action, className = '') {
  const node = element('button', { type: 'button', text, class: className });
  node.addEventListener('click', action);
  return node;
}

/** @param {any} file @param {string} action */
async function openOutput(file, action) {
  const response = await api('/api/open', { job: currentJob.id, path: file.path, action });
  const result = await json(response);
  if (!response.ok) showGeneral([{ field: null, level: 'error', text: result.error || '打不开' }]);
  else if (!result.opened && result.path) showGeneral([{ field: null, level: 'warning', text: `这台电脑打不开文件管理器，文件在：${result.path}` }]);
}

/** @param {any} file */
async function viewText(file) {
  const response = await api(`/api/jobs/${currentJob.id}/file?path=${encodeURIComponent(file.path)}`);
  const viewer = byId('viewer');
  viewer.textContent = response.ok ? await response.text() : `打不开（${response.status}）`;
  viewer.classList.remove('hidden');
  viewer.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/** @param {any} file */
function fileDownload(file) {
  download(`/api/jobs/${currentJob.id}/file?path=${encodeURIComponent(file.path)}`, file.path.split('/').pop());
}

function fitChanged() {
  return (schema?.sections.find((section) => section.name === 'fit')?.keys || []).some((row) => readValue(row) !== row.default);
}

async function loadOutputs() {
  const response = await api(`/api/jobs/${currentJob.id}/files`);
  const result = await json(response);
  const box = byId('outputs');
  box.textContent = '';
  box.classList.remove('muted');
  /** @type {any[]} */
  const files = result.files || [];
  /** @param {string} group */
  const first = (group) => files.find((file) => file.group === group);
  const project = first('3mf');
  const card = first('card');
  const primary = element('div', { class: 'toolbar' });
  if (project && status?.bambu?.found) primary.append(button('用 Bambu Studio 打开', () => openOutput(project, 'bambu'), 'primary'));
  if (project || card) primary.append(button(status?.platform?.reveal_label || '在文件夹中显示', () => openOutput(project || card, 'reveal')));
  if (card) primary.append(button('查看装配卡', () => viewText(card)));
  const report = files.find((file) => file.path === 'report.md');
  if (report) primary.append(button('查看报告', () => viewText(report)));
  box.append(primary);
  if (currentJob.state === 'unsliced') {
    box.append(element('p', { class: 'warning', text: '没切片（没找到或起不来 Bambu Studio）：没有 3MF；装配卡 §1 末尾列出了每件要在切片软件里手动设的项。' }));
  } else if (!DONE_STATES.includes(currentJob.state)) {
    box.append(element('p', { class: 'error', text: `${STATE_TITLES[currentJob.state] || currentJob.state}：看日志和报告。` }));
  }
  if (DONE_STATES.includes(currentJob.state) && fitChanged()) {
    box.append(element('p', { class: 'warning', text: '改了「配合」的键：只重打改过的那一件，在 Bambu Studio 里删掉同盘别的对象；'
      + '小件（K、EN、EF、P、盖片 D、垫片 S）别单独打：按装配卡 §1-5 移到陪打柱 Q 那一盘，和 Q 一起打。' }));
  }
  box.append(element('p', { class: 'muted', text: '只用打印机的「仅局域网（LAN only）」模式或 SD 卡打印：云模式会把带号码的文件传到拓竹云。' }));
  const downloads = element('details', { class: 'downloads' }, [element('summary', { text: '下载…（会在下载文件夹里多一份带号码的副本，用完删掉）' })]);
  for (const group of result.groups || []) {
    const inGroup = files.filter((file) => file.group === group.group);
    if (!inGroup.length) continue;
    const total = inGroup.reduce((sum, file) => sum + file.size, 0);
    const action = inGroup.length === 1 ? () => fileDownload(inGroup[0])
      : () => download(`/api/jobs/${currentJob.id}/zip?groups=${group.group}`, `${group.group}.zip`);
    downloads.append(element('div', { class: 'group' }, [element('span', { text: `${group.label} · ${inGroup.length} 个 · ${sizeText(total)}` }),
      button('下载', action)]));
  }
  downloads.append(element('div', { class: 'group' }, [button('全部打包（不含 config.toml、G-code 和日志）',
    () => download(`/api/jobs/${currentJob.id}/zip?groups=${result.default_zip.join(',')}`, 'all.zip'))]));
  box.append(downloads);
  const renders = files.filter((file) => file.group === 'renders');
  if (DONE_STATES.includes(currentJob.state) && !renders.length) {
    box.append(element('p', { class: 'warning', text: '这台电脑没出渲染图（渲染失败，构建照常完成）：原因见报告。' }));
  }
  showRenders(renders);
}

/** @param {any[]} files */
async function showRenders(files) {
  const box = byId('renders');
  box.textContent = '';
  for (const file of files) {
    const response = await api(`/api/jobs/${currentJob.id}/file?path=${encodeURIComponent(file.path)}`);
    if (!response.ok) continue;
    const image = element('img', { alt: file.path });
    image.src = URL.createObjectURL(await response.blob());
    image.addEventListener('click', () => image.classList.toggle('large'));
    box.append(element('figure', {}, [image, element('figcaption', { text: file.path.split('/').pop() })]));
  }
}

async function loadJobs() {
  const response = await api('/api/jobs');
  if (!response.ok) return;
  const result = await json(response);
  const list = byId('jobs');
  list.textContent = '';
  for (const job of result.jobs) {
    const remove = button('删除', async () => {
      if (!(await confirmAction('删除这次构建的全部文件（含 config.toml 和带号码的产物）？'))) return;
      await api(`/api/jobs/${job.id}/delete`, {});
      loadJobs();
    });
    remove.disabled = ['queued', 'running'].includes(job.state);
    list.append(element('li', {}, [element('span', { text: job.id }),
      element('span', { class: `state-${job.state}`, text: STATE_TITLES[job.state] || job.state }),
      element('span', { class: 'muted', text: job.elapsed ? `${Math.round(job.elapsed)} s` : '' }),
      button('打开', () => openJob(job.id)), remove]));
  }
}

// ---------------------------------------------------------------- config.toml
/** @param {any} result @param {string} source */
function applyConfig(result, source) {
  if (result.state) fillForm(result.state);
  saveBlocked = (result.messages || []).some((/** @type {Message} */ message) => message.blocks_save);
  byId('config-save').disabled = saveBlocked || status?.example;
  showMessages(result.messages || []);
  if (result.state) showGeneral([{ field: null, level: 'note', text: `已读入 ${source}` }, ...(result.messages || []).filter((/** @type {Message} */ m) => !m.field)]);
  for (const face of ['A', 'B', 'L']) delete lastPreview[face];
  validate();
  refreshPreviews();
}

async function readConfig() {
  const response = await api('/api/config');
  const result = await json(response);
  if (!response.ok) {
    showGeneral([{ field: null, level: 'error', text: result.error || `读不了（${response.status}）` }]);
    return;
  }
  configSha = result.sha256;
  applyConfig(result, result.source);
}

async function saveConfig() {
  const state = currentState();
  const empty = ['a', 'b'].some((key) => !(key in state.numbers) && !(key in state.text));
  const example = ['a', 'b'].some((key) => state.numbers[key] === EXAMPLE_NUMBERS[key]);
  if ((empty || example) && !(await confirmAction(empty ? 'A、B 面还有没填的，照样保存？' : '填的是示例号码，照样保存？'))) return;
  let response = await api('/api/config', { state, sha256: configSha });
  if (response.status === 428) {
    if (!(await confirmAction('会用页面上的内容覆盖现有的 config.toml，原文件留在备份里。覆盖？'))) return;
    response = await api('/api/config', { state, sha256: null, overwrite: true });
  }
  const result = await json(response);
  if (!response.ok) {
    showGeneral([{ field: null, level: 'error', text: result.error || `保存失败（${response.status}）` }]);
    return;
  }
  configSha = result.sha256;
  showGeneral([{ field: null, level: 'note', text: '已保存到 config.toml（旧文件在 config.toml.*.bak）' }]);
}

/** @param {Event} event */
async function importConfig(event) {
  const input = /** @type {HTMLInputElement} */ (event.target);
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  const response = await api('/api/config/import', { toml: await file.text() });
  const result = await json(response);
  if (!response.ok) {
    showGeneral([{ field: null, level: 'error', text: result.error || `读入失败（${response.status}）` }]);
    return;
  }
  if (!result.state) {                         // not TOML: the form, its sha256 and the save block stay as they were
    showGeneral(result.messages || []);
    return;
  }
  configSha = null;                           // a saved import overwrites config.toml only after a confirmation
  applyConfig(result, file.name);
}

// ---------------------------------------------------------------- status
async function loadStatus(refresh = false) {
  const response = await api(`/api/status${refresh ? '?refresh=1' : ''}`);
  if (!response.ok) {
    const banner = byId('token-missing');
    if (response.status !== 403) {           // 503: the build pipeline did not load (the terminal shows why)
      banner.textContent = `服务器没准备好：${(await json(response)).error}。看启动它的终端窗口里的报错。`;
    }
    banner.classList.remove('hidden');
    return false;
  }
  status = await response.json();
  const bambu = byId('badge-bambu');
  bambu.textContent = status.bambu.found ? `Bambu Studio ${status.bambu.version || ''} ${status.bambu.version_ok ? '✓' : '（版本不同）'}`
    : '没有能用的 Bambu Studio：不出 3MF';
  bambu.title = status.bambu.found ? (status.bambu.version_ok ? '' : `预设按 ${status.bambu.expected} 写，别的版本可能找不到预设`) : status.bambu.reason;
  bambu.className = `badge ${status.bambu.found && status.bambu.version_ok ? 'ok' : 'warn'}`;
  const font = byId('badge-font');
  font.textContent = status.font.present ? '字体 ✓' : '缺字体';
  font.className = `badge ${status.font.present ? 'ok' : 'bad'}`;
  byId('font-missing').classList.toggle('hidden', status.font.present);
  byId('font-other').classList.toggle('hidden', !status.font.present || status.font.authors);
  byId('font-url').textContent = status.font.url;
  byId('badge-example').classList.toggle('hidden', !status.example);
  byId('config-read').textContent = status.example ? '读取示例配置' : '从 config.toml 读取';
  byId('config-read').disabled = !status.example && !status.config_exists;
  byId('config-save').disabled = status.example || saveBlocked;
  byId('history-rule').textContent = `只留最近 ${status.keep} 次，每次约 74 MB；里面的文件都带号码`;
  const warning = byId('platform-warning');
  warning.textContent = status.platform.warning || '';
  warning.classList.toggle('hidden', !status.platform.warning);
  return true;
}

async function stopServer() {
  if (!(await confirmAction('停止服务器？正在跑的构建也会停。'))) return;
  let response;
  try {
    response = await api('/api/shutdown', {});
  } catch {                                     // no reply at all: stopped already (Ctrl+C in its terminal)
    showGeneral([{ field: null, level: 'error', text: '连不上服务器：它可能已经停了，看启动它的终端窗口' }]);
    return;
  }
  if (!response.ok) {
    showGeneral([{ field: null, level: 'error', text: `停不了（${(await json(response)).error}）：在启动它的终端窗口里按 Ctrl+C` }]);
    return;
  }
  serverStopped = true;
  clearTimeout(loadingTimer);
  byId('platform-warning').classList.add('hidden');
  byId('stopped').classList.remove('hidden');
  for (const node of document.querySelectorAll('button, input, select')) /** @type {HTMLInputElement} */ (node).disabled = true;
}

async function init() {
  byId('notice-hide').addEventListener('click', () => byId('notice').classList.add('hidden'));
  byId('stop').addEventListener('click', stopServer);           // also while the pipeline loads or failed to load
  // a new .venv imports for 1-2 minutes before the first reply: say so instead of a page that seems stuck
  loadingTimer = setTimeout(() => {
    byId('platform-warning').textContent = '正在加载构建程序：新建的环境第一次可能要 1–2 分钟，加载完页面会自己继续。';
    byId('platform-warning').classList.remove('hidden');
  }, 3000);
  let ready = false;
  try {
    ready = Boolean(TOKEN) && (await loadStatus());
  } catch {                                     // no reply: the server stopped, or the browser gave up waiting
    byId('token-missing').textContent = '连不上服务器：看启动它的终端窗口还在不在运行，等它打出"构建程序已加载"再刷新本页。';
  }
  clearTimeout(loadingTimer);
  if (!ready) {
    byId('platform-warning').classList.add('hidden');
    byId('token-missing').classList.toggle('hidden', serverStopped);     // stopped by the button: that banner says it
    return;
  }
  schema = await json(await api('/api/schema'));
  buildForm();
  fillSettings({});
  for (const input of document.querySelectorAll('#faces input')) input.addEventListener('input', onChange);
  byId('config-read').addEventListener('click', readConfig);
  byId('config-save').addEventListener('click', saveConfig);
  byId('import-file').addEventListener('change', importConfig);
  byId('config-export').addEventListener('click', () => download('/api/config/export', 'config.toml', { state: currentState() }));
  byId('defaults').addEventListener('click', () => {
    fillSettings({});
    onChange();
  });
  byId('build').addEventListener('click', startBuild);
  byId('cancel').addEventListener('click', cancelBuild);
  byId('font-folder').addEventListener('click', () => api('/api/fonts/reveal', {}));
  byId('font-recheck').addEventListener('click', async () => {
    await loadStatus(true);
    onChange();
  });
  validate();
  refreshPreviews();
  loadJobs();
  if (status.busy) openJob(status.busy);
}

init();
