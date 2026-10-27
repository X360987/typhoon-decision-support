import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type Params } from '../api/client'
import type { Dataset, EventItem, Health, ReplayMode } from '../api/types'
import { addHours, errorText, hourFloor, hoursBetween } from '../lib/format'

export type BootStatus = 'idle' | 'loading' | 'ready' | 'no_dataset' | 'no_event' | 'error'

/**
 * One query context shared by every page: dataset, event, province, analysis cursor and replay mode.
 * Pages derive their request parameters from `params` so lists, maps, cards, charts, detail and export agree.
 */
export const useContextStore = defineStore('context', () => {
  const health = ref<Health | null>(null)
  const datasets = ref<Dataset[]>([])
  const events = ref<EventItem[]>([])
  const datasetId = ref('')
  const eventId = ref<number | null>(null)
  const province = ref('')
  const replayMode = ref<ReplayMode>('retrospective')
  const cursor = ref<string | null>(null)
  const dataVersion = ref('')
  const bootStatus = ref<BootStatus>('idle')
  const bootError = ref('')
  /** Bumped after writes (import, rerun, seed) so pages reload even if the context is unchanged. */
  const revision = ref(0)

  const dataMode = computed(() => health.value?.data_mode ?? null)
  const event = computed(() => events.value.find((e) => e.id === eventId.value) ?? null)
  const ready = computed(() => bootStatus.value === 'ready' && !!datasetId.value && eventId.value != null)
  const strict = computed(() => replayMode.value === 'as_known' && !!cursor.value)
  const eventHours = computed(() => (event.value ? hoursBetween(event.value.start_time, event.value.end_time) : 0))

  /** Parameters shared by context-aware endpoints. */
  const params = computed<Params>(() => ({
    dataset_id: datasetId.value,
    event_id: eventId.value,
    province_code: province.value || undefined,
    replay_mode: replayMode.value,
    as_of: strict.value ? cursor.value : undefined,
    data_version: dataVersion.value || undefined,
  }))

  /** Changes whenever any part of the context changes; pages watch it to reload. */
  const key = computed(() => JSON.stringify([params.value, revision.value]))
  /** Changes only when the dataset or event changes; data from another event is cleared instead of shown stale. */
  const scopeKey = computed(() => `${datasetId.value}|${eventId.value}|${dataVersion.value}`)

  function defaultCursor(ev: EventItem): string {
    const span = hoursBetween(ev.start_time, ev.end_time)
    return addHours(hourFloor(ev.start_time), Math.round((span * 5) / 6))
  }

  async function loadEvents() {
    const res = await api.events(datasetId.value)
    events.value = res.items
    if (!res.items.length) {
      eventId.value = null
      cursor.value = null
      bootStatus.value = 'no_event'
      return
    }
    if (!res.items.some((e) => e.id === eventId.value)) selectEvent(res.items[0].id)
    bootStatus.value = 'ready'
  }

  async function bootstrap() {
    bootStatus.value = 'loading'
    bootError.value = ''
    try {
      health.value = await api.health()
      const ds = await api.datasets()
      datasets.value = ds.items
      if (!ds.items.length) {
        // Real mode with an empty database stays empty; demo data is only created by an explicit action.
        datasetId.value = ''
        events.value = []
        eventId.value = null
        bootStatus.value = 'no_dataset'
        return
      }
      if (!ds.items.some((d) => d.id === datasetId.value)) datasetId.value = ds.items[0].id
      await loadEvents()
    } catch (e) {
      bootStatus.value = 'error'
      bootError.value = errorText(e)
    }
  }

  function selectEvent(id: number) {
    const ev = events.value.find((e) => e.id === id)
    if (!ev) return
    eventId.value = id
    dataVersion.value = ''
    cursor.value = defaultCursor(ev)
  }

  async function selectDataset(id: string) {
    datasetId.value = id
    eventId.value = null
    dataVersion.value = ''
    await loadEvents()
  }

  function setCursor(iso: string | null) {
    if (!iso || !event.value) {
      cursor.value = iso
      return
    }
    const start = hourFloor(event.value.start_time)
    const end = hourFloor(event.value.end_time)
    const h = hourFloor(iso)
    cursor.value = h < start ? start : h > end ? end : h
  }

  function stepCursor(hours: number) {
    if (!cursor.value) return
    setCursor(addHours(cursor.value, hours))
  }

  function touch() {
    revision.value += 1
  }

  return {
    health,
    datasets,
    events,
    datasetId,
    eventId,
    province,
    replayMode,
    cursor,
    dataVersion,
    bootStatus,
    bootError,
    revision,
    dataMode,
    event,
    ready,
    strict,
    eventHours,
    params,
    key,
    scopeKey,
    bootstrap,
    loadEvents,
    selectEvent,
    selectDataset,
    setCursor,
    stepCursor,
    touch,
  }
})
