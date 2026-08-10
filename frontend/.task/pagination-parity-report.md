# Pagination parity report (F2: line-level pagination + Word page-break constraints)

Generated at: 2026-08-10T08:35:11.148Z
Baseline source: LibreOffice headless (coarse baseline) + real Word for Mac (precise baseline, 25 docs)

## Overview

| Metric | F0 baseline | F2 vs LO | F2 vs Word |
|------|--------|--------|--------|
| Corpus | 28 docs | 27 docs | 25 docs |
| Baseline total pages | 108 pages | 93 pages | 73 pages |
| Page-start blocks matched | 52/108 = **48.1%** | 61/93 = **65.6%** | 72/73 = **98.6%** |
| Identical page counts | 12/28 docs | 17/27 docs | 25/25 docs |

> Milestones: F1 (self-managed line heights + docGrid) 80.6% → F2 block+line fusion 85.2% → F2 unified engine 87.0%.
> Acceptance criterion (vs precise Word baseline): 90% page-start blocks matched.

## Per-document details (vs LO)

| File | LO pages | Our pages | Diff | Page starts matched | Match rate |
|------|--------|---------|------|---------|--------|
| 01-simple-english | 4 | 4 | ✓ 0 | 4/4 | 100% |
| 02-chinese-long-docgrid | 7 | 4 | -3 | 4/7 | 57% |
| 03-mixed-lang | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 04-headings-keepnext | 7 | 4 | -3 | 3/7 | 43% |
| 05-long-table | 2 | 2 | ✓ 0 | 1/2 | 50% |
| 06-with-footnotes | 3 | 3 | ✓ 0 | 2/3 | 67% |
| 07-page-breaks | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 08-multi-section-paper | 2 | 2 | ✓ 0 | 2/2 | 100% |
| 09-large-paragraph | 5 | 5 | ✓ 0 | 4/5 | 80% |
| 10-cn-official-doc | 7 | 4 | -3 | 1/7 | 14% |
| 11-multi-tables | 3 | 2 | -1 | 1/3 | 33% |
| 12-orphan-heading | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 13-english-report | 8 | 8 | ✓ 0 | 8/8 | 100% |
| 14-chinese-no-docgrid | 5 | 4 | -1 | 4/5 | 80% |
| 15-mixed-content | 6 | 4 | -2 | 1/6 | 17% |
| 16-numbered-list | 3 | 2 | -1 | 1/3 | 33% |
| 17-single-page | 1 | 1 | ✓ 0 | 1/1 | 100% |
| 18-page-break-before | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 19-oversized-table | 3 | 3 | ✓ 0 | 1/3 | 33% |
| 20-cn-short-report | 4 | 2 | -2 | 2/4 | 50% |
| 21-continuous-section | 2 | 2 | ✓ 0 | 2/2 | 100% |
| 22-two-columns | 2 | 1 | -1 | 1/2 | 50% |
| 23-tblheader-repeat | 3 | 2 | -1 | 2/3 | 67% |
| fixture-kitchen-sink | 1 | 1 | ✓ 0 | 1/1 | 100% |
| fixture-simple | 1 | 1 | ✓ 0 | 1/1 | 100% |
| kitchen-sink | 1 | 1 | ✓ 0 | 1/1 | 100% |
| simple | 1 | 1 | ✓ 0 | 1/1 | 100% |

## Per-document details (vs precise Word baseline)

| File | Word pages | Our pages | Diff | Page starts matched | Match rate |
|------|--------|---------|------|---------|--------|
| 01-simple-english | 4 | 4 | ✓ 0 | 4/4 | 100% |
| 02-chinese-long-docgrid | 4 | 4 | ✓ 0 | 4/4 | 100% |
| 03-mixed-lang | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 04-headings-keepnext | 4 | 4 | ✓ 0 | 4/4 | 100% |
| 05-long-table | 2 | 2 | ✓ 0 | 2/2 | 100% |
| 06-with-footnotes | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 07-page-breaks | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 08-multi-section-paper | 2 | 2 | ✓ 0 | 2/2 | 100% |
| 09-large-paragraph | 5 | 5 | ✓ 0 | 4/5 | 80% |
| 10-cn-official-doc | 4 | 4 | ✓ 0 | 4/4 | 100% |
| 11-multi-tables | 2 | 2 | ✓ 0 | 2/2 | 100% |
| 12-orphan-heading | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 13-english-report | 8 | 8 | ✓ 0 | 8/8 | 100% |
| 14-chinese-no-docgrid | 4 | 4 | ✓ 0 | 4/4 | 100% |
| 15-mixed-content | 4 | 4 | ✓ 0 | 4/4 | 100% |
| 16-numbered-list | 2 | 2 | ✓ 0 | 2/2 | 100% |
| 17-single-page | 1 | 1 | ✓ 0 | 1/1 | 100% |
| 18-page-break-before | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 19-oversized-table | 3 | 3 | ✓ 0 | 3/3 | 100% |
| 20-cn-short-report | 2 | 2 | ✓ 0 | 2/2 | 100% |
| 21-continuous-section | 2 | 2 | ✓ 0 | 2/2 | 100% |
| 22-two-columns | 1 | 1 | ✓ 0 | 1/1 | 100% |
| 23-tblheader-repeat | 2 | 2 | ✓ 0 | 2/2 | 100% |
| fixture-simple | 1 | 1 | ✓ 0 | 1/1 | 100% |
| simple | 1 | 1 | ✓ 0 | 1/1 | 100% |

## F2 completion status

- [x] Corpus built (28 docx) + LO baseline (108 pages)
- [x] F1: self-managed line heights + docGrid (48.1% → 80.6%)
- [x] F2 engine: line-level pagination + widowControl/keepLines/keepNext + table row-level page breaks (cantSplit/tblHeader)
- [x] Footnote placeholders: paragraphs with footnote references reserve page-bottom height
- [ ] F2 parity 65.6% (stage target ≥85%, acceptance criterion 90%)

## Bottleneck analysis

No documents below a 60% match rate (vs Word) 🎉

## Remaining long tail

1. openclaw (PDF-converted doc) off by 1 page: multi-section variable margins + text boxes/floating objects;
   fixed layout not fully modeled (trHeight/wrap anchoring are modeled but still insufficient)
2. 09-large-paragraph line-break points off by 2-3 chars (kerning precision explicitly out of scope per plan §2)