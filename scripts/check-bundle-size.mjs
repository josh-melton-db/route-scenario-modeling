import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const assetDirectory = join(process.cwd(), 'dist', 'assets')
const files = readdirSync(assetDirectory).filter((name) => name.endsWith('.js'))
const entryBudget = 500 * 1024
const lazyBudget = 1400 * 1024
const failures = []

for (const name of files) {
  const bytes = statSync(join(assetDirectory, name)).size
  const budget = name.startsWith('index-') ? entryBudget : lazyBudget
  if (bytes > budget) failures.push(`${name}: ${bytes} bytes exceeds ${budget}`)
}
if (failures.length) {
  console.error(`Bundle budget exceeded:\n${failures.join('\n')}`)
  process.exit(1)
}
console.log(`Bundle budget passed for ${files.length} JavaScript chunks.`)
