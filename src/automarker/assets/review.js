/* One quiz, one assessment.csv. Writes require explicit approval for each paper. */
(() => {
  'use strict';
  const element = document.getElementById('assessment-data');
  if (!element) return;
  const config = JSON.parse(element.textContent);
  const controls = [...document.querySelectorAll('[data-review-answer]')];
  const status = document.getElementById('assessment-status');
  const dialog = document.getElementById('save-permission');
  const pageKey = JSON.stringify([config.source, String(config.page)]);
  let saved = new Map(), snapshot = null, dirty = false, saving = false, destination = null;

  const latexToggle = document.querySelector('[data-toggle-latex]');
  const answerTable = document.getElementById('answer-table');
  if (latexToggle && answerTable) {
    latexToggle.addEventListener('click', () => {
      const show = answerTable.dataset.latexHidden === 'true';
      answerTable.dataset.latexHidden = String(!show);
      latexToggle.setAttribute('aria-pressed', String(show));
      latexToggle.textContent = (show ? 'Hide' : 'Show') + ' recognized LaTeX';
    });
  }

  function message(text, error = false) {
    status.textContent = text;
    status.classList.toggle('error', error);
  }
  function selectVerdict(control, verdict) {
    control.dataset.verdict = ['correct', 'incorrect'].includes(verdict) ? verdict : '';
    control.querySelectorAll('[data-verdict]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.verdict === control.dataset.verdict));
    });
  }
  function showSaved(rows) {
    const current = rows.filter(row => row.archive_id === config.archiveId);
    const identity = row => JSON.stringify([row.source_image, row.page, row.answer_id]);
    const map = new Map(current.map(row => [identity(row), row]));
    saved = new Map(config.rows.map(seed => [seed.answer_id, map.get(identity(seed)) || seed]));
    controls.forEach(control => {
      const row = saved.get(control.dataset.reviewAnswer);
      selectVerdict(control, row.verdict);
      control.querySelector('textarea').value = row.notes || '';
    });
    document.querySelectorAll('[data-review-source]').forEach(card => {
      const rows = current.filter(row => row.source_image === card.dataset.reviewSource && row.page === card.dataset.reviewPage);
      const correct = rows.filter(row => row.verdict === 'correct').length;
      const incorrect = rows.filter(row => row.verdict === 'incorrect').length;
      const reviewed = rows.filter(row => row.reviewed_at).length;
      card.querySelector('.review-progress').textContent = correct + ' correct / ' + incorrect + ' incorrect · ' + reviewed + ' reviewed';
    });
    dirty = false;
  }
  function changes() {
    return controls.map(control => ({answer_id: control.dataset.reviewAnswer,
      verdict: control.dataset.verdict, notes: control.querySelector('textarea').value}));
  }
  function edited() {
    dirty = changes().some(row => row.verdict !== (saved.get(row.answer_id).verdict || '') || row.notes !== (saved.get(row.answer_id).notes || ''));
    message(dirty ? 'Unsaved corrections. assessment.csv has not changed.' : 'No unsaved corrections.');
  }
  async function responseJSON(response) {
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Could not access this quiz assessment.');
    if (data.archive_id !== config.archiveId) throw Error('This review server belongs to a different quiz.');
    return data;
  }
  async function reload() {
    snapshot = await responseJSON(await fetch('/api/assessment', {cache: 'no-store'}));
    showSaved(snapshot.rows);
    document.documentElement.dataset.reviewLive = 'true';
    message('This quiz’s assessment.csv is ready. Confirm or correct the automatic verdicts.');
  }
  function requestSave(target = null) {
    if (saving || dialog.open) return;
    if (!snapshot) {
      message('Start the local review server for this quiz to save directly to assessment.csv. See the command below.', true);
      return;
    }
    const values = changes();
    if (values.some(row => !['correct', 'incorrect'].includes(row.verdict))) {
      message('Choose ✓ or ✕ for every answer before saving this paper.', true);
      return;
    }
    destination = target;
    const correct = values.filter(row => row.verdict === 'correct').length;
    document.getElementById('save-summary').textContent = config.source + ': ' + correct + ' correct, ' +
      (values.length - correct) + ' incorrect. Only this paper’s rows in this quiz’s assessment.csv will be updated.';
    dialog.showModal();
  }
  if (dialog) {
    document.getElementById('approve-save').addEventListener('click', async event => {
      if (!event.isTrusted || !dialog.open || saving) return;
      dialog.close(); saving = true;
      const target = destination;
      const inputs = [...document.querySelectorAll('[data-save-page], [data-save-next], [data-reload-csv], [data-verdict], .review-cell textarea')];
      inputs.forEach(input => { input.disabled = true; });
      message('Saving this paper to assessment.csv…');
      try {
        snapshot = await responseJSON(await fetch('/api/assessment', {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-AutoMarker-Token': snapshot.token},
          body: JSON.stringify({archive_id: config.archiveId, source_image: config.source,
            page: config.page, version: snapshot.versions[pageKey], approved: true, edits: changes()})
        }));
        showSaved(snapshot.rows);
        message('Page saved to this quiz’s assessment.csv.');
        if (target) { saving = false; location.assign(target); }
      } catch (error) { message(error.message + ' Your edits remain on this page.', true); }
      finally { saving = false; inputs.forEach(input => { input.disabled = false; }); }
    });
    const cancel = () => { destination = null; message('CSV update cancelled. Nothing was saved.'); };
    document.getElementById('cancel-save').addEventListener('click', () => { dialog.close(); cancel(); });
    dialog.addEventListener('cancel', cancel);
  }
  controls.forEach(control => {
    control.querySelectorAll('[data-verdict]').forEach(button => button.addEventListener('click', () => {
      selectVerdict(control, button.dataset.verdict); edited();
    }));
    control.querySelector('textarea').addEventListener('input', edited);
  });
  document.querySelectorAll('[data-save-page]').forEach(button => button.addEventListener('click', () => requestSave()));
  document.querySelectorAll('[data-save-next]').forEach(button => button.addEventListener('click', () => requestSave(config.next)));
  document.querySelectorAll('nav a').forEach(link => link.addEventListener('click', event => {
    if (saving) { event.preventDefault(); return; }
    if (link.getAttribute('href') === config.next || dirty) { event.preventDefault(); requestSave(link.getAttribute('href')); }
  }));
  document.querySelectorAll('[data-reload-csv]').forEach(button => button.addEventListener('click', () => {
    if (dirty && !window.confirm('Discard unsaved corrections and reload saved verdicts?')) return;
    reload().catch(error => message(error.message, true));
  }));
  window.addEventListener('beforeunload', event => {
    if (dirty || saving) { event.preventDefault(); event.returnValue = ''; }
  });
  showSaved(config.savedRows);
  (async () => {
    try {
      if (['http:', 'https:'].includes(location.protocol)) await reload();
      else message('Automatic verdicts shown. Start this quiz’s local review server to save corrections.');
    } catch (error) { message(error.message, true); }
    document.documentElement.dataset.reviewReady = 'true';
  })();
})();
