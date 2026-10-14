import { test, expect } from '@playwright/test';
test('explores verified public source data through the real product', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Load verified public sample' }).first().click();
  await expect(page.getByTestId('graph-scope')).toBeVisible();
  await expect(page.getByText('langchain-community', { exact: true })).toBeVisible();
  await expect(page.getByText('Records returned').first()).toBeVisible();
  await expect(page.getByText('Preparing evidence', { exact: true })).not.toBeVisible();
  await page.screenshot({ path: '../artifacts/verification/core-desktop.png', fullPage: false });
  await page.getByRole('button', { name: 'Advisory matches' }).click();
  await page.locator('.finding-card').first().click();
  await expect(page.getByRole('heading', { name: 'Recorded impact paths' })).toBeVisible();
  await expect(page.locator('.evidence-detail').getByRole('link', { name: 'Source record ↗' })).toBeVisible();
  await page.screenshot({ path: '../artifacts/verification/core-evidence.png', fullPage: true });
  await page.getByRole('button', { name: 'Compare snapshots', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Compare evidence before changing code' })).toBeVisible();
  await page.setViewportSize({ width: 430, height: 932 });
  await page.screenshot({ path: '../artifacts/verification/core-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('creates a project, resolves two real snapshots, and compares their sources', async ({ page }) => {
  const name = `e2e-public-verification-${Date.now()}`;
  await page.goto('/');
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByRole('textbox', { name: 'Project name' }).fill(name);
  const created = page.waitForResponse(response => response.url().endsWith('/api/projects') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  const project = (await (await created).json()).id;
  try {
    await expect(page.getByRole('combobox', { name: 'Project', exact: true })).toHaveValue(project);
    for (const version of ['0.0.50', '0.4.2']) {
      await page.getByRole('button', { name: 'Add snapshot' }).click();
      const dialog = page.getByRole('dialog');
      await dialog.getByRole('button', { name: 'Public package' }).click();
      await dialog.getByRole('textbox', { name: 'Package name' }).fill('langchain-experimental');
      await dialog.getByRole('textbox', { name: 'Version', exact: true }).fill(version);
      await dialog.getByRole('button', { name: 'Load public resolution' }).click();
      await expect(page.getByRole('combobox', { name: 'Snapshot', exact: true }).locator('option', { hasText: `langchain-experimental@${version}` })).toHaveCount(1, { timeout: 45000 });
      await expect(page.getByText('Preparing evidence', { exact: true })).not.toBeVisible({ timeout: 45000 });
    }
    await page.getByRole('button', { name: 'Compare snapshots', exact: true }).first().click();
    await page.getByRole('combobox', { name: 'Baseline snapshot' }).selectOption({ label: 'langchain-experimental@0.0.50 · Public resolution' });
    await page.getByRole('combobox', { name: 'Candidate snapshot' }).selectOption({ label: 'langchain-experimental@0.4.2 · Public resolution' });
    await page.locator('.compare-picker').getByRole('button', { name: 'Compare snapshots' }).click();
    await expect(page.getByText('metadata comparison', { exact: true })).toBeVisible({ timeout: 45000 });
    await expect(page.getByText('New known matches', { exact: true })).toBeVisible();
    await expect(page.getByText('Remaining known matches', { exact: true })).toBeVisible();
    await page.screenshot({ path: '../artifacts/verification/core-comparison.png', fullPage: true });
  } finally {
    const { spawnSync } = await import('node:child_process');
    const cleanup = spawnSync('../backend/.venv/bin/python', ['-c', `
import sys
from depscope.runtime.config import load_settings
from depscope.graph.driver import connect
with connect(load_settings()) as driver:
 with driver.session() as session:
  project=sys.argv[1]
  name=sys.argv[2]
  assert session.run('MATCH (p:Project {id:$p,name:$n}) RETURN p.id AS id',p=project,n=name).single()
  session.run('MATCH (c:Comparison)-[:BASELINE|CANDIDATE]->(s:Snapshot {project_id:$p}) DETACH DELETE c',p=project).consume()
  session.run('MATCH (r:MatchRun {project_id:$p})-[:HAS_FINDING]->(f) DETACH DELETE f',p=project).consume()
  session.run('MATCH (r:MatchRun {project_id:$p}) DETACH DELETE r',p=project).consume()
  session.run('MATCH (c:ComponentInstance {project_id:$p}) DETACH DELETE c',p=project).consume()
  session.run('MATCH (s:Snapshot {project_id:$p}) DETACH DELETE s',p=project).consume()
  session.run('MATCH (p:Project {id:$p,name:$n}) DETACH DELETE p',p=project,n=name).consume()
`, project, name], { encoding: 'utf8' });
    expect(cleanup.status, cleanup.stderr).toBe(0);
  }
});
