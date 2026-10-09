const $ = (id) => document.getElementById(id);
const numberFormat = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });
let selectedCase = null;
let searchTimer = null;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function shortNumber(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const n = Number(value);
  if (Math.abs(n) >= 1_000_000) return `${numberFormat.format(n / 1_000_000)}M`;
  if (Math.abs(n) >= 10_000) return `${numberFormat.format(n / 1_000)}K`;
  return whole.format(n);
}
function fmtDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : new Intl.DateTimeFormat('en-GB', {year:'numeric', month:'short', day:'numeric'}).format(d);
}
function fmtHours(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const hours = Math.max(0, Number(value));
  if (hours >= 48) return `${numberFormat.format(hours / 24)} days`;
  return `${numberFormat.format(hours)} h`;
}
function showError(message) {
  $('loading').classList.remove('hidden');
  $('loading').classList.add('error-toast');
  $('loading').textContent = message;
}

function metricCard(label, value, detail) {
  return `<article class="metric-card"><div class="metric-label">${esc(label)}</div><div class="metric-value">${esc(value)}</div><div class="metric-detail">${esc(detail)}</div></article>`;
}
function renderSummary(data) {
  const s = data.summary;
  const p90 = s.p90_duration_days == null ? '—' : `${numberFormat.format(s.p90_duration_days)} days`;
  $('summary-cards').innerHTML = [
    metricCard('Cases in log', shortNumber(s.case_count), 'unit: application / case'),
    metricCard('Events', shortNumber(s.event_count), 'after lifecycle normalization'),
    metricCard('Recognized completion', shortNumber(s.complete_cases), `${shortNumber(s.censored_cases)} censored cases`),
    metricCard('Median process duration', s.median_duration_days == null ? '—' : `${numberFormat.format(s.median_duration_days)} days`, `90th percentile: ${p90}`),
  ].join('');
  const period = data.data_period_note || '';
  $('source-line').textContent = `${period} ${data.source || ''}`;
  const q = data.quality || {};
  $('quality-note').textContent = `Recognized complete: ${shortNumber(s.complete_cases)} · no recognized ending: ${shortNumber(s.censored_cases)}. Completion uses the last activity in a heuristic terminal list; skipped ${shortNumber(q.events_missing_timestamp || 0)} events without timestamps and ${shortNumber(q.events_missing_activity || 0)} without activity names.`;
  renderMonthly(data.months || []);
  renderBars('activity-chart', data.activities || [], 'activity', 'count', 9);
  renderTransitions(data.transitions || []);
  const outcomeNames = {accepted:'accepted', declined:'declined', cancelled:'cancelled', censored:'no recognized ending', other_terminal:'other terminal'};
  renderBars('outcome-chart', (data.outcomes || []).map(row => ({...row, outcome:outcomeNames[row.outcome] || row.outcome})), 'outcome', 'count', 0);
  renderModel(data.metrics);
}
function renderMonthly(rows) {
  const box = $('volume-chart');
  if (!rows.length) { box.textContent = 'No monthly data available.'; return; }
  const w = 700, h = 210, left = 38, right = 14, top = 15, bottom = 34;
  const max = Math.max(...rows.map(r => r.count), 1);
  const x = i => left + (rows.length < 2 ? (w-left-right)/2 : i * (w-left-right)/(rows.length-1));
  const y = n => top + (max-n)/max*(h-top-bottom);
  const points = rows.map((r,i) => `${x(i)},${y(r.count)}`).join(' ');
  const area = `${x(0)},${h-bottom} ${points} ${x(rows.length-1)},${h-bottom}`;
  const tickIndices = [...new Set([0, Math.floor((rows.length-1)/3), Math.floor(2*(rows.length-1)/3), rows.length-1])];
  const grid = [0, .5, 1].map(frac => {
    const yy = top + frac*(h-top-bottom);
    return `<line x1="${left}" y1="${yy}" x2="${w-right}" y2="${yy}" stroke="#edf1f5"/><text x="${left-8}" y="${yy+3}" text-anchor="end" fill="#9aa5b4" font-size="9">${shortNumber(max*(1-frac))}</text>`;
  }).join('');
  const labels = tickIndices.map(i => `<text x="${x(i)}" y="${h-8}" text-anchor="middle" fill="#8d99aa" font-size="9">${esc(rows[i].month)}</text>`).join('');
  box.innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Cases started by month"><defs><linearGradient id="area-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#527cf4" stop-opacity=".18"/><stop offset="1" stop-color="#527cf4" stop-opacity="0"/></linearGradient></defs>${grid}<polygon points="${area}" fill="url(#area-fill)"/><polyline points="${points}" fill="none" stroke="#527cf4" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>${rows.map((r,i)=>`<circle cx="${x(i)}" cy="${y(r.count)}" r="2.7" fill="#fff" stroke="#527cf4" stroke-width="1.7"><title>${esc(r.month)}: ${whole.format(r.count)}</title></circle>`).join('')}${labels}</svg>`;
}
function renderBars(target, rows, labelKey, valueKey, limit) {
  const box = $(target);
  if (!rows.length) { box.textContent = 'No data to display.'; return; }
  const visible = limit ? rows.slice(0, limit) : rows;
  const max = Math.max(...visible.map(row => Number(row[valueKey]) || 0), 1);
  box.innerHTML = visible.map(row => `<div class="bar-row"><span class="bar-name" title="${esc(row[labelKey])}">${esc(row[labelKey])}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${Math.max(2, (Number(row[valueKey]) / max) * 100)}%"></span></span><span class="bar-count">${shortNumber(row[valueKey])}</span></div>`).join('');
}
function renderTransitions(rows) {
  const body = $('transitions-body');
  if (!rows.length) { body.innerHTML = '<tr><td colspan="3">No transitions to display.</td></tr>'; return; }
  body.innerHTML = rows.map(row => `<tr><td>${esc(row.from)}</td><td>${esc(row.to)}</td><td>${whole.format(row.count)}</td></tr>`).join('');
}
function renderModel(metrics) {
  if (!metrics?.test) {
    $('model-empty').classList.remove('hidden');
    return;
  }
  const test = metrics.test;
  $('model-section').classList.remove('hidden');
  $('model-mae').textContent = numberFormat.format(test.mae_hours);
  const ci = test.mae_case_bootstrap_95_ci_hours || [];
  $('model-ci').textContent = ci.length === 2 ? `95% case-bootstrap CI: ${numberFormat.format(ci[0])}–${numberFormat.format(ci[1])} h` : 'Mean error on the chronological test set.';
  const baseline = test.baseline_activity_median?.mae_hours;
  const biggest = Math.max(test.mae_hours || 0, baseline || 0, 1);
  $('model-bars').innerHTML = [
    ['ML model', test.mae_hours, '#527cf4'],
    ['Activity median', baseline, '#abb6c4'],
  ].map(([label,value]) => `<div class="compare-row"><span>${esc(label)}</span><span class="compare-track"><span class="compare-fill" style="display:block;width:${Math.max(2, value/biggest*100)}%;background:${label==='ML model'?'#527cf4':'#abb6c4'}"></span></span><b>${numberFormat.format(value ?? 0)} h</b></div>`).join('');
  const improvement = test.mae_improvement_vs_baseline_percent;
  $('improvement-note').textContent = improvement == null ? 'Could not calculate the change versus the baseline.' : improvement >= 0 ? `ML error is ${numberFormat.format(improvement)}% lower than the baseline on this test.` : `The baseline error is ${numberFormat.format(Math.abs(improvement))}% lower on this test.`;
  const coverage = Number(test.test_interval_coverage || 0);
  $('coverage').textContent = numberFormat.format(coverage * 100);
  $('coverage-track').style.width = `${Math.max(0, Math.min(100, coverage*100))}%`;
  $('interval-note').textContent = `Mean width: ${numberFormat.format(test.test_interval_mean_width_hours || 0)} h · validation radius: ${numberFormat.format(test.validation_absolute_residual_p90_hours || 0)} h`;
  const stageNames = {early:'Early stage', mid:'Middle stage', late:'Late stage'};
  $('stage-table').innerHTML = (test.by_stage || []).map(row => `<div class="stage-row"><span>${stageNames[row.stage] || esc(row.stage)} <small>(${whole.format(row.cases)} cases)</small></span><b>${numberFormat.format(row.mae_hours)} h</b></div>`).join('') || '<p class="micro-note">No stage metrics available.</p>';
}

