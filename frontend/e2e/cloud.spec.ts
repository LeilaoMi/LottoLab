import { expect, test } from '@playwright/test'

const token = 'isolated-e2e-test-token-32-chars-ok'

test('private cloud entry, request compute and persistent history without a worker', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  expect((await request.get('/api/v1/draws')).status()).toBe(403)
  const health = await (await request.get('/api/v1/health')).json()
  expect(health.execution_mode).toBe('request')
  expect(health.worker_ready).toBe(true)
  await page.goto('/#/simulation')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByLabel('管理员令牌', { exact: true }).fill('wrong-token')
  await page.getByRole('button', { name: '验证权限', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('令牌无效')
  await page.getByLabel('管理员令牌', { exact: true }).fill(token)
  await page.getByRole('button', { name: '验证权限', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('云端按需计算', { exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '模拟次数', exact: true }).selectOption('10000')
  await page.getByRole('button', { name: '开始模拟', exact: true }).click()
  await expect(page.locator('.job-completed')).toBeVisible({ timeout: 60000 })
  await expect(page.getByRole('heading', { name: '命中分布：模拟与理论' })).toBeVisible()
  await page.getByRole('button', { name: '导入 CSV', exact: true }).click()
  await expect(page.getByText('支持 UTF-8 / GB18030，最多 4 MB')).toBeVisible()
  await page.keyboard.press('Escape')

  await page.reload()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByLabel('管理员令牌', { exact: true }).fill(token)
  await page.getByRole('button', { name: '验证权限', exact: true }).click()
  const jobs = await (
    await request.get('/api/v1/jobs?kind=simulation', { headers: { 'X-Admin-Token': token } })
  ).json()
  expect(jobs.items).toHaveLength(1)
  expect(jobs.items[0].status).toBe('completed')
  await expect(page.locator('.history-list')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(391)
  expect(errors).toEqual([])
  await page.screenshot({
    path: test.info().outputPath('cloud-mobile.png'),
    fullPage: true,
    animations: 'disabled',
  })
})
