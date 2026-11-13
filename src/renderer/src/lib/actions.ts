import { useMemo } from 'react'
import type { FileFilter } from '../../../shared/api'
import { baseName, FILTERS, samePath, withExt } from './files'
import { useServices } from './services'

/** PDF operations shared by the Home quick actions and the PDF Studio toolbar. */
export function usePdfActions() {
  const { run, ask, notify } = useServices()

  return useMemo(() => {
    const pickPdf = async (title: string): Promise<string | null> =>
      (await window.suite.openFiles({ title, filters: FILTERS.pdf }))[0] ?? null

    const convert = async (
      input: string | null,
      target: { ext: string; label: string; filters: FileFilter[] },
      password?: string
    ): Promise<void> => {
      input ??= await pickPdf(`Choose a PDF to convert to ${target.label}`)
      if (!input) return
      const output = await window.suite.saveFile({
        title: `Save ${target.label} as`,
        defaultPath: withExt(input, target.ext),
        filters: target.filters
      })
      if (!output) return
      await run(`${baseName(input)} → ${target.label}`, 'convert.run', { input, output, options: { password } })
    }

    return {
      toWord: (input: string | null = null, password?: string) =>
        convert(input, { ext: 'docx', label: 'Word', filters: FILTERS.docx }, password),

      toMarkdown: (input: string | null = null, password?: string) =>
        convert(input, { ext: 'md', label: 'Markdown', filters: FILTERS.markdown }, password),

      toExcel: (input: string | null = null, password?: string) =>
        convert(input, { ext: 'xlsx', label: 'Excel', filters: FILTERS.xlsx }, password),

      toHtml: (input: string | null = null, password?: string) =>
        convert(input, { ext: 'html', label: 'HTML', filters: FILTERS.html }, password),

      toText: (input: string | null = null, password?: string) =>
        convert(input, { ext: 'txt', label: 'text', filters: FILTERS.text }, password),

      async toImages(input: string | null = null, password?: string): Promise<void> {
        input ??= await pickPdf('Choose a PDF to export as images')
        if (!input) return
        const output_dir = await window.suite.openFolder({ title: 'Choose a folder for the page images' })
        if (!output_dir) return
        await run(`${baseName(input)} → PNG pages`, 'pdf.to_images', { input, output_dir, format: 'png', dpi: 150, password })
      },

      async merge(): Promise<void> {
        const inputs = await window.suite.openFiles({
          title: 'Choose the PDFs to merge (they are joined in the order listed)',
          filters: FILTERS.pdf,
          multiple: true
        })
        if (inputs.length === 0) return
        if (inputs.length < 2) return notify('Merge PDFs', 'Select at least two PDFs to merge.', 'error')
        const output = await window.suite.saveFile({
          title: 'Save merged PDF as',
          defaultPath: withExt(inputs[0], 'pdf', '-merged'),
          filters: FILTERS.pdf
        })
        if (!output) return
        if (inputs.some((p) => samePath(p, output))) {
          return notify('Merge PDFs', 'Choose a new file name - the output cannot replace one of the inputs.', 'error')
        }
        await run(`Merge ${inputs.length} PDFs`, 'pdf.merge', { inputs, output })
      },

      async imagesToPdf(): Promise<void> {
        const inputs = await window.suite.openFiles({ title: 'Choose images', filters: FILTERS.images, multiple: true })
        if (inputs.length === 0) return
        const output = await window.suite.saveFile({
          title: 'Save PDF as',
          defaultPath: withExt(inputs[0], 'pdf'),
          filters: FILTERS.pdf
        })
        if (!output) return
        await run(`${inputs.length} image${inputs.length > 1 ? 's' : ''} → PDF`, 'convert.images_to_pdf', { inputs, output })
      },

      async batchToWord(): Promise<void> {
        const inputs = await window.suite.openFiles({
          title: 'Choose PDFs to convert to Word',
          filters: FILTERS.pdf,
          multiple: true
        })
        if (inputs.length === 0) return
        const output_dir = await window.suite.openFolder({ title: 'Choose a folder for the Word documents' })
        if (!output_dir) return
        const result = await run<{ succeeded: number; failed: number }>(
          `Batch: ${inputs.length} PDFs → Word`,
          'convert.batch',
          { inputs, output_dir, target: 'docx' }
        )
        if (result && result.failed > 0) {
          notify('Batch conversion', `${result.succeeded} converted, ${result.failed} failed.`, 'error')
        }
      },

      async split(input: string, password?: string): Promise<void> {
        const answer = await ask({
          title: 'Split PDF',
          body: 'Each range becomes its own PDF. Leave empty to save every page separately.',
          fields: [{ name: 'ranges', label: 'Page ranges', placeholder: 'e.g. 1-3, 4, 7-', optional: true }],
          confirm: 'Choose folder…'
        })
        if (!answer) return
        const output_dir = await window.suite.openFolder({ title: 'Choose a folder for the split PDFs' })
        if (!output_dir) return
        await run(`Split ${baseName(input)}`, 'pdf.split', { input, output_dir, ranges: answer.ranges, password })
      },

      async watermark(input: string, password?: string): Promise<void> {
        const answer = await ask({
          title: 'Add watermark',
          body: 'The text is drawn diagonally across every page of a new copy.',
          fields: [{ name: 'text', label: 'Watermark text', initial: 'CONFIDENTIAL' }],
          confirm: 'Save as…'
        })
        if (!answer) return
        const output = await window.suite.saveFile({
          title: 'Save watermarked PDF as',
          defaultPath: withExt(input, 'pdf', '-watermarked'),
          filters: FILTERS.pdf
        })
        if (!output) return
        if (samePath(input, output)) return notify('Watermark', 'Choose a new file name for the copy.', 'error')
        await run(`Watermark ${baseName(input)}`, 'pdf.watermark', { input, output, text: answer.text, password })
      },

      /** Digitally sign with a local certificate. `page` is where an optional visible stamp goes. */
      async sign(input: string, password: string | undefined, page: number): Promise<string | null> {
        const [certificate] = await window.suite.openFiles({
          title: 'Choose your signing certificate (.p12 or .pfx)',
          filters: FILTERS.certificate
        })
        if (!certificate) return null
        const answer = await ask({
          title: 'Sign PDF',
          body: `Certificate: ${baseName(certificate)}. The signing time comes from this computer's clock; no timestamp service is contacted.`,
          fields: [
            { name: 'passphrase', label: 'Certificate password', type: 'password', optional: true },
            { name: 'reason', label: 'Reason', placeholder: 'e.g. Approved', optional: true },
            { name: 'location', label: 'Location', optional: true },
            { name: 'visible', label: `Show a signature stamp on page ${page + 1}`, type: 'checkbox', initial: 'true' }
          ],
          confirm: 'Save as…'
        })
        if (!answer) return null
        const output = await window.suite.saveFile({
          title: 'Save signed PDF as',
          defaultPath: withExt(input, 'pdf', '-signed'),
          filters: FILTERS.pdf
        })
        if (!output) return null
        if (samePath(input, output)) {
          notify('Sign PDF', 'Choose a new file name for the signed copy.', 'error')
          return null
        }
        const result = await run(`Sign ${baseName(input)}`, 'pdf.sign', {
          input,
          output,
          certificate,
          password,
          passphrase: answer.passphrase,
          reason: answer.reason,
          location: answer.location,
          visible: answer.visible === 'true',
          page
        })
        return result ? output : null
      },

      async protect(input: string, password?: string): Promise<void> {
        const answer = await ask({
          title: 'Password-protect PDF',
          body: 'Creates an AES-256 encrypted copy. The password cannot be recovered if it is lost.',
          fields: [
            { name: 'pw', label: 'Password to open', type: 'password' },
            { name: 'again', label: 'Confirm password', type: 'password' },
            { name: 'print', label: 'Allow printing', type: 'checkbox', initial: 'true' },
            { name: 'copy', label: 'Allow copying text', type: 'checkbox', initial: 'true' },
            { name: 'modify', label: 'Allow editing and annotating', type: 'checkbox', initial: 'true' },
            {
              name: 'owner',
              label: 'Owner password',
              type: 'password',
              optional: true,
              hint: 'Required if you untick anything above. Restrictions are a request to PDF readers, not a lock.'
            }
          ],
          confirm: 'Save as…'
        })
        if (!answer) return
        if (answer.pw !== answer.again) return notify('Protect PDF', 'The two passwords did not match.', 'error')
        const output = await window.suite.saveFile({
          title: 'Save protected PDF as',
          defaultPath: withExt(input, 'pdf', '-protected'),
          filters: FILTERS.pdf
        })
        if (!output) return
        if (samePath(input, output)) return notify('Protect PDF', 'Choose a new file name for the copy.', 'error')
        await run(`Protect ${baseName(input)}`, 'pdf.protect', {
          input,
          output,
          password,
          user_password: answer.pw,
          owner_password: answer.owner || undefined,
          permissions: {
            print: answer.print === 'true',
            copy: answer.copy === 'true',
            modify: answer.modify === 'true',
            annotate: answer.modify === 'true'
          }
        })
      }
    }
  }, [run, ask, notify])
}