async function loadCases(query='') {
  const response = await fetch(`/api/cases?q=${encodeURIComponent(query)}&limit=100`);
  const rows = await response.json();
  const select = $('case-select');
  const current = selectedCase;
  select.innerHTML = rows.map(row => `<option value="${esc(row.case_id)}">${esc(row.case_id)} · ${fmtDate(row.started_at)} · ${whole.format(row.event_count)} events · ${esc(row.outcome)}</option>`).join('');
  if (!rows.length) {
    selectedCase = null;
    $('case-facts').textContent = 'No cases match this search.';
    return;
  }
  const found = rows.find(row => row.case_id === current);
  selectedCase = found ? current : rows[0].case_id;
  select.value = selectedCase;
  await loadReplay();
}
async function loadReplay() {
  const id = $('case-select').value;
  if (!id) return;
  selectedCase = id;
  const response = await fetch(`/api/case?case_id=${encodeURIComponent(id)}&prefix=${$('prefix-range').value}`);
  if (!response.ok) { $('replay-message').textContent = 'Could not load this case.'; return; }
  const item = await response.json();
  const range = $('prefix-range');
  range.max = Math.max(1, item.event_count - 1);
  range.value = Math.min(Number(range.value) || 1, Number(range.max));
  if (Number(range.value) !== item.prefix_count) {
    const retry = await fetch(`/api/case?case_id=${encodeURIComponent(id)}&prefix=${range.value}`);
    Object.assign(item, await retry.json());
  }
  $('prefix-label').textContent = `${item.prefix_count} / ${Math.max(1, item.event_count - 1)} events`;
  const statusName = {accepted:'accepted', declined:'declined', cancelled:'cancelled', censored:'censored', other_terminal:'completed'};
  $('case-facts').innerHTML = `<span class="fact-chip">Started: ${esc(fmtDate(item.started_at))}</span><span class="fact-chip">Status: ${esc(statusName[item.outcome] || item.outcome)}</span><span class="fact-chip">Current: ${esc(item.current_activity)}</span><span class="fact-chip">Elapsed: ${fmtHours(item.elapsed_hours)}</span>`;
  $('history-list').innerHTML = (item.history || []).map(event => `<li><span class="seq">${String(event.sequence).padStart(2,'0')}</span><span class="act">${esc(event.activity)}</span><time>${esc(new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(event.timestamp)))}</time></li>`).join('');
  if (item.forecast) {
    $('forecast-value').textContent = numberFormat.format(item.forecast.remaining_hours);
    $('forecast-band').textContent = `${numberFormat.format(item.forecast.lower_hours)}–${numberFormat.format(item.forecast.upper_hours)} h`;
    $('baseline-value').textContent = `${numberFormat.format(item.forecast.baseline_hours)} h`;
    $('actual-value').textContent = item.remaining_actual_hours == null ? 'No recognized ending' : `${numberFormat.format(item.remaining_actual_hours)} h`;
    $('replay-message').textContent = item.remaining_actual_hours == null ? 'This trace is censored in the event log. No fabricated completion time is shown.' : `Difference from the historical outcome: ${numberFormat.format(Math.abs(item.forecast.remaining_hours - item.remaining_actual_hours))} h.`;
  } else {
    $('forecast-value').textContent = '—';
    $('forecast-band').textContent = 'Train the model first';
    $('baseline-value').textContent = '—';
    $('actual-value').textContent = item.remaining_actual_hours == null ? 'No recognized ending' : `${numberFormat.format(item.remaining_actual_hours)} h`;
    $('replay-message').textContent = 'No model found. Run flowtwin train.';
  }
}

async function init() {
  try {
    const response = await fetch('/api/dashboard');
    const data = await response.json();
    $('loading').classList.add('hidden');
    if (!data.ready) {
      $('empty-state').classList.remove('hidden');
      return;
    }
    $('dashboard').classList.remove('hidden');
    renderSummary(data);
    await loadCases();
    $('case-select').addEventListener('change', loadReplay);
    $('case-search').addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadCases($('case-search').value.trim()), 250);
    });
    $('prefix-range').addEventListener('input', () => {
      $('prefix-label').textContent = `${$('prefix-range').value} / ${$('prefix-range').max} events`;
    });
    $('prefix-range').addEventListener('change', loadReplay);
  } catch (error) {
    showError(`Could not connect to the local API. Start the app with flowtwin serve. (${error.message})`);
  }
}
init();
