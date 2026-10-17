/* End-to-end review against the real loopback service and an isolated quiz CSV. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.AUTOMARKER_PLAYWRIGHT || 'playwright');

(async () => {
  const archive = path.resolve(process.argv[2]), artifacts = path.resolve(process.argv[3]);
  const base = process.argv[4] + '/';
  const manifest = JSON.parse(fs.readFileSync(path.join(archive, 'archive.json'), 'utf8'));
  const csvPath = path.join(archive, 'assessment.csv');
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  try {
    const context = await browser.newContext({viewport: {width: 1500, height: 1000}});
    const page = await context.newPage();
    const errors = [], remote = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route(/^https?:/, route => {
      if (route.request().url().startsWith(base)) return route.continue();
      remote.push(route.request().url()); return route.abort();
    });
    const ready = () => page.waitForFunction(() => document.documentElement.dataset.reviewReady === 'true');
    const correct = () => page.locator('[data-review-answer]').first().locator('[data-verdict="correct"]');
    const incorrect = () => page.locator('[data-review-answer]').first().locator('[data-verdict="incorrect"]');
    await page.goto(base + 'index.html'); await ready();
    assert.equal(await page.locator('[data-link-csv]').count(), 0);
    assert.match(await page.locator('#assessment-status').textContent(), /assessment.csv is ready/);
    const original = fs.readFileSync(csvPath, 'utf8');
    await page.goto(base + encodeURIComponent(manifest.pages[0].html)); await ready();
    const latex = () => page.locator('td.recognized-latex-column').first();
    const toggle = () => page.locator('[data-toggle-latex]');
    assert.equal(await latex().isVisible(), false);
    assert.equal(await toggle().getAttribute('aria-pressed'), 'false');
    assert.equal(await toggle().textContent(), 'Show recognized LaTeX');
    await toggle().click();
    assert.equal(await latex().isVisible(), true);
    assert.equal(await toggle().getAttribute('aria-pressed'), 'true');
    assert.equal(await toggle().textContent(), 'Hide recognized LaTeX');
    await toggle().click();
    assert.equal(await latex().isVisible(), false);
    assert.equal(fs.readFileSync(csvPath, 'utf8'), original);
    assert.equal(await incorrect().getAttribute('aria-pressed'), 'true');
    assert.match(await page.locator('.auto-verdict').first().textContent(), /Auto: Incorrect/);
    assert.equal(await page.locator('select').count(), 0);
    const note = 'Reviewer, "quotes"\nSecond line: đúng';
    await correct().click(); await page.locator('#notes-1').fill(note);
    assert.equal(await correct().getAttribute('aria-pressed'), 'true');
    assert.equal(await incorrect().getAttribute('aria-pressed'), 'false');
    assert.equal(fs.readFileSync(csvPath, 'utf8'), original);
    await page.locator('[data-save-page]').first().click();
    await page.evaluate(() => document.getElementById('approve-save').click());
    assert.equal(await page.locator('#save-permission').isVisible(), true);
    assert.equal(fs.readFileSync(csvPath, 'utf8'), original);
    await page.locator('#cancel-save').click();
    assert.equal(fs.readFileSync(csvPath, 'utf8'), original);
    await page.locator('[data-save-next]').first().click(); await page.locator('#approve-save').click();
    await page.waitForURL(base + encodeURIComponent(manifest.pages[1].html)); await ready();
    assert.equal(await latex().isVisible(), false); // Each paper starts with OCR hidden.
    assert.equal(await incorrect().getAttribute('aria-pressed'), 'true');
    await page.locator('[data-save-page]').first().click(); await page.locator('#approve-save').click();
    await page.waitForFunction(() => document.getElementById('assessment-status').textContent.startsWith('Page saved'));
    fs.copyFileSync(csvPath, path.join(artifacts, 'approved.csv'));
    await page.goto(base + encodeURIComponent(manifest.pages[0].html)); await ready();
    assert.equal(await correct().getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('#notes-1').inputValue(), note);
    // A second reviewer changes this paper after the first tab loaded it.
    const snapshot = await (await context.request.get(base + 'api/assessment')).json();
    const source = manifest.pages[0].source;
    const response = await context.request.post(base + 'api/assessment', {
      headers: {'Origin': base.slice(0,-1), 'X-AutoMarker-Token': snapshot.token},
      data: {approved: true, archive_id: snapshot.archive_id, source_image: source, page: '1',
        version: snapshot.versions[JSON.stringify([source,'1'])],
        edits: [{answer_id:'answer_001', verdict:'incorrect', notes:'Other reviewer'}]}
    });
    assert.equal(response.status(), 200);
    const conflict = fs.readFileSync(csvPath, 'utf8');
    await page.locator('#notes-1').fill('Conflicting draft');
    await page.locator('[data-save-page]').first().click(); await page.locator('#approve-save').click();
    await page.waitForFunction(() => document.getElementById('assessment-status').textContent.includes('changed elsewhere'));
    assert.equal(fs.readFileSync(csvPath, 'utf8'), conflict);
    page.once('dialog', dialog => dialog.accept()); await page.locator('[data-reload-csv]').click();
    await page.waitForFunction(() => document.querySelector('button[data-verdict="incorrect"]').getAttribute('aria-pressed') === 'true');
    await page.setViewportSize({width: 390, height: 900});
    assert.equal(await latex().isVisible(), false);
    await toggle().click();
    assert.equal(await latex().isVisible(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await toggle().click();
    assert.equal(await latex().isVisible(), false);
    assert.deepEqual(errors, []); assert.deepEqual(remote, []);
    console.log('Automatic association, auto verdicts, binary controls, permission, persistence and conflict checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
