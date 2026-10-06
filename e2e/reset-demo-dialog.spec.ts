import { expect, test } from '@playwright/test'

test('reset demo dialog stays in view and manages focus', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 500 })
  await page.goto('/network')

  const trigger = page.getByRole('button', { name: /Reset demo/ })
  await trigger.click()

  const dialog = page.getByRole('dialog', { name: 'Reset demo data?' })
  await expect(dialog).toBeVisible()
  await expect(page.getByRole('button', { name: 'Yes, reset demo' })).toBeFocused()

  const bounds = await dialog.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(500)

  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(page.getByRole('button', { name: 'Yes, reset demo' })).toBeFocused()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})
