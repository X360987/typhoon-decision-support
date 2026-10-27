import { onBeforeUnmount, ref, shallowRef, watch, type Ref, type ShallowRef } from 'vue'
import { isAbort } from '../api/client'
import { errorText } from '../lib/format'

export type LoadStatus = 'idle' | 'loading' | 'ready' | 'error'

export interface Loader<T> {
  data: ShallowRef<T | null>
  status: Ref<LoadStatus>
  error: Ref<string>
  /** True while a newer request is in flight and `data` still belongs to the previous parameters. */
  stale: Ref<boolean>
  reload: () => Promise<void>
}

interface LoaderOptions {
  /** Data is discarded (not shown as stale) when this key changes, e.g. dataset or event switches. */
  scope?: () => string
  /** Skip loading while false; data is cleared. */
  enabled?: () => boolean
}

/**
 * Loads data for the current parameters. Each request carries a sequence number and an AbortController,
 * so a slow response for old parameters can never overwrite the result for newer ones.
 */
export function useLoader<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: () => unknown,
  options: LoaderOptions = {},
): Loader<T> {
  const data = shallowRef<T | null>(null) as ShallowRef<T | null>
  const status = ref<LoadStatus>('idle')
  const error = ref('')
  const stale = ref(false)
  let seq = 0
  let controller: AbortController | null = null
  let lastScope: string | null = null

  async function reload() {
    const my = ++seq
    controller?.abort()
    if (options.enabled && !options.enabled()) {
      data.value = null
      status.value = 'idle'
      stale.value = false
      return
    }
    const scope = options.scope ? options.scope() : ''
    if (scope !== lastScope) {
      data.value = null
      lastScope = scope
    }
    controller = new AbortController()
    stale.value = data.value !== null
    status.value = 'loading'
    error.value = ''
    try {
      const result = await fetcher(controller.signal)
      if (my !== seq) return
      data.value = result
      status.value = 'ready'
      stale.value = false
    } catch (e) {
      if (my !== seq || isAbort(e)) return
      error.value = errorText(e)
      status.value = 'error'
      stale.value = data.value !== null
    }
  }

  watch(deps, () => void reload(), { immediate: true })
  onBeforeUnmount(() => {
    seq += 1
    controller?.abort()
  })

  return { data, status, error, stale, reload }
}
