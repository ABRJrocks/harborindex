import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('query, mode and document controls inspect actual exported results', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Toy-vector demonstration', { exact: true })).toBeVisible();
  await expect(page.locator('#inspector h2')).toHaveText('Service credential rotation');
  await expect(page.locator('.contribution-track')).toHaveCount(1);
  await page.getByLabel('Recorded query').selectOption('1');
  await expect(page.locator('#inspector h2')).toHaveText('Database restore rehearsal');
  await page.getByLabel('Retrieval mode').selectOption('dense');
  await expect(page.locator('.contribution-track')).toHaveCount(0);
  await expect(page.locator('#formula')).toContainText('Exact cosine');
  await page.getByRole('button', { name: 'Recovery point review' }).click();
  await expect(page.locator('#inspector h2')).toHaveText('Recovery point review');
  await expect(page.getByRole('button', { name: 'Recovery point review' })).toBeFocused();
  await page.getByLabel('Filter document results').fill('does-not-exist');
  await expect(page.locator('#rows tr')).toHaveCount(0);
  await expect(page.locator('#inspector')).toContainText('No document selected');
  await page.getByLabel('Recorded query').selectOption('2');
  await expect(page.locator('#inspector h2')).toHaveText('Canary traffic change');
});

test('hostile content stays literal and makes no external request', async ({ page }) => {
  const external = [];
  const errors = [];
  page.on('request', req => { if (!req.url().startsWith('http://127.0.0.1:4188/')) external.push(req.url()); });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/hostile.html');
  await expect(page.locator('#inspector h2')).toContainText('</script>');
  await expect(page.locator('.document-body')).toContainText('<img');
  expect(await page.evaluate(() => window.pwned)).toBeUndefined();
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) {
  test(`accessible report and contained layout at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('/');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const result = await new AxeBuilder({ page }).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
    expect(result.violations).toEqual([]);
    await page.screenshot({ path: `../../reports/report-${width}.png`, fullPage: true });
  });
}
