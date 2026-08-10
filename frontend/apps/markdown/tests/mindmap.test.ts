import { describe, expect, it } from 'vitest'
import { Transformer } from 'markmap-lib'

interface Node {
  content: string
  children?: Node[]
}

function countNodes(n: Node): number {
  return 1 + (n.children ?? []).reduce((s, c) => s + countNodes(c), 0)
}

// The mind-map is a view of the Markdown outline: this guards that the outline
// still transforms into a hierarchical tree (headings + list nesting → depth).
describe('mindmap transform', () => {
  const transformer = new Transformer()

  it('nests headings and lists into a tree', () => {
    const md = '# A\n\n## B\n\n- c\n  - d\n'
    const { root } = transformer.transform(md) as { root: Node }
    expect(root.content).toContain('A')
    expect(countNodes(root)).toBeGreaterThanOrEqual(4)
    // B is a child of A, c a child of B, d a child of c
    const b = root.children?.[0]
    expect(b?.content).toContain('B')
    expect(b?.children?.[0]?.content).toContain('c')
  })
})
