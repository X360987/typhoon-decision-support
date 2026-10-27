import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'

export interface Pager<T> {
  page: Ref<number>
  pages: ComputedRef<number>
  total: ComputedRef<number>
  rows: ComputedRef<T[]>
}

/** Client-side paging for lists the API returns in full; resets to page 1 whenever the list changes. */
export function usePager<T>(items: () => T[], size = 15): Pager<T> {
  const page = ref(1)
  const total = computed(() => items().length)
  const pages = computed(() => Math.max(1, Math.ceil(total.value / size)))
  const rows = computed(() => items().slice((page.value - 1) * size, page.value * size))
  watch(items, () => {
    page.value = 1
  })
  return { page, pages, total, rows }
}
