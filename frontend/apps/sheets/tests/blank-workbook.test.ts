import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'

import { blankXlsxBytes } from '../src/renderer/web-adapter'

// The blank workbook is a hand-built OPC zip (no client-side createBlank exists).
// If a required part is dropped or the zip is malformed the Rust sidecar's /open
// rejects it and the new-workbook flow dies — this reopens the archive and asserts
// every part the [Content_Types] overrides reference is present + parseable XML.
describe('blankXlsxBytes', () => {
  it('produces a reopenable xlsx with all required OPC parts', async () => {
    const zip = await JSZip.loadAsync(await blankXlsxBytes())
    const required = [
      '[Content_Types].xml',
      '_rels/.rels',
      'xl/_rels/workbook.xml.rels',
      'xl/workbook.xml',
      'xl/worksheets/sheet1.xml',
      'xl/styles.xml',
    ]
    for (const name of required) {
      expect(zip.file(name), `missing ${name}`).toBeTruthy()
    }
    const workbook = await zip.file('xl/workbook.xml')!.async('string')
    expect(workbook).toContain('name="Sheet1"')
    // well-formed XML (DOMParser is available under jsdom)
    for (const name of required) {
      const xml = await zip.file(name)!.async('string')
      const doc = new DOMParser().parseFromString(xml, 'application/xml')
      expect(doc.querySelector('parsererror'), `${name} not well-formed`).toBeNull()
    }
  })
})
