import { fmtPct, type MetricSet, type Metrics } from './api'

/** Persons are what the system is for: their missed detections and mAP are shown first everywhere */
export const FOCUS_CLASS = 'person'

/** the focus class of a metrics object: person if evaluated, otherwise the first class */
export function focusClassOf(m: Metrics | null | undefined): string | null {
  const names = Object.keys(m?.per_class ?? {})
  return names.includes(FOCUS_CLASS) ? FOCUS_CLASS : names[0] ?? null
}

/** annotated boxes of a class = TP + FN */
export function boxesOf(s: MetricSet | null | undefined): number | null {
  return s?.tp != null && s?.fn != null ? s.tp + s.fn : null
}

/** "4 von 112 (3,6 %)" */
export function missedText(s: MetricSet | null | undefined, withRate = true): string {
  const boxes = boxesOf(s)
  if (s?.fn == null || boxes == null) return '–'
  return withRate && boxes ? `${s.fn} von ${boxes} (${fmtPct(s.fn / boxes)})` : `${s.fn} von ${boxes}`
}

/** metrics of the person class (null if the model has no person class) */
export function focusPerClass(m: Metrics | null | undefined): MetricSet | null {
  return m?.per_class?.[FOCUS_CLASS] ?? null
}
